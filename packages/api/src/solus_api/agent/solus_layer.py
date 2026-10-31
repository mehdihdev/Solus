"""SOLUSDEV-321 P0-T6 — `.solus` on the tree: what the `.solus` and findings layers of SOL's
context read, and how each renders (docs/architecture/sol-context-layers.md §1).

- standing (`solus_standing`, prefix): every goal and constraint a person wrote or confirmed,
  newest first — whole while that fits in 1,000 tokens, else one title line each — then the
  budgets, a line per budget. A row SOL filed is a candidate, never standing.
- scoped (`solus_scoped`, prefix): the `errors` entries that blame a part in scope, each with
  the machine it happened on.
- findings (`findings`, prefix): the open findings observing a part in scope, every severity;
  a one-row read of the non-info ones (warning, critical) marks the turn
  `Context.finding_in_scope`, which P0-T7 routes hard. After them, the envelope of each part in
  scope that has one (P2-T1, `livebench/findings/envelopes.py`): up to four quantities, a line
  each, packed under the same layer cap.
- relevant (`retrieval`, suffix): the `.solus` entries the message matches that the prefix does
  not already carry, those bound to a part in scope first; the environment divergences table
  only for an environment question.

Every read goes through ONE read-only session of the request's sessionmaker, scoped by
`project_id` (`_solus_reads`); `SolSystems` gains nothing. Every ingested string is redacted
and capped before it renders, and stays data inside the context's fences.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from solus_api.agent.interfaces import EntityRead
from solus_api.agent.layers import ContextSection, SectionKind, _cite_part, _clip, _under_cap
from solus_api.agent.tools.untrusted import redact_text, redact_value
from solus_api.checkers.interface import Severity
from solus_api.graph import kinds
from solus_api.graph.findings import list_findings
from solus_api.livebench.findings.envelopes import (
    QUANTITIES,
    Envelope,
    envelope_line,
    part_envelopes,
)
from solus_api.models import GraphEntity, SolusEntry, SolusEntryKind, SolusSection
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.type_estimator import chars_for_tokens, estimate_tokens
from solus_api.services.budgets import find_budgets_entry
from solus_api.services.environment_divergence import (
    CAUSES,
    DIVERGENCES_SUBSECTION,
    find_divergences_entry,
)
from solus_api.services.search import SolusHit, search_solus
from solus_api.services.solus_config import SECTION_LABELS, load_sections
from solus_api.services.solus_payloads import (
    BudgetLine,
    Budgets,
    ConstraintMeta,
    EnvironmentDivergencesDoc,
    ErrorMeta,
    GoalMeta,
    MachineDivergences,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("solus.agent.solus_layer")

#: The one token estimator (models.yaml `type_estimator:`), as context.py packs with.
_ESTIMATOR = default_orchestration_config().type_estimator
#: One `.solus` entry renders to at most this many chars (docs/api/solus.md
#: allows 4,000 per entry; the layer is a digest, not the panel).
_SOLUS_ENTRY_CAP = 500
#: The standing digest renders whole while it costs at most this many tokens; past
#: that every entry is one title line that keeps its status or bound.
_STANDING_WHOLE_TOKENS: Final = 1000
_TITLE_CAP = 80
#: The search route's own bound on `q` (routers/search.py): an 8,000-char message must
#: not become thousands of trigram probes. ponytail: a prefix, not a keyword pick (P1-T1).
_QUERY_CHARS = 255
_BUDGETS_CAP = 2000
#: Open findings read per turn; scoped subjects named per finding; headline/evidence chars.
_FINDINGS_LIMIT = 20
_FINDING_SUBJECTS = 4
_FINDING_CAP = 200
#: The quantities of one part whose envelope the findings layer shows, and the knob the
#: envelopes derive their warn bound from (models.yaml `envelopes:`).
_ENVELOPE_QUANTITIES: Final = 4
_ENVELOPES: Final = default_orchestration_config().envelopes
#: The severities of an open finding that routes its turn HARD (P0-T7); an info one is advisory.
_ROUTING_SEVERITIES: Final = (Severity.WARNING, Severity.CRITICAL)
#: The divergences table's bound, and how many items it names after the per-machine counts.
_DIVERGENCE_TOKENS = 200
_DIVERGENCE_ITEMS = 3
_DIVERGENCES: Final = (SolusSection.ENVIRONMENT.value, DIVERGENCES_SUBSECTION)


@dataclass(frozen=True)
class SolusReads:
    """What the `.solus` and findings layers read for one turn, in ONE session
    (`_solus_reads`); the default is the empty read of a turn without a sessionmaker, or whose
    read failed (logged) — the standing, scoped and findings layers then say `.solus not loaded`."""

    rows: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    budgets: SolusEntry | None = None
    #: The `errors` entries that blame a part in scope, newest first, with their metadata.
    errors: tuple[tuple[Mapping[str, Any], ErrorMeta], ...] = ()
    machines: Mapping[UUID, GraphEntity] = field(default_factory=dict)
    hits: tuple[SolusHit, ...] = ()
    divergences: SolusEntry | None = None
    findings: tuple[GraphEntity, ...] = ()
    #: An open non-info finding observes a part in scope: its own one-row read, since the
    #: 20 rows above could all be info (P0-T7 routes such a turn HARD).
    finding_in_scope: bool = False
    #: The envelopes of the parts in scope (P2-T1): the bounds each quantity of a part runs
    #: inside, built from its config, definition, scene joint and expected value.
    envelopes: tuple[Envelope, ...] = ()


async def _solus_reads(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    project_id: UUID,
    *,
    query: str,
    scoped_ids: frozenset[UUID],
    search_limit: int,
    environment_question: bool,
) -> SolusReads | None:
    """Every `.solus` and findings read of the turn, in ONE read-only session of the
    request's sessionmaker, each scoped by `project_id`. None without a sessionmaker, or when
    a read fails (logged, never raised into the turn): the standing, scoped and findings
    layers then say ".solus not loaded"."""
    if sessionmaker is None:
        return None
    try:
        async with sessionmaker() as session:
            rows = await load_sections(session, project_id)
            errors = _scoped_errors(rows, scoped_ids)
            machine_ids = {meta.machine_id for _, meta in errors if meta.machine_id is not None}
            machines: Iterable[GraphEntity] = ()
            if machine_ids:  # one batch read, never one per entry
                machines = await session.scalars(
                    select(GraphEntity).where(
                        GraphEntity.id.in_(machine_ids),
                        GraphEntity.project_id == project_id,
                        GraphEntity.kind == kinds.MACHINE,
                        GraphEntity.deleted_at.is_(None),
                    )
                )
            findings: Sequence[GraphEntity] = ()
            routing: Sequence[GraphEntity] = ()
            if scoped_ids:
                findings, _ = await list_findings(
                    session, project_id, status="open", subjects=scoped_ids, limit=_FINDINGS_LIMIT
                )
                # Read, not filtered from the rows above: 20 standing infos could fill those.
                routing, _ = await list_findings(
                    session,
                    project_id,
                    status="open",
                    subjects=scoped_ids,
                    severities=_ROUTING_SEVERITIES,
                    limit=1,
                )
            divergences = None
            if environment_question:
                divergences = await find_divergences_entry(session, project_id)
            hits = await search_solus(session, project_id, query[:_QUERY_CHARS], limit=search_limit)
            budgets = await find_budgets_entry(session, project_id)
            return SolusReads(
                rows=rows,
                budgets=budgets,
                errors=errors,
                machines={machine.id: machine for machine in machines},
                hits=tuple(hits),
                divergences=divergences,
                findings=tuple(findings),
                finding_in_scope=bool(routing),
                envelopes=await _scoped_envelopes(session, project_id, scoped_ids),  # the last read
            )
    except Exception:  # noqa: BLE001 — a `.solus` read must never fail the turn
        logger.exception("solus layer reads failed project_id=%s", project_id)
        return None


async def _scoped_envelopes(
    session: AsyncSession, project_id: UUID, scoped_ids: frozenset[UUID]
) -> tuple[Envelope, ...]:
    """The envelopes of the parts in scope, read in the turn's one session. Its own failure
    domain: a failed read is logged and costs only the envelopes, never the `.solus` layers the
    rest of the session loaded."""
    if not scoped_ids:
        return ()
    try:
        found = await part_envelopes(session, project_id, scoped_ids, envelopes=_ENVELOPES)
    except Exception:  # noqa: BLE001 — envelopes are context, never a failed turn
        logger.exception("envelope reads failed project_id=%s", project_id)
        return ()
    return tuple(envelope for part in found.values() for envelope in part)


def _sized(kind: SectionKind, text: str, citation: str, score: float = 1.0) -> ContextSection:
    tokens = estimate_tokens(text, config=_ESTIMATOR)
    return ContextSection(kind=kind, text=text, tokens=tokens, score=score, citation=citation)


def _meta[M: BaseModel](model: type[M], payload: object) -> M | None:
    """A stored payload as its typed model; None when malformed — no metadata, never a
    failed turn (empty beats invented)."""
    try:
        return model.model_validate(payload or {})
    except ValidationError:
        return None


def _newest_first(entries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    # str(datetime) sorts chronologically within one tz — the ORM's utcnow.
    return sorted(
        entries, key=lambda e: (str(e.get("created_at") or ""), str(e.get("id"))), reverse=True
    )


def _solus_body(entry: Mapping[str, Any]) -> str:
    kind = entry.get("kind")
    if kind == "artifact":
        media = entry.get("media_type")
        return f"file {entry.get('name') or '?'}" + (f" ({media})" if media else "")
    if kind == "config":
        return str(redact_value(entry.get("payload"))) if entry.get("payload") else ""
    return str(entry.get("text") or "")


def _section_label(raw_section: str) -> str:
    try:
        return SECTION_LABELS[SolusSection(raw_section)]
    except ValueError:
        return raw_section


def _solus_citation(section: str, entry_id: object) -> str:
    return f"[solus:{_cite_part(section, '?')}:{_cite_part(str(entry_id), '?')}]"


def _solus_section(
    entry: Mapping[str, Any],
    *,
    kind: SectionKind = "solus",
    body: str | None = None,
    tail: str = "",
) -> ContextSection:
    """`<label> · <author>: <body><tail>`; the entry's own body, clipped, unless given."""
    raw_section = str(entry.get("section") or "?")
    author = str(entry.get("author") or "user")
    text = _clip(_solus_body(entry), _SOLUS_ENTRY_CAP) if body is None else body
    return _sized(
        kind,
        redact_text(f"{_section_label(raw_section)} · {author}: {text}{tail}"),
        _solus_citation(raw_section, entry.get("id")),
    )


