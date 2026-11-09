"""SOLUSDEV-321 P3-T1 — the base every interaction-matrix rule implements (P3-T2's nine cells).

A `MatrixRule` names itself (`rule_id`), the cell of the interaction matrix it speaks for
(`matrix_cell`: src → dst, the cells an edge's `attrs.matrix_cell` holds) and what it reads
(`needs`, the shape the live-signal rules declare). It implements one pure method, `evaluate`:
graph and facts in, one `RuleResult` per judgement out — `pass`, `fail`, `inconclusive` (the
facts are there and do not settle it) or `unknown_input` (a fact it needs is not stated; `missing`
names it and where a person states it).

`results` is what a run reads: one `unknown_input` naming the first of `needs.facts` the fact
store does not hold, else what `evaluate` says. `check`, the `Checker` contract, turns ONLY a
`fail` into a `Warning`, so a rule that could not judge raises nothing in `run_checkers`, impact
or the checker eval: an unmet fact is never a false positive. Both are final. A result about an
edge names it by `edge_ref`; the `GraphContext` carries no edge ids, so the runner (P3-T3) finds
the row by the edge's ends and relation type.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Final, NamedTuple, final
from uuid import UUID

from solus_contracts.relations import MatrixCell

from solus_api.checkers.checker_results import RuleStatus
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Checker, Severity, Warning
from solus_api.checkers.traversal import GraphView, domains_of
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

if TYPE_CHECKING:
    from solus_api.agent.interfaces import EdgeRead, GraphContext
    from solus_api.fingerprint.contract import FingerprintOutput

#: A matrix side's graph domain where the two differ (`solus_contracts.relations.matrix_cell`).
_DOMAIN: Final = {"software": "code"}


class EdgeRef(NamedTuple):
    """The edge a result is about, as a `GraphContext` names it (an `EdgeRead` has no id)."""

    src_id: UUID
    dst_id: UUID
    relation_type: str

    @classmethod
    def of(cls, edge: EdgeRead) -> EdgeRef:
        return cls(edge.src_id, edge.dst_id, edge.relation_type)


@dataclass(frozen=True, kw_only=True)
class RuleResult:
    """One judgement: `subjects` are the entities it is about, in blame order; `evidence` the
    numbers it compared, under stable keys; `missing` the fact an `unknown_input` lacks."""

    status: RuleStatus
    message: str
    severity: Severity = Severity.INFO
    subjects: tuple[UUID, ...] = ()
    edge_ref: EdgeRef | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    missing: FactNeed | None = None

    def __post_init__(self) -> None:
        if self.status == "unknown_input" and self.missing is None:
            raise ValueError("an unknown_input result names the fact it is missing")


class MatrixRule(Checker):
    """One rule of one matrix cell: subclasses set `rule_id`, `matrix_cell` and (when they read
    facts) `needs`, and implement `evaluate`."""

    rule_id: ClassVar[str]
    matrix_cell: ClassVar[MatrixCell]
    needs: ClassVar[Needs] = Needs()
    #: False when another producer already raises this rule's problem as a finding: a run keeps
    #: the rule's `fail` on the edge and in its report, and raises nothing for it (R60).
    raises_findings: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """A rule's `checker_id` is its `rule_id`; its `domains` are its cell's two worlds."""
        super().__init_subclass__(**kwargs)
        if "rule_id" in vars(cls):
            sides = cls.matrix_cell.value.split("->")
            cls.checker_id = cls.rule_id
            cls.domains = tuple(sorted({_DOMAIN.get(side, side) for side in sides}))

    @abc.abstractmethod
    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        """The rule: pure (ADR-003), and `unknown_input` rather than a guess."""

    @final
    def results(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        """One `unknown_input` for the first needed fact the store lacks, worded by the cells'
        one helper; else `evaluate`."""
        from solus_api.checkers.cells import unknown_input  # the cells import this module

        missing = next((need for need in self.needs.facts if not facts.has(need.name)), None)
        return self.evaluate(graph, facts) if missing is None else [unknown_input(self, missing)]

    @final
    def check(
        self, graph: GraphContext, parts: FingerprintOutput, facts: FactStore | None = None
    ) -> list[Warning]:
        """Only a `fail` is a `Warning`; every other result is the runner's to keep (P3-T3)."""
        view = GraphView(graph)
        found = self.results(graph, facts if facts is not None else FactStore())
        return [self.warning(view, result) for result in found if result.status == "fail"]

    def warning(self, view: GraphView, result: RuleResult) -> Warning:
        """A `fail` as the checker contract words it: the domains of the subjects that resolve,
        else the cell's. A run maps its fails through this, never evaluating a rule twice."""
        implicated = [e for i in result.subjects if (e := view.entity(i)) is not None]
        return Warning(
            checker_id=self.rule_id,
            severity=result.severity,
            domains=domains_of(*implicated) if implicated else self.domains,
            message=result.message,
            evidence=dict(result.evidence),
            entity_ids=result.subjects,
        )
