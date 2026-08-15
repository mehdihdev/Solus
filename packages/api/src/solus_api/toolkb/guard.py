"""SOLUS-TU-06 (SOLUSDEV-209) — the HARD tenancy ingestion guard.

THE ONLY WRITE PATH into `tool_knowledge`. Everything else — the HTTP route,
the docs-ingestion job, the review CLI — calls `ingest()`/`approve()`/
`reject()` here; a tripwire test fails the suite if `ToolKnowledgeEntry` is
constructed anywhere else in the source tree.

Rules, in order (docs/contracts/tool-knowledge.md — "allowlist at the source;
the patterns are a net under it, not the floor"):

1. CTR-05 re-validation — the NET, never the filter.
2. Closed acquired_via → provenance map; a mismatch is a lie about origin.
3. Per-path source allowlist:
   - docs: server-side only; `doc_url` host must be official vendor
     documentation (checked, then DISCARDED — there is deliberately no column
     for it). The one path that publishes directly.
   - api_geometry: `endpoint_scope` decides. A per-document endpoint may
     return a customer's imported custom features in exactly the fields a real
     control would use (Onshape `featurespecs` — the canonical trap), so
     per-document entries must name a control vendor docs already know. An
     unstated scope is treated as per-document.
   - visual: recognizes known controls only; may never introduce one.
   - operator: may introduce controls; always staged for review.
4. Idempotent dedup on the natural identity.
5. Status is COMPUTED here, never a parameter — no caller can request
   `published`.

Rejections carry NO entry content: a rejected entry is by definition suspect,
so its prose — including its control_id — stays out of exceptions and logs
(CLAUDE.md §7).
"""

import enum
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import Provenance, ToolKnowledge
from solus_api.models import utcnow
from solus_api.toolkb.catalog import is_known_vendor_control, is_vendor_doc_url
from solus_api.toolkb.schema import (
    INITIAL_CONFIDENCE,
    AcquisitionMethod,
    KnowledgeStatus,
    ToolKnowledgeEntry,
    version_keys,
)

logger = logging.getLogger("solus.toolkb")

type EmbedFn = Callable[[str], Awaitable[list[float] | None]]


class RejectReason(enum.StrEnum):
    CONTRACT_VALIDATION = "contract_validation"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    UNKNOWN_CONTROL = "unknown_control"
    PER_DOCUMENT_SOURCE = "per_document_source"
    DOC_DOMAIN_NOT_ALLOWED = "doc_domain_not_allowed"


class IngestRejectedError(Exception):
    """An entry the guard refused. `detail` names fields and rules, never content."""

    def __init__(self, reason: RejectReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class IngestContext:
    """What the CALLER knows about where the entry came from — never persisted."""

    acquired_via: AcquisitionMethod
    #: docs path only: the vendor-documentation URL. Checked, then discarded.
    doc_url: str | None = None
    #: api_geometry path only: whether the automation endpoint is global tool
    #: surface or scoped to a user's document. Unstated = per_document.
    endpoint_scope: Literal["global", "per_document"] | None = None


_PROVENANCE_FOR: Final[dict[AcquisitionMethod, Provenance]] = {
    AcquisitionMethod.DOCS: Provenance.VENDOR_DOCS,
    AcquisitionMethod.API_GEOMETRY: Provenance.OBSERVED_UI,
    AcquisitionMethod.VISUAL: Provenance.OBSERVED_UI,
    AcquisitionMethod.OPERATOR: Provenance.OPERATOR_AUTHORED,
}

_MAX_DETAIL: Final = 400


def _validated(entry: ToolKnowledge | Mapping[str, Any]) -> ToolKnowledge:
    if isinstance(entry, ToolKnowledge):
        return entry  # frozen + validated at construction; cannot exist unchecked
    try:
        return ToolKnowledge.model_validate(entry)
    except ValidationError as exc:
        # Field names and rule descriptions only — never the offending input.
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False, include_input=False)
        )
        # `from None`: ValidationError.__str__ embeds the offending input, so
        # it must not ride along as __cause__ into tracebacks/logs (review finding).
        raise IngestRejectedError(RejectReason.CONTRACT_VALIDATION, detail[:_MAX_DETAIL]) from None


