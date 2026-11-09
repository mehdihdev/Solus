"""SOLUSDEV-321 P3-T4 — `extract_rulebook`: a rulebook's limits as CANDIDATE constraints (R58).

A rulebook (a competition's rules, a customer's specification) filed as a PDF in the project's
`.solus` is read through `read_document`'s own extractor (`read_pages`). Its pages are rendered,
then one metered vision call a page runs under the requester's identity (`purpose="extract"`)
and returns page-cited proposals.

A proposal becomes a candidate row `{payload, text, page, quote}` when it states ONE finite
number, a unit and a bound ("at most", "minimum", "no less than", ...).
- `payload` is a whole `ConstraintMeta`, which the confirm path takes as it is.
- `text` is the line a person files.
- `page` and `quote` are the citation.
Any other proposal is counted in `notes`; none is guessed into a bound.

Nothing is written. The rows live only in this tool's result. A candidate becomes a constraint
only when the person files its `text` under `constraints/rules` and sets its `payload` through
`PATCH /solus/entries/{id}/payload` (docs/api/solus.md §3.2). The tool only reads, so it is
ungated.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy import select

from solus_api.agent.prompt import _encode  # the prompt layer's own encoder: what the model reads
from solus_api.agent.tools.read_document import (
    DEFAULT_ARTIFACT_TTL_SECONDS,
    PAGES_SCHEMA,
    READ_TIMEOUT_SECONDS,
    read_artifact,
    read_pages,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.models import SolusEntry, SolusEntryKind, SolusSection
from solus_api.services.solus_payloads import ConstraintMeta

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.documents.extract import DocumentProposal
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.storage import ArtifactStore

Comparator = Literal["<", "<=", ">=", ">"]

#: Where a person files a candidate: the cell whose payload model is `ConstraintMeta`.
RULES_SECTION: Final = SolusSection.CONSTRAINTS
RULES_SUBSECTION: Final = "rules"
#: Rows a call returns, so the result fits its cap whole instead of as a cut prefix.
#: The result's cap as the prompt layer encodes it (`ToolDescriptor.result_cap`). Rows are added
#: while the whole result fits it (m8); `_NOTE_ROOM` keeps space for the note naming the rest.
RESULT_CAP: Final = 16_000
_NOTE_ROOM: Final = 128
_UNCAPPED: Final = 2**31
_SOURCE_CAP: Final = 80
#: Solus-authored. The extractor fences it as data; it steers what each page read transcribes.
_QUESTION: Final = (
    "the numeric limits a design must meet: each maximum, minimum, at most or at least, "
    "with its value and unit"
)
#: Bound phrases. Where two start alike, the longer comes first, so "no more than" reads as
#: `<=` and never as the `>` of "more than".
_BOUNDS: Final[tuple[tuple[str, Comparator], ...]] = (
    ("less than or equal to", "<="),
    ("greater than or equal to", ">="),
    ("no more than", "<="),
    ("not more than", "<="),
    ("no less than", ">="),
    ("not less than", ">="),
    ("no fewer than", ">="),
    ("not to exceed", "<="),
    ("not exceed", "<="),
    ("not be exceeded", "<="),
    ("at most", "<="),
    ("at least", ">="),
    ("up to", "<="),
    ("limited to", "<="),
    ("maximum", "<="),
    ("minimum", ">="),
    ("or less", "<="),
    ("or more", ">="),
    ("less than", "<"),
    ("fewer than", "<"),
    ("greater than", ">"),
    ("more than", ">"),
    ("≤", "<="),
    ("<=", "<="),
    ("≥", ">="),
    (">=", ">="),
    ("<", "<"),
    (">", ">"),
)
_COMPARATOR_OF: Final[dict[str, Comparator]] = dict(_BOUNDS)
_BOUND_RE: Final = re.compile(
    "(?<![a-z])(?:" + "|".join(re.escape(phrase) for phrase, _ in _BOUNDS) + ")(?![a-z])"
)
_NEGATION_RE: Final = re.compile(r"\b(?:not|no|never|cannot|nor)\b|n't\b")

_ROW_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "payload": {"type": "object"},
        "text": {"type": "string"},
        "page": {"type": "integer"},
        "quote": {"type": "string"},
    },
    "required": ["payload", "text", "page", "quote"],
    "additionalProperties": False,
}

EXTRACT_RULEBOOK_DESCRIPTOR: Final = ToolDescriptor(
    name="extract_rulebook",
    description=(
        "Read a rulebook or specification PDF filed in this project's .solus (pass its "
        "entry_id) and return the numeric limits it states as CANDIDATE constraints. Each row "
        "holds the payload for a constraints/rules entry, the line to file, and the page and "
        "quote it came from. Nothing is filed. Show the person the rows: a candidate becomes a "
        "constraint only when they file its text under constraints/rules and confirm its "
        "payload. At most 12 pages per call; pass `pages` (1-based) to pick them."
    ),
    params={
        "type": "object",
        "properties": {
            "entry_id": {"type": "string", "format": "uuid"},
            "pages": PAGES_SCHEMA,
        },
        "required": ["entry_id"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "entry_id": {"type": "string", "format": "uuid"},
            "title": {"type": ["string", "null"]},
            "section": {"type": "string"},
            "subsection": {"type": "string"},
            "pages_read": {"type": "array", "items": {"type": "integer"}},
            "rows": {"type": "array", "items": _ROW_SCHEMA},
            "notes": {"type": "array", "items": {"type": "string"}},
            "truncated": {"type": "boolean"},
        },
        "required": [
            "entry_id",
            "title",
            "section",
            "subsection",
            "pages_read",
            "rows",
            "notes",
            "truncated",
        ],
        "additionalProperties": False,
    },
    timeout_seconds=READ_TIMEOUT_SECONDS,
    result_cap=RESULT_CAP,
)


def _single_value(text: str) -> float | None:
    """`text` as one finite number, or None ("1.71 to 3.6", "nan", "0x20")."""
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _comparator(proposal: DocumentProposal) -> Comparator | None:
    """The one bound the proposal's name and quote state together. None when they state none,
    or two that disagree, or a negation outside the listed phrases ("cannot be more than").

    ponytail: phrase matching, not parsing, which is why every row is only a candidate. A
    negation is a skip, never a flipped bound."""
    text = f"{proposal.name} {proposal.quote}".lower()
    found = {_COMPARATOR_OF[phrase] for phrase in _BOUND_RE.findall(text)}
    if len(found) != 1 or _NEGATION_RE.search(_BOUND_RE.sub(" ", text)):
        return None
    return found.pop()


def _rule_quantity(name: str) -> str:
    """The name without its bound words, in snake_case: "Maximum accumulator voltage" →
    `accumulator_voltage`."""
    bare = _BOUND_RE.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_")[:64]


def _candidate_row(
    proposal: DocumentProposal, *, entry_id: uuid.UUID, source: str
) -> dict[str, Any] | None:
    limit, comparator = _single_value(proposal.value), _comparator(proposal)
    quantity, unit = _rule_quantity(proposal.name), (proposal.unit or "").strip()
    if limit is None or comparator is None or not quantity or not unit:
        return None
    try:  # model output is untrusted: a row that does not validate is dropped, never fixed up
        payload = ConstraintMeta(
            quantity=quantity,
            limit=limit,
            unit=unit,
            comparator=comparator,
            source_entry_id=entry_id,
        )
    except ValidationError:
        return None
    stated = f"{proposal.name} {comparator} {proposal.value.strip()} {unit}"
    return {
        "payload": payload.model_dump(mode="json"),
        "text": f"{stated} ({source}, page {proposal.page})",
        "page": proposal.page,
        "quote": proposal.quote,
    }


def rulebook_rows(
    proposals: Sequence[DocumentProposal], *, entry_id: uuid.UUID, source: str = "rulebook"
) -> tuple[list[dict[str, Any]], int]:
    """The candidate rows the proposals state, in page order, and the count of proposals that
    stated no single number, unit and bound. Never raises; nothing here writes."""
    cited = source[:_SOURCE_CAP]
    rows = [
        row
        for proposal in proposals
        if (row := _candidate_row(proposal, entry_id=entry_id, source=cited)) is not None
    ]
    return rows, len(proposals) - len(rows)


def _fitting(rows: Sequence[dict[str, Any]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows, in order, while the whole result fits `RESULT_CAP` as the prompt layer encodes it
    (m8). That encoding is compact ASCII JSON, in which a non-ASCII character takes six. Room is
    kept for the overflow note, so the model never reads a row cut in half."""
    used = len(_encode({"ok": True, "value": result}, _UNCAPPED)) + _NOTE_ROOM
    kept: list[dict[str, Any]] = []
    for row in rows:
        used += len(_encode(row, _UNCAPPED)) + 1  # and the comma before it
        if used > RESULT_CAP:
            break
        kept.append(row)
    return kept


