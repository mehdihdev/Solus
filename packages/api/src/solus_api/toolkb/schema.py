"""SOLUS-TU-04 (SOLUSDEV-207) — tool-knowledge KB storage schema.

One table, `tool_knowledge`, holding both staging (`candidate`) and shared
(`published`) entries in the SAME closed shape — there is no second staging
schema whose validation could drift. The columns mirror CTR-05
(`solus_api.contracts.tool_knowledge`) exactly; every storage-side addition is
an enum, a number, or a timestamp, so storage introduces no new prose channel.

Deliberate absences, which ARE the tenancy boundary (docs/contracts/
tool-knowledge.md): no team/project/user/install column, no JSONB, no free-text
beyond the contract's validated fields. The `embedding` column lives here and
not in the contract shape because a vector of customer text is still customer
text — this column may only ever hold vectors of guard-admitted vendor prose.

Rows are constructed ONLY by `toolkb.guard` (TU-06); a tripwire test enforces
that outside tests.
"""

import enum
import re
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from solus_api.contracts.tool_knowledge import (
    ControlEffect,
    Invocation,
    Provenance,
    ScreenLocator,
    ToolFamily,
    ToolKnowledge,
    UiSurface,
)
from solus_api.models import (
    EMBEDDING_DIM,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UuidPkMixin,
    _enum_column,
    _hnsw,
    _partial_unique,
)


class KnowledgeStatus(enum.StrEnum):
    """Staging vs. shared. `published` rows are read by EVERY tenant."""

    CANDIDATE = "candidate"
    PUBLISHED = "published"


class AcquisitionMethod(enum.StrEnum):
    """How the entry was learned (the TU ladder), finer-grained than Provenance."""

    API_GEOMETRY = "api_geometry"
    DOCS = "docs"
    VISUAL = "visual"
    OPERATOR = "operator"


class Verdict(enum.StrEnum):
    """A human's judgement on a guidance entry (TU-08 feedback / TU-05 sharing).

    Lives here, not in `feedback`, so the observation model can reference it
    without a circular import; `feedback` re-exports it for existing callers.
    """

    CONFIRM = "confirm"
    REJECT = "reject"


#: Starting confidence per acquisition method — stored, then adjusted only by
#: the TU-08 confirm/reject recompute. Provisional values (product call).
INITIAL_CONFIDENCE: Final[dict[AcquisitionMethod, float]] = {
    AcquisitionMethod.API_GEOMETRY: 0.9,  # machine-read from the vendor's own API
    AcquisitionMethod.DOCS: 0.8,  # vendor documentation
    AcquisitionMethod.OPERATOR: 0.7,  # human-authored, pre-review
    AcquisitionMethod.VISUAL: 0.5,  # ML-detected, weakest
}


# ------------------------------------------------------------- version keys
#
# `version_range` stays verbatim (the contract validates it); at write time we
# derive zero-padded sortable keys so "which entries hold for KiCad 8.0.6?" is
# a pure btree range scan: min_key <= key(v) < max_key (max NULL = open-ended).
# ponytail: 4-digit components — breaks ordering at version 10000; widen the pad then.
_COMPONENT_PAD: Final = 4
_MAX_COMPONENT: Final = 9999
_TOKEN_RE: Final = re.compile(r"^(?P<op>[<>=~^]{0,2})(?P<ver>\d+(?:\.\d+){0,2})$")
_KNOWN_OPS: Final = frozenset({"", "=", ">", ">=", "<", "<=", "~", "^"})


def _parse(version: str) -> tuple[list[int], int]:
    """Split ``"2.1"`` into padded components ``[2, 1, 0]`` and its precision (2)."""
    try:
        parts = [int(piece) for piece in version.split(".")]
    except ValueError as exc:
        raise ValueError(f"not a version: {version!r}") from exc
    if not 1 <= len(parts) <= 3 or any(p > _MAX_COMPONENT or p < 0 for p in parts):
        raise ValueError(f"version out of range: {version!r}")
    precision = len(parts)
    return parts + [0] * (3 - precision), precision


def _key(parts: Sequence[int]) -> str:
    return ".".join(f"{part:0{_COMPONENT_PAD}d}" for part in parts)


def _bump(parts: Sequence[int], index: int) -> list[int]:
    bumped = list(parts)
    bumped[index] += 1
    if bumped[index] > _MAX_COMPONENT:
        raise ValueError(f"version component overflow bumping {parts!r}")
    for i in range(index + 1, 3):
        bumped[i] = 0
    return bumped