def solus_sections(
    rows: Mapping[str, Sequence[Mapping[str, Any]]], *, cap_tokens: int
) -> tuple[list[ContextSection], list[str]]:
    """`.solus` rows as sections: newest first, one capped section per entry, packed
    under `cap_tokens` with the same strict cutoff as every other group. Returns
    (kept, dropped citations)."""
    entries = _newest_first(entry for group in rows.values() for entry in group)
    return _under_cap([_solus_section(entry) for entry in entries], cap_tokens)


def standing_sections(
    reads: SolusReads, *, cap_tokens: int
) -> tuple[list[ContextSection], list[str], frozenset[str | None]]:
    """The standing digest: every goal and constraint a person wrote or confirmed, newest
    first — whole while that fits in 1,000 tokens, else one title line each — then the
    budgets, a line per budget; packed under `cap_tokens`. A row SOL filed is a candidate,
    never standing: it reaches the prompt only as a relevant hit. Returns (kept, cut, the
    citations kept WHOLE) — an entry reduced to its title stays reachable by its body."""
    entries = [
        entry
        for section in (SolusSection.GOALS.value, SolusSection.CONSTRAINTS.value)
        for entry in reads.rows.get(section, ())
        if entry.get("author") != "sol" and entry.get("kind") != "config"
    ]
    whole, over = solus_sections({"standing": entries}, cap_tokens=_STANDING_WHOLE_TOKENS)
    digest = [_title_section(entry) for entry in _newest_first(entries)] if over else whole
    kept, cut = _under_cap([*digest, *_budgets_section(reads.budgets)], cap_tokens)
    titled: set[str | None] = {s.citation for s in digest} if over else set()
    return kept, cut, frozenset(s.citation for s in kept if s.citation not in titled)


