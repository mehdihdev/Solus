# SOLUSDEV-130 (SOL-02) — the reasoning layer's deterministic halves.
#
# The anchor vocabulary (SOLUSDEV-321 P0-T3): why an entity is one of a turn's
# anchors (`AnchorReason`), the claims the turn's own pointing makes
# (`anchor_claims`) and how they rank under `MAX_ANCHORS` (`rank_anchors`). The
# scope planner (`agent/turn_scope.py`, P1-T1) adds the names it resolves and
# decides WHAT TO PULL, with no model call of its own (the ADR-026 pattern:
# classification that gates spend never spends). WHICH MODEL answers stays
# with the gateway's `resolve_routing`, the single routing brain.
#
# `verified_citations` closes the loop on attribution: the model is asked to
# cite `[connector:ref]` tokens, but only citations the assembled Context
# actually contains survive into the Sources line — a hallucinated citation
# is stripped, never rendered as provenance (§7: model output is untrusted).

from __future__ import annotations

import re
import uuid
from collections.abc import Collection, Iterable, Iterator
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    # Annotations only: context.py imports this module's `Anchor` at runtime (the
    # manifest carries the turn's anchors, SOLUSDEV-321 P0-T4).
    from solus_api.agent.context import Context
    from solus_api.orchestration.config import ScopeConfig

#: Standard UUID literal. THE shared instance — runtime.py imports it too
#: (review: a security-relevant parser must not drift between copies).
UUID_RE: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_UUID_RE: Final = UUID_RE  # local alias

#: SEC-H3: an 8000-char message can carry hundreds of UUIDs; anchors are capped so
#: a hostile query bounds DB work, not just the rendered prompt (the SYS-05
#: sub-sampling lever, actually pulled).
MAX_ANCHORS: Final = 8
#: The longest trail a focus may carry. Bounded where the request is parsed, like the anchor
#: cap: the planner trusts nothing a client sends (SEC-H3).
MAX_FOCUS_PATH: Final = 16

#: Why an entity is an anchor. The first three are the person's own pointing, the next two are
#: what the surface they asked from is about, and `ref_match` is an id found in their prose.
#: `name_match` is a name the scope planner resolved in the message (P1-T1); when that name was
#: an entity's exact external ref, the planner's anchor is a `ref_match` too.
AnchorReason = Literal[
    "focused",
    "mentioned",
    "pinned",
    "finding_subject",
    "bench_robot",
    "name_match",
    "ref_match",
]


class Anchor(BaseModel):
    """One entity SOL was pointed at, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    reason: AnchorReason


#: Why an anchor never reached the scope: the caller's view of the project cannot see it, or the
#: cap (`MAX_ANCHORS`) took it from the weak end.
DropCause = Literal["not_visible", "over_cap"]


class DroppedAnchor(Anchor):
    """An anchor that never reached the scope: the reason it was one, and the cause it was lost."""

    cause: DropCause


class FocusIn(BaseModel):
    """The workspace focus a page send carries: the entity the person is looking at and the
    trail they came through (oldest first, the focus itself excluded). It rides every page
    send, so ids in it that went stale are dropped rather than refused — see
    `turn_scope.plan_scope`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: uuid.UUID
    path: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_FOCUS_PATH)

    def ids(self) -> tuple[uuid.UUID, ...]:
        """Every id the focus carries: the focus, then its trail (oldest first)."""
        return (self.entity_id, *self.path)


def anchor_claims(
    query: str,
    mentions: Iterable[uuid.UUID],
    pins: Iterable[uuid.UUID],
    focus: FocusIn | None,
    finding_subjects: Iterable[uuid.UUID],
    bench_robot: uuid.UUID | None,
) -> Iterator[Anchor]:
    """Every claim the turn's own pointing makes on an entity, strongest first: the entity the
    person is looking at, what they pointed at, what the surface they asked from is about — and
    last the ids found in the prose, which may just be quoted log output. The focus trail is not
    one of them: it ranks after the names the planner resolves (`trail_claims`, P1-T1). They are
    EQUAL anchors: each seeds the neighbourhood the same way and differs only in its reason."""
    if focus is not None:
        yield Anchor(id=focus.entity_id, reason="focused")
    yield from (Anchor(id=i, reason="mentioned") for i in mentions)
    yield from (Anchor(id=i, reason="pinned") for i in pins)
    yield from (Anchor(id=i, reason="finding_subject") for i in finding_subjects)
    if bench_robot is not None:
        yield Anchor(id=bench_robot, reason="bench_robot")
    yield from (Anchor(id=uuid.UUID(m), reason="ref_match") for m in _UUID_RE.findall(query))


