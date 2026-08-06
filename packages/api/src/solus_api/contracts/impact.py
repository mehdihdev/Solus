"""SOLUSDEV-219 (CTR-04) — the impact result contract.

Impact is the flagship surface and it was fully serialised: engine (LANE A,
backend) -> consequence model (LANE A) -> widget (LANE B, frontend), with the
widget also blocked on the SOL lane. Publishing the RESULT shape lets the engine
and the widget be built at the same time, with the fixtures under
`packages/shared-types/fixtures/impact/` standing in for the engine until it
lands.

The TypeScript twin is `packages/shared-types/src/impact.ts`; both are validated
against those same fixtures, which is what stops them drifting. See
`docs/contracts/impact.md`.

Nothing here computes impact. This is the shape the engine returns.
"""

from __future__ import annotations

import re
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from solus_api.checkers.interface import Severity, severity_rank
from solus_api.contracts.action_gate import DiffRow
from solus_api.models import Domain

#: A locator is a REFERENCE, never a URL. Covers every documented form —
#: `firmware/motor_ctl.cpp:88`, `sch:U3`, `cad:drive_harness` — while refusing
#: URL-ish schemes outright and forbidding the characters a payload needs
#: (`?`, `=`, `(`, `;`, `,`). A widget still renders it as text and resolves it
#: itself; it must never go straight into an `href`.
LOCATOR_RE: Final = (
    r"^(?!(?:javascript|data|vbscript|file|blob|https?):)"
    r"(?:[a-z][a-z0-9_]*:)?[\w./-]+(?::\d+)?$"
)


def worst_severity(severities: list[Severity]) -> Severity:
    """The worst of a set. Empty is INFO — no consequences is not an error."""
    return max(severities, key=severity_rank, default=Severity.INFO)


class ImpactEntity(BaseModel):
    """A graph entity as the API addresses it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    entity_id: str


class ImpactPathStep(BaseModel):
    """One hop of the traversal from the focus toward an affected entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: ImpactEntity
    domain: Domain
    label: str = Field(max_length=512)
    #: `graph_edge.relation_type` traversed from this step toward the next.
    relation: str = Field(min_length=1, max_length=128)


class ConsequenceEvidence(BaseModel):
    """Where to look. `locator` is the thing a UI turns into a link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(max_length=200)
    detail: str = Field(max_length=1000)
    #: e.g. `firmware/motor_ctl.cpp:88`, `sch:U3`, `cad:drive_harness`.
    #: None when there is genuinely no place to point.
    #:
    #: CONSTRAINED, because an impact result is data a model may have influenced
    #: and this field is documented as "the thing a UI turns into a link" — an
    #: unconstrained string means `javascript:` and `https://attacker/?leak=` are
    #: valid values, and CLAUDE.md §7 puts sanitising model output before render
    #: on us, not on six independent widget authors.
    locator: str | None = Field(default=None, max_length=512)

    @field_validator("locator")
    @classmethod
    def _check_locator(cls, value: str | None) -> str | None:
        # Checked here rather than via StringConstraints because pydantic-core's
        # Rust regex engine has no lookahead, and the scheme denylist needs one.
        # Same pattern string as the TypeScript mirror.
        if value is not None and not re.match(LOCATOR_RE, value):
            raise ValueError(
                "locator: must be a reference like 'sch:U3' or 'path/file.cpp:88', never a URL"
            )
        return value


class SolAction(BaseModel):
    """A SOL action an impact row can launch.

    `args` is a PROPOSAL, not an authorisation. A destructive tool still routes
    through the confirmation gate, which stores and re-reads its own arguments
    (`docs/contracts/action-gate.md`). Nothing on this row bypasses that — an
    impact result is data the model may have influenced, and model output is
    untrusted input to the next step (CLAUDE.md §7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(max_length=128)
    label: str = Field(max_length=200)
    args: dict[str, Any] = Field(default_factory=dict)


class Consequence(BaseModel):
    """One specific thing that goes wrong at an affected entity.

    An entity can have several — the driver may be both under-rated and
    thermally marginal. `rationale` is the why-this-matters prose, and it is the
    reason Impact is worth reading rather than a list of rule names. It is
    rendered under the user's SOL mode (ADR-016).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    severity: Severity
    #: One line, for the collapsed row.
    headline: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=4000)
    evidence: list[ConsequenceEvidence] = Field(default_factory=list, max_length=20)
    #: None when there is no proposable fix — nullable, never absent, so a widget
    #: never has to tell "no action" from "field forgotten".
    action: SolAction | None = None


class ImpactNode(BaseModel):
    """An entity the change reaches, with everything that goes wrong there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: ImpactEntity
    label: str = Field(max_length=512)
    domain: Domain
    #: The worst of `consequences`, precomputed so a widget can sort without
    #: walking every consequence.
    severity: Severity
    #: Hops from the focus. Always equals `len(path)`.
    distance: int = Field(ge=0)
    #: The traversal back to the focus, STARTING at the focus.
    path: list[ImpactPathStep]
    consequences: list[Consequence] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        # Two ways to say the same thing is two ways to be wrong. A node whose
        # distance and path disagree would render a breadcrumb contradicting its
        # own hop count.
        if self.distance != len(self.path):
            raise ValueError(f"distance {self.distance} != path length {len(self.path)}")
        worst = worst_severity([c.severity for c in self.consequences])
        if self.severity is not worst:
            raise ValueError(f"severity {self.severity} is not the worst consequence ({worst})")
        return self


class ImpactFocus(BaseModel):
    """What was focused when the change happened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: ImpactEntity
    domain: Domain
    label: str = Field(max_length=512)


class ImpactResult(BaseModel):
    """One impact analysis.

    `nodes == []` means "nothing downstream broke" — a real answer, not an
    empty state to apologise for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    focus: ImpactFocus
    #: The change that caused this. Reuses the action gate's row shape so what a
    #: user approves and what an impact was caused by render identically.
    change: list[DiffRow] = Field(min_length=1)
    computed_at: str
    #: Whether the traversal hit its bound (IMP-01 traverses to a bounded depth).
    #: A widget that does not surface this presents a partial answer as complete.
    truncated: bool = False
    nodes: list[ImpactNode] = Field(default_factory=list)


__all__ = [
    "Consequence",
    "ConsequenceEvidence",
    "ImpactEntity",
    "ImpactFocus",
    "ImpactNode",
    "ImpactPathStep",
    "ImpactResult",
    "Severity",
    "SolAction",
    "worst_severity",
]