def _title_section(entry: Mapping[str, Any]) -> ContextSection:
    """A degraded digest line: the entry's first line, then a goal's status or a quantified
    constraint's bound."""
    first = _clip(next(iter(_solus_body(entry).strip().splitlines()), ""), _TITLE_CAP)
    if entry.get("section") == SolusSection.GOALS.value:
        goal = _meta(GoalMeta, entry.get("payload"))
        return _solus_section(entry, body=first, tail=f" [status={goal.status}]" if goal else "")
    bound = _meta(ConstraintMeta, entry.get("payload"))
    if bound is None or not bound.is_quantified:
        return _solus_section(entry, body=first)
    tail = f" [{bound.quantity} {bound.comparator} {bound.limit:g} {bound.unit}]"
    return _solus_section(entry, body=first, tail=tail)


def _budgets_section(entry: SolusEntry | None) -> list[ContextSection]:
    """The `constraints/budgets` document as ONE section, a line per budget."""
    doc = _meta(Budgets, entry.payload) if entry is not None else None
    if entry is None or doc is None or not doc.budgets:
        return []
    text = "\n".join(["Constraints · budgets:", *map(_budget_row, doc.budgets)])
    citation = _solus_citation(SolusSection.CONSTRAINTS.value, entry.id)
    return [_sized("solus", redact_text(_clip(text, _BUDGETS_CAP)), citation)]