def _entry_uuid(raw: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise ToolException("entry_id must be a UUID", code=ToolErrorCode.INVALID_ARGS) from None


class _RulebookReader:
    """The tool, bound to ONE project and the requesting user by Solus code."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        store: ArtifactStore,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        secret_store: SecretStore,
        redis: Any,
        enqueue: Any,
        artifact_ttl_seconds: int,
    ) -> None:
        self._sessions = session_factory
        self._store = store
        self._project_id = project_id
        self._user_id = user_id
        self._secret_store = secret_store
        self._redis = redis
        self._enqueue = enqueue
        self._ttl = artifact_ttl_seconds

    async def _rulebook(self, session: AsyncSession, entry_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """The filed document's name and artifact, in the bound project only. An unknown and a
        foreign entry are the same `not_found`. It is a plain read: no project lock is held
        across the page reads."""
        entry = await session.scalar(
            select(SolusEntry).where(
                SolusEntry.id == entry_id,
                SolusEntry.project_id == self._project_id,
                SolusEntry.deleted_at.is_(None),
            )
        )
        if entry is None:
            raise ToolException("no such entry in this project", code=ToolErrorCode.NOT_FOUND)
        if entry.kind is not SolusEntryKind.ARTIFACT or entry.artifact_id is None:
            raise ToolException(
                "that entry is not a filed document", code=ToolErrorCode.INVALID_ARGS
            )
        return entry.text or "rulebook", entry.artifact_id

    async def extract(self, args: dict[str, Any]) -> dict[str, Any]:
        entry_id = _entry_uuid(args["entry_id"])
        async with self._sessions() as session:
            source, artifact_id = await self._rulebook(session, entry_id)
            _, data = await read_artifact(
                session,
                self._store,
                project_id=self._project_id,
                user_id=self._user_id,
                artifact_id=artifact_id,
                ttl_seconds=self._ttl,
            )
            rendered, proposals, notes = await read_pages(
                data,
                pages=args.get("pages"),
                question=_QUESTION,
                secret_store=self._secret_store,
                user_id=self._user_id,
                session=session,
                redis=self._redis,
                enqueue=self._enqueue,
            )
        rows, skipped = rulebook_rows(proposals, entry_id=entry_id, source=source)
        if skipped:
            notes.append(f"{skipped} proposal(s) stated no single number, unit and bound")
        result: dict[str, Any] = {
            "entry_id": str(entry_id),
            "title": rendered.title,
            "section": RULES_SECTION.value,
            "subsection": RULES_SUBSECTION,
            "pages_read": [page.index for page in rendered.pages],
            "rows": [],
            "notes": notes,
            "truncated": rendered.page_count > len(rendered.pages),
        }
        result["rows"] = _fitting(rows, result)
        if dropped := len(rows) - len(result["rows"]):
            notes.append(f"{dropped} more candidate(s) did not fit; read fewer pages to see them")
        return result


def register_rulebook_tool(
    registry: ToolRegistry,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    secret_store: SecretStore,
    redis: Any,
    enqueue: Any,
    artifact_ttl_seconds: int = DEFAULT_ARTIFACT_TTL_SECONDS,
) -> None:
    """Add `extract_rulebook`, bound to ONE project and the requesting user by Solus code: no
    argument names a project, and their identity meters the page reads."""
    reader = _RulebookReader(
        session_factory=session_factory,
        store=store,
        project_id=project_id,
        user_id=user_id,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        artifact_ttl_seconds=artifact_ttl_seconds,
    )
    registry.register(InProcessTool(EXTRACT_RULEBOOK_DESCRIPTOR, reader.extract))