async def _check_source(session: AsyncSession, tk: ToolKnowledge, ctx: IngestContext) -> None:
    if ctx.acquired_via is AcquisitionMethod.DOCS:
        if ctx.doc_url is None or not is_vendor_doc_url(tk.tool, ctx.doc_url):
            raise IngestRejectedError(
                RejectReason.DOC_DOMAIN_NOT_ALLOWED,
                f"doc_url is not official {tk.tool.value} documentation",
            )
    elif ctx.acquired_via is AcquisitionMethod.API_GEOMETRY:
        if ctx.endpoint_scope != "global" and not await is_known_vendor_control(
            session, tk.tool, tk.control_id
        ):
            raise IngestRejectedError(
                RejectReason.PER_DOCUMENT_SOURCE,
                "per-document endpoints mix vendor and customer content; "
                "the control is not known vendor surface",
            )
    elif ctx.acquired_via is AcquisitionMethod.VISUAL:
        if not await is_known_vendor_control(session, tk.tool, tk.control_id):
            raise IngestRejectedError(
                RejectReason.UNKNOWN_CONTROL,
                "visual detection may only recognize documented controls, never introduce one",
            )
    # OPERATOR: may introduce controls; review is the control (approve()).


async def _find_live(session: AsyncSession, tk: ToolKnowledge) -> ToolKnowledgeEntry | None:
    return (
        await session.execute(
            select(ToolKnowledgeEntry).where(
                ToolKnowledgeEntry.deleted_at.is_(None),
                ToolKnowledgeEntry.tool == tk.tool,
                ToolKnowledgeEntry.control_id == tk.control_id,
                ToolKnowledgeEntry.surface == tk.surface,
                ToolKnowledgeEntry.version_range == tk.version_range,
            )
        )
    ).scalar_one_or_none()


async def ingest(
    session: AsyncSession,
    *,
    entry: ToolKnowledge | Mapping[str, Any],
    ctx: IngestContext,
    embed: EmbedFn | None = None,
) -> ToolKnowledgeEntry:
    """Admit one entry into the store, or raise `IngestRejectedError`.

    Returns the existing live row unchanged when the identity already exists
    (idempotent). Status is computed: only the docs path publishes directly;
    everything else is a `candidate` until `approve()`.
    """
    tk = _validated(entry)
    expected = _PROVENANCE_FOR[ctx.acquired_via]
    if tk.provenance is not expected:
        raise IngestRejectedError(
            RejectReason.PROVENANCE_MISMATCH,
            f"{ctx.acquired_via.value} entries must carry provenance {expected.value}",
        )
    await _check_source(session, tk, ctx)

    try:
        low, high = version_keys(tk.version_range)
    except ValueError:
        # The CTR-05 regex is looser than the key grammar ("==2.0", "<<2.0",
        # ">=3.0 <2.0", components >9999 all pass it) — reject, never 500,
        # and never chain the ValueError (its message quotes the input).
        raise IngestRejectedError(
            RejectReason.CONTRACT_VALIDATION, "version_range: unsupported range expression"
        ) from None

    existing = await _find_live(session, tk)
    if existing is not None:
        return await _reconcile_existing(session, existing, tk, ctx, embed)

    row = ToolKnowledgeEntry(
        tool=tk.tool,
        version_range=tk.version_range,
        surface=tk.surface,
        control_id=tk.control_id,
        label=tk.label,
        effect=tk.effect,
        description=tk.description,
        menu_path=None if tk.invocation is None else tk.invocation.menu_path,
        shortcut=None if tk.invocation is None else tk.invocation.shortcut,
        locator_x=None if tk.locator is None else tk.locator.x,
        locator_y=None if tk.locator is None else tk.locator.y,
        locator_w=None if tk.locator is None else tk.locator.w,
        locator_h=None if tk.locator is None else tk.locator.h,
        provenance=tk.provenance,
        status=(
            KnowledgeStatus.PUBLISHED
            if ctx.acquired_via is AcquisitionMethod.DOCS
            else KnowledgeStatus.CANDIDATE
        ),
        acquired_via=ctx.acquired_via,
        confidence=INITIAL_CONFIDENCE[ctx.acquired_via],
        version_min_key=low,
        version_max_key=high,
        embedding=await _embed_or_none(embed, tk),
    )
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError:
        # Lost a check-then-insert race with a concurrent ingest of the same
        # identity — the partial unique index is the arbiter; converge on the
        # winner idempotently instead of surfacing a 500 (review finding).
        raced = await _find_live(session, tk)
        if raced is None:
            raise
        return await _reconcile_existing(session, raced, tk, ctx, embed)
    # Accepted entries may be named in logs; rejected ones never are.
    logger.info(
        "toolkb ingest accepted: tool=%s control=%s status=%s via=%s",
        tk.tool.value,
        tk.control_id,
        row.status.value,
        ctx.acquired_via.value,
    )
    return row