def version_key(version: str) -> str:
    """``"8.0.6"`` → ``"0008.0000.0006"`` — the query-side key for one version."""
    parts, _ = _parse(version.strip())
    return _key(parts)


def _token_window(token: str) -> tuple[str | None, str | None]:
    """One token → its (low, high) contribution, either possibly None."""
    match = _TOKEN_RE.match(token)
    if match is None or match["op"] not in _KNOWN_OPS:
        raise ValueError(f"unsupported version token: {token!r}")
    parts, precision = _parse(match["ver"])
    op = match["op"]
    if op == ">=":
        return _key(parts), None
    if op == ">":
        return _key(_bump(parts, 2)), None
    if op == "<":
        return None, _key(parts)
    if op == "<=":
        return None, _key(_bump(parts, precision - 1))
    if op == "~":
        return _key(parts), _key(_bump(parts, min(precision - 1, 1)))
    if op == "^":
        # npm caret: bump the leftmost non-zero STATED component — ^0.2.3
        # means <0.3.0 and ^0.0.3 means <0.0.4, not <1.0.0 (review finding).
        # All stated components zero (^0, ^0.0) → bump the last stated one.
        index = next((i for i, part in enumerate(parts[:precision]) if part), precision - 1)
        return _key(parts), _key(_bump(parts, index))
    # "" or "=" — equality window at stated precision
    return _key(parts), _key(_bump(parts, precision - 1))


def version_keys(version_range: str) -> tuple[str, str | None]:
    """Derive the ``[min_key, max_key)`` window for a CTR-05 ``version_range``.

    Bare/``=`` tokens are an equality window at their stated precision
    (``"2.0"`` covers 2.0.*), ``~``/``^`` follow their npm meanings, ``>``
    excludes at patch precision, ``<=`` includes at stated precision. Multiple
    tokens intersect.
    """
    tokens = version_range.strip().split()
    if not tokens:
        raise ValueError("empty version_range")
    windows = [_token_window(token) for token in tokens]
    lows = [low for low, _ in windows if low is not None]
    highs = [high for _, high in windows if high is not None]
    low = max(lows) if lows else _key([0, 0, 0])
    high = min(highs) if highs else None
    if high is not None and high <= low:
        raise ValueError(f"empty version window: {version_range!r}")
    return low, high


# ---------------------------------------------------------------------- ORM
class ToolKnowledgeEntry(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One stored fact about one tool's UI — the CTR-05 shape plus bookkeeping."""

    __tablename__ = "tool_knowledge"

    # -- CTR-05 mirror (writable only via a validated ToolKnowledge; TU-06) --
    tool: Mapped[ToolFamily] = mapped_column(_enum_column(ToolFamily))
    version_range: Mapped[str] = mapped_column(String(64))
    surface: Mapped[UiSurface] = mapped_column(_enum_column(UiSurface))
    control_id: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(400))
    effect: Mapped[ControlEffect] = mapped_column(_enum_column(ControlEffect))
    description: Mapped[str] = mapped_column(String(400))
    # Typed array, not JSONB — the contract forbids untyped containers.
    menu_path: Mapped[list[str] | None] = mapped_column(ARRAY(String(400)), default=None)
    shortcut: Mapped[str | None] = mapped_column(String(64), default=None)
    locator_x: Mapped[float | None] = mapped_column(Float, default=None)
    locator_y: Mapped[float | None] = mapped_column(Float, default=None)
    locator_w: Mapped[float | None] = mapped_column(Float, default=None)
    locator_h: Mapped[float | None] = mapped_column(Float, default=None)
    provenance: Mapped[Provenance] = mapped_column(_enum_column(Provenance))

    # -- storage-side: enum / number / timestamp only, never prose ----------
    status: Mapped[KnowledgeStatus] = mapped_column(_enum_column(KnowledgeStatus))
    acquired_via: Mapped[AcquisitionMethod] = mapped_column(_enum_column(AcquisitionMethod))
    confidence: Mapped[float] = mapped_column(Float)
    confirm_count: Mapped[int] = mapped_column(Integer, default=0)
    reject_count: Mapped[int] = mapped_column(Integer, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    version_min_key: Mapped[str] = mapped_column(String(32))
    version_max_key: Mapped[str | None] = mapped_column(String(32), default=None)
    # NOTE: pgvector reads back numpy.ndarray, not list (models.py:37).
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), default=None, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_tool_knowledge_confidence_range"
        ),
        CheckConstraint(
            "confirm_count >= 0 AND reject_count >= 0",
            name="ck_tool_knowledge_counts_nonnegative",
        ),
        CheckConstraint(
            "menu_path IS NULL OR cardinality(menu_path) <= 8",
            name="ck_tool_knowledge_menu_path_len",
        ),
        # num_nonnulls, not IS NULL algebra: a half-set locator must FAIL, and a
        # CHECK evaluating to NULL passes — the SQL-null trap.
        CheckConstraint(
            "num_nonnulls(locator_x, locator_y, locator_w, locator_h) IN (0, 4)",
            name="ck_tool_knowledge_locator_all_or_none",
        ),
        CheckConstraint(
            "(locator_x IS NULL OR (locator_x >= 0 AND locator_x <= 1))"
            " AND (locator_y IS NULL OR (locator_y >= 0 AND locator_y <= 1))"
            " AND (locator_w IS NULL OR (locator_w >= 0 AND locator_w <= 1))"
            " AND (locator_h IS NULL OR (locator_h >= 0 AND locator_h <= 1))",
            name="ck_tool_knowledge_locator_bounds",
        ),
        _partial_unique(
            "uq_tool_knowledge_identity", "tool", "control_id", "surface", "version_range"
        ),
        Index("ix_tool_knowledge_lookup", "tool", "status", "version_min_key"),
        _hnsw("ix_tool_knowledge_embedding", "embedding"),
    )