def trail_claims(focus: FocusIn | None) -> Iterator[Anchor]:
    """The focus trail, nearest the focused entity first (it arrives oldest first). The page
    sends it with every turn on its own, so it ranks after everything the turn names (P1-T1):
    a long trail never crowds out a mention or a resolved name."""
    if focus is not None:
        yield from (Anchor(id=i, reason="focused") for i in reversed(focus.path))


def rank_anchors(
    claims: Iterable[Anchor], not_visible: Collection[uuid.UUID]
) -> tuple[tuple[Anchor, ...], tuple[DroppedAnchor, ...]]:
    """(kept, dropped). An entity claimed twice is one anchor under its first claim; the ones
    the caller could not see never take a slot; `MAX_ANCHORS` takes the rest from the weakest
    end — a client is not trusted to respect the request schema's limits, and this cap is what
    bounds the neighbourhood query's DB work (SEC-H3). The dropped keep blame order, each with
    the cause that removed it."""
    first: dict[uuid.UUID, Anchor] = {}
    for claim in claims:
        first.setdefault(claim.id, claim)
    hidden = frozenset(not_visible)
    kept = [a for a in first.values() if a.id not in hidden][:MAX_ANCHORS]
    kept_ids = {a.id for a in kept}
    dropped = tuple(
        DroppedAnchor(
            id=a.id, reason=a.reason, cause="not_visible" if a.id in hidden else "over_cap"
        )
        for a in first.values()
        if a.id not in kept_ids
    )
    return tuple(kept), dropped


def question_domains(query: str, *, scope: ScopeConfig) -> frozenset[str]:
    """The `scope.domain_keywords` groups (models.yaml) whose words or phrases the message
    uses — whole words, any case. `environment` gates the divergences table (P0-T6); the
    planner reads the `runtime` group (P1-T1)."""
    text = query.lower()  # the keywords are lowercased at load
    return frozenset(
        group
        for group, words in scope.domain_keywords.items()
        if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) for word in words)
    )


_CITATION_RE: Final = re.compile(r"\[[A-Za-z0-9._/#:-]+:[A-Za-z0-9._/#:-]+\]")


_SOURCES_LINE_RE: Final = re.compile(r"^\s*sources?\s*:.*$", re.IGNORECASE | re.MULTILINE)


def sanitize_reply(text: str, context: Context) -> tuple[str, tuple[str, ...]]:
    """The final reply, split into prose and PROVENANCE.

    Model prose cannot be the provenance surface: `_CITE_NOTE` trains the model
    to emit bracket tokens, so it could also write its own convincing
    "Sources:" line. Any model-authored Sources line is stripped from the
    prose, and the verified citations travel as structured data on the message
    event — a region model text cannot reach.

    KNOWN LIMIT (documented, not solved here): verification is token-set
    membership. A poisoned chunk can still tell the model to attribute a
    fabricated CLAIM to a genuine citation the context served — the citation
    list proves "these sources were in context", not "each sentence is faithful
    to its source". Per-claim binding is future work; renderers must not
    present the citation list as more than that."""
    prose = _SOURCES_LINE_RE.sub("", text).strip()
    return prose, verified_citations(text, context)


def verified_citations(text: str, context: Context) -> tuple[str, ...]:
    """The citations from `text` that the context actually contains, in first-
    appearance order, deduplicated. Model output is untrusted — a citation the
    context never served is stripped, not rendered as provenance."""
    genuine = {section.citation for section in context.sections if section.citation}
    seen: list[str] = []
    for token in _CITATION_RE.findall(text):
        if token in genuine and token not in seen:
            seen.append(token)
    return tuple(seen)