def _budget_row(line: BudgetLine) -> str:
    current = "?" if line.current is None else f"{line.current:g}"
    if line.limit is None:
        return f"{line.name} {current} {line.unit}, no limit known ({line.status})"
    return f"{line.name} {current}/{line.limit:g} {line.unit} ({line.status})"


def _scoped_errors(
    rows: Mapping[str, Sequence[Mapping[str, Any]]], scoped: frozenset[UUID]
) -> tuple[tuple[Mapping[str, Any], ErrorMeta], ...]:
    """The `errors` entries whose metadata blames a part in scope, newest first."""
    entries = _newest_first(rows.get(SolusSection.ERRORS.value, ()))
    metas = ((entry, _meta(ErrorMeta, entry.get("payload"))) for entry in entries)
    return tuple((e, meta) for e, meta in metas if meta is not None and meta.entity_id in scoped)


def scoped_error_sections(reads: SolusReads) -> list[ContextSection]:
    """The scoped layer: each `errors` entry that blames a part in scope, newest first,
    with its status and count and the machine it happened on."""
    return [
        _solus_section(
            entry,
            kind="solus_scoped",
            tail=f" [status={meta.status} count={meta.count}]"
            + _machine_label(reads.machines, meta.machine_id),
        )
        for entry, meta in reads.errors
    ]


def _machine_label(machines: Mapping[UUID, GraphEntity], machine_id: UUID | None) -> str:
    machine = machines.get(machine_id) if machine_id is not None else None
    if machine is None:  # no machine named, or none live in this project any more
        return ""
    host, os_name, arch = (
        _clip(str(machine.attrs.get(key) or fallback), _TITLE_CAP)
        for key, fallback in (("hostname", machine.name), ("os", "?"), ("arch", "?"))
    )
    return f" on {host} ({os_name}/{arch})"


def finding_sections(reads: SolusReads, scoped: Iterable[EntityRead]) -> list[ContextSection]:
    """The findings layer: each open finding observing a part in scope, newest-created first
    — headline, severity, rule, the scoped subjects it names and one line of its newest
    evidence. Never the re-raise count or the evidence history (`items`): a re-raise that
    changes nothing leaves the prefix byte-identical."""
    names = {str(entity.id): _clip(entity.name, _TITLE_CAP) for entity in scoped}
    sections = []
    # ponytail: the 20 rows are list_findings' most recently UPDATED, so past 20 open findings
    # in scope a re-raise can change which 20 show; a created_at-ordered read is the upgrade.
    for row in sorted(reads.findings, key=lambda r: (r.created_at, r.id), reverse=True):
        a = row.attrs
        subjects = [names[s] for s in a.get("subjects", []) if s in names][:_FINDING_SUBJECTS]
        newest = {k: v for k, v in (a.get("evidence") or {}).items() if k != "items"}
        evidence = _clip(str(redact_value(newest)), _FINDING_CAP)
        text = (
            f"{_clip(str(a.get('headline') or row.name), _FINDING_CAP)} [severity="
            f"{a.get('severity')} rule={a.get('rule_id')}] subjects: {', '.join(subjects)}\n"
            f"Evidence: {evidence}"
        )
        sections.append(_sized("finding", redact_text(text), f"[finding:{row.id}]"))
    return sections