async def _embed_or_none(embed: EmbedFn | None, tk: ToolKnowledge) -> list[float] | None:
    if embed is None:
        return None
    try:
        return await embed(f"{tk.label}. {tk.description}")
    except Exception:  # noqa: BLE001 — embedding is best-effort by contract
        logger.warning("toolkb embed failed; storing entry without vector", exc_info=True)
        return None


async def _reconcile_existing(
    session: AsyncSession,
    existing: ToolKnowledgeEntry,
    tk: ToolKnowledge,
    ctx: IngestContext,
    embed: EmbedFn | None,
) -> ToolKnowledgeEntry:
    """Idempotent return — except an authoritative docs ingest OVERTAKES a
    lower-trust row for the same identity.

    Without this, a candidate that reached the identity first (an operator
    submission, say) silently blocks vendor-docs publication forever (review
    finding). Content is REPLACED with the docs version — publishing the
    earlier submitter's prose under docs trust would be worse than the block.
    """
    if (
        ctx.acquired_via is not AcquisitionMethod.DOCS
        or existing.acquired_via is AcquisitionMethod.DOCS
    ):
        return existing
    existing.label = tk.label
    existing.effect = tk.effect
    existing.description = tk.description
    existing.menu_path = None if tk.invocation is None else tk.invocation.menu_path
    existing.shortcut = None if tk.invocation is None else tk.invocation.shortcut
    existing.locator_x = None if tk.locator is None else tk.locator.x
    existing.locator_y = None if tk.locator is None else tk.locator.y
    existing.locator_w = None if tk.locator is None else tk.locator.w
    existing.locator_h = None if tk.locator is None else tk.locator.h
    existing.provenance = tk.provenance
    existing.status = KnowledgeStatus.PUBLISHED
    existing.acquired_via = AcquisitionMethod.DOCS
    existing.confidence = INITIAL_CONFIDENCE[AcquisitionMethod.DOCS]
    existing.embedding = await _embed_or_none(embed, tk)
    await session.flush()
    logger.info(
        "toolkb docs ingest overtook lower-trust row: id=%s tool=%s control=%s",
        existing.id,
        tk.tool.value,
        tk.control_id,
    )
    return existing


async def _live_row(session: AsyncSession, entry_id: uuid.UUID) -> ToolKnowledgeEntry:
    row = await session.get(ToolKnowledgeEntry, entry_id)
    if row is None or row.deleted_at is not None:
        raise LookupError(f"no live tool_knowledge entry {entry_id}")
    return row


async def approve(session: AsyncSession, *, entry_id: uuid.UUID) -> ToolKnowledgeEntry:
    """Operator review: promote a candidate. The ONLY path besides docs to published."""
    row = await _live_row(session, entry_id)
    if row.status is KnowledgeStatus.PUBLISHED:
        raise ValueError(f"entry {entry_id} is already published")
    row.status = KnowledgeStatus.PUBLISHED
    row.last_verified_at = utcnow()
    await session.flush()
    logger.info("toolkb approved: id=%s tool=%s control=%s", row.id, row.tool.value, row.control_id)
    return row


async def reject(session: AsyncSession, *, entry_id: uuid.UUID) -> None:
    """Operator review: soft-delete a candidate (or retract a published row)."""
    row = await _live_row(session, entry_id)
    row.deleted_at = utcnow()
    await session.flush()
    logger.info("toolkb rejected: id=%s tool=%s", row.id, row.tool.value)
