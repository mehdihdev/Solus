"""Compatibility checker interface + Warning contract (SOLUS-CHK-01, SOLUSDEV-115).

The cross-domain catch logic that is Solus's reason to exist: rules that run over the linked
graph to catch integration bugs spanning domains. Checkers are PURE, STATELESS FUNCTIONS —
graph in, warnings out, no hidden state (ADR-003). Each checker reads a serializable
``GraphContext`` (the LNK graph-access seam, ``agent/interfaces.py``) plus the fingerprint's
canonical parts (FP, W0-06), walks linked cross-domain edges, evaluates part attributes, and
emits ``Warning`` values.

STATUS — proposed spine contract. CLAUDE.md §9 lists the checker interface as a shared
contract and ADR-028 makes ``packages/contracts/`` HUMAN-OWNED. This module therefore STAGES
the shape inside the ``solus-api`` package (mirroring how the connector contract was staged),
and promotion to ``packages/contracts/`` — locked together with the CHK-03/04 warning UI —
is a human follow-up. See ``docs/contracts/checker-interface.md``.
"""

import abc
import enum
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.interfaces import GraphContext
from solus_api.fingerprint.contract import FingerprintOutput


class Severity(enum.StrEnum):
    """Ordered severity of a checker finding, by real-world impact (not just style):
    ``CRITICAL`` = the robot will not work or may be damaged (wrong voltage, under-rated
    supply); ``WARNING`` = degraded or unreliable behaviour (aliasing, a marginal op-amp);
    ``INFO`` = advisory. Use :func:`severity_rank` to sort/compare."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.CRITICAL: 2,
}


def severity_rank(severity: Severity) -> int:
    """Integer rank for ordering (higher = more severe)."""
    return _SEVERITY_RANK[severity]


class Warning(BaseModel):  # noqa: A001 — domain name; the CHK-03/04 UI consumes `Warning`
    """One cross-domain compatibility finding — the shape the warning UI (CHK-03/04) renders
    and the SOL Agent explains, so it is deliberately structured, never free prose.

    Frozen + ``extra="forbid"`` (house style): a warning is an immutable value object, and an
    unexpected field is a bug, not silently accepted.

    UNTRUSTED CONTENT (CLAUDE.md §7): ``message`` and every string inside ``evidence`` inline
    connector-ingested entity names/attrs (``EntityRead.name``/``attrs``), which are
    attacker-influenceable — a malicious CAD part name can carry "ignore previous instructions…".
    This pure layer deliberately does NOT escape or delimit them (that would corrupt the data for
    other consumers). Consumers MUST: the SOL Agent wraps them as delimited DATA in prompt assembly
    (mirroring ``agent/interfaces.py``), and the CHK-03/04 UI HTML-escapes them at render — never
    treat ``message`` as trusted Solus prose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checker_id: str  # which rule produced it, e.g. "op_amp_mismatch"
    severity: Severity
    domains: tuple[str, ...]  # spanned domains (lowercase Domain values), sorted + unique
    message: str  # human summary; carries UNTRUSTED entity names — see class docstring
    evidence: dict[str, Any] = Field(default_factory=dict)  # structured WHAT/WHY; UNTRUSTED strings
    entity_ids: tuple[UUID, ...] = ()  # graph entities implicated (for UI highlight / focus)
    suggested_area: str | None = None  # where to look / what to change


class Checker(abc.ABC):
    """A compatibility rule. Subclasses are STATELESS — construct once and reuse; every input
    arrives through :meth:`check`. Declaring a subclass and registering it (see ``core.py``)
    is all it takes to add a rule, so the library scales by addition, not modification."""

    #: stable identifier, emitted on every Warning this checker produces
    checker_id: ClassVar[str]
    #: the domains this checker reasons across (each warning's `domains` is derived from the
    #: entities actually implicated; this documents the checker's intended span)
    domains: ClassVar[tuple[str, ...]]

    @abc.abstractmethod
    def check(self, graph: GraphContext, parts: FingerprintOutput) -> list["Warning"]:
        """Walk ``graph`` (optionally using ``parts`` for canonical identity) and return the
        warnings found. MUST be pure: no I/O, no mutation of inputs, deterministic for a given
        input. MUST degrade gracefully — when the attributes a rule needs are absent, SKIP
        rather than guess, so an incomplete graph never produces false positives."""
        raise NotImplementedError


def run_checkers(
    graph: GraphContext,
    parts: FingerprintOutput,
    checkers: tuple[Checker, ...],
) -> list["Warning"]:
    """Run every checker over the same graph and return all warnings, most-severe first.

    Pure and side-effect-free (ADR-003): event emission / persistence belongs to the job or
    route layer that *calls* this, never inside the checkers."""
    found: list[Warning] = []
    for checker in checkers:
        found.extend(checker.check(graph, parts))
    return sorted(found, key=lambda w: severity_rank(w.severity), reverse=True)