def envelope_sections(reads: SolusReads, scoped: Iterable[EntityRead]) -> list[ContextSection]:
    """The findings layer's envelope sections, packed after the findings: each part in scope that
    has an envelope, by name, shows up to four of its quantities in the fixed order, one line
    each — what normal, warn and limit look like and where each bound came from — cited
    `[envelope:<part>:<quantity>]` so the reply's citations verify. A part with none says
    nothing."""
    names = {entity.id: _clip(entity.name, _TITLE_CAP) for entity in scoped}
    by_part: dict[UUID, list[Envelope]] = {}
    for envelope in reads.envelopes:
        by_part.setdefault(envelope.part_id, []).append(envelope)
    sections = []
    for part_id in sorted((p for p in by_part if p in names), key=lambda p: (names[p], str(p))):
        shown = sorted(by_part[part_id], key=lambda e: QUANTITIES.index(e.quantity))
        for envelope in shown[:_ENVELOPE_QUANTITIES]:
            text = redact_text(f"{names[part_id]} · {envelope_line(envelope)}")
            citation = (
                f"[envelope:{_cite_part(str(part_id), '?')}:{_cite_part(envelope.quantity, '?')}]"
            )
            sections.append(_sized("envelope", text, citation))
    return sections


def relevant_solus_sections(
    hits: Sequence[SolusHit],
    *,
    rendered: Collection[str | None],
    scoped: frozenset[UUID],
    k: int,
) -> tuple[list[ContextSection], list[ContextSection]]:
    """The first `k` `.solus` entries the message matches that the prefix does not already
    carry whole, as retrieval evidence: (bound to a part in scope, the rest). The caller
    over-fetches, so carried entries do not take the slots. The divergences document is
    never one — it renders only through its own gate (`divergence_sections`)."""
    bound: list[ContextSection] = []
    unbound: list[ContextSection] = []
    for hit in hits:
        if len(bound) + len(unbound) >= k:
            break
        section = _solus_hit_section(hit)
        if section.citation in rendered or (hit.section, hit.subsection) == _DIVERGENCES:
            continue
        (bound if hit.entity_id in scoped else unbound).append(section)
    return bound, unbound


def _solus_hit_section(hit: SolusHit) -> ContextSection:
    """Kind `error` for the errors section, else `document`: the entry, then the matching
    window when it adds to it. A note SOL filed says so."""
    author = " · sol" if hit.kind == SolusEntryKind.SOL.value else ""
    lines = [f"{_section_label(hit.section)}{author}: {_clip(hit.name, _SOLUS_ENTRY_CAP)}"]
    if hit.snippet and hit.snippet not in hit.name:
        lines.append(_clip(hit.snippet, _SOLUS_ENTRY_CAP))
    kind: SectionKind = "error" if hit.section == SolusSection.ERRORS.value else "document"
    text = redact_text("\n".join(lines))
    return _sized(kind, text, _solus_citation(hit.section, hit.id), hit.score)


def divergence_sections(entry: SolusEntry | None) -> list[ContextSection]:
    """`environment/divergences` as one table — a line per machine counting each cause,
    then up to 3 named items — within 200 tokens. Read only for environment questions."""
    doc = _meta(EnvironmentDivergencesDoc, entry.payload) if entry is not None else None
    if entry is None or doc is None:
        return []
    items = [
        " ".join(
            part
            for part in (
                group.cause,
                item.name,
                item.expected and f"expected {item.expected}",
                item.actual and f"actual {item.actual}",
            )
            if part
        )
        for machine in doc.machines
        for group in machine.causes
        for item in group.items
    ][:_DIVERGENCE_ITEMS]
    lines = ["Environment divergences by machine:", *map(_divergence_line, doc.machines), *items]
    bound = chars_for_tokens(_DIVERGENCE_TOKENS, config=_ESTIMATOR) - 1  # -1: the ellipsis
    text = _clip(redact_text("\n".join(lines)), bound)
    return [_sized("document", text, _solus_citation(SolusSection.ENVIRONMENT.value, entry.id))]


def _divergence_line(machine: MachineDivergences) -> str:
    counts = {group.cause: len(group.items) for group in machine.causes}
    tally = " · ".join(f"{cause} {counts.get(cause, 0)}" for cause in CAUSES)
    return f"{_clip(machine.hostname, _TITLE_CAP)}: {tally}"