def locator_of(row: ToolKnowledgeEntry) -> ScreenLocator | None:
    """The row's normalised 0..1 box, or None when it has no geometry.

    All-or-nothing by the table's own CHECK (`num_nonnulls(...) IN (0, 4)`), so a
    half-set locator cannot reach here — but the four-way test stays explicit
    rather than trusting the constraint, because this feeds the overlay's
    "point at it" decision (SOLUS-TU-10) and a partial box must never render.
    """
    if (
        row.locator_x is None
        or row.locator_y is None
        or row.locator_w is None
        or row.locator_h is None
    ):
        return None
    return ScreenLocator(x=row.locator_x, y=row.locator_y, w=row.locator_w, h=row.locator_h)


def to_contract(row: ToolKnowledgeEntry) -> ToolKnowledge:
    """Materialize a row as the CTR-05 shape, re-running its validators.

    A row that somehow held customer-shaped prose fails HERE, not in a tenant's
    Guide panel — the read path re-checks the boundary it serves.
    """
    invocation = None
    if row.menu_path is not None or row.shortcut is not None:
        invocation = Invocation(
            menu_path=None if row.menu_path is None else list(row.menu_path),
            shortcut=row.shortcut,
        )
    locator = locator_of(row)
    return ToolKnowledge(
        tool=row.tool,
        version_range=row.version_range,
        surface=row.surface,
        control_id=row.control_id,
        label=row.label,
        effect=row.effect,
        description=row.description,
        invocation=invocation,
        locator=locator,
        provenance=row.provenance,
    )


class ToolKnowledgeObservation(UuidPkMixin, TimestampMixin, Base):
    """SOLUS-TU-05 — one voter's verdict on one entry. SERVER-ONLY.

    Records WHO corroborated a fact so distinct-voter counting can gate sharing,
    without ever putting a tenant-linkable reference on the cross-tenant entry.
    `voter_hash` is a salted, one-way hash (see `sharing.voter_key`) — NOT a
    user/team/project FK — so it dedups and counts distinct voters but cannot be
    reversed to a person, and it is never exposed on any read route. Mirrors the
    `data_events` precedent (§7.3, human-approved 2026-08-08). The UNIQUE on
    (knowledge_id, voter_hash) is the anti-ballot-stuffing primitive: one voter,
    one vote per entry.
    """

    __tablename__ = "tool_knowledge_observation"

    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tool_knowledge.id", ondelete="CASCADE"), index=True
    )
    voter_hash: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[Verdict] = mapped_column(_enum_column(Verdict))

    __table_args__ = (
        UniqueConstraint("knowledge_id", "voter_hash", name="uq_tk_observation_voter"),
    )
