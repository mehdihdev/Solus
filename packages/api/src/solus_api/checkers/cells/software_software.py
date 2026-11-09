"""SOLUSDEV-321 P3-T2 — software → software: a package, a module contract or a protocol one
piece of software assumes against what another states.

- `package_version_conflict` covers two cases. The first is a package the dependency files pin
  differently (`checkers/environment.py:pin_conflicts`, the reading the code-environment proposal
  shares). The second is a machine whose recorded environment runs a version or a build the
  project's spec does not allow, from the `environment/divergences` CONFIG, read and never
  recomputed.
- `module_contract_mismatch` (P6) compares, within one source, each policy's action space with
  the inputs of the controllers the software reader found (`FactStore.module_interfaces`) when
  they all take one width; controllers of more than one width leave the pairing unknown (I1).
- `loop_rate_latency` and `config_protocol_mismatch` wait for facts nothing states yet: each
  answers `unknown_input` with where a person states it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.cells import UnstatedFactRule, unknown_input
from solus_api.checkers.environment import PinConflict, pin_conflicts
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import MatrixRule, RuleResult
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

if TYPE_CHECKING:
    from uuid import UUID

    from solus_api.agent.interfaces import GraphContext
    from solus_api.checkers.fact_store import FactStore
    from solus_api.services.solus_payloads import MachineDivergences
    from solus_api.software.policy_reader import ModuleInterface

    type _Held = list[tuple[UUID, ModuleInterface]]

CELL: Final = MatrixCell.SOFTWARE_SOFTWARE
DIVERGENCES: Final = FactNeed(
    name="divergences",
    set_in=(
        "the `.solus` environment/divergences CONFIG, recomputed when a machine's "
        "environment/software CONFIG is linked"
    ),
)
#: The divergence causes that are a version conflict, and how bad each is: a build the spec does
#: not allow will not run, a drifted version may not. A missing or an extra package is not one.
DRIFT: Final = {"version_drift": Severity.WARNING, "platform_build": Severity.CRITICAL}
#: Package names a drift message lists before it counts the rest.
NAMED: Final = 5


class PackageVersionConflict(MatrixRule):
    """A package the code needs at two versions, or at one its machine does not run. Both inputs
    are optional, so the rule declares no need for the base to guard. Without the divergences it
    answers `unknown_input` for them and still judges the dependency files."""

    rule_id = "package_version_conflict"
    matrix_cell = CELL

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        pinned = [_pinned(conflict) for conflict in pin_conflicts(graph)]
        if facts.divergences is None:
            return [*pinned, unknown_input(self, DIVERGENCES)]
        return [*pinned, *(_drifted(machine) for machine in facts.divergences.machines)]


def _pinned(conflict: PinConflict) -> RuleResult:
    return RuleResult(
        status="fail",
        severity=conflict.severity,
        message=conflict.message,
        subjects=tuple(req.entity_id for req in conflict.requirements),
        evidence={"package": conflict.package, "pins": conflict.pins},
    )


def _drifted(machine: MachineDivergences) -> RuleResult:
    """One judgement per machine: the drift and build groups its divergences record, if any."""
    groups = {group.cause: group.items for group in machine.causes if group.cause in DRIFT}
    groups = {cause: items for cause, items in groups.items() if items}
    subjects = (machine.machine_id,)
    if not groups:
        message = f"'{machine.hostname}' runs the versions the project's spec allows"
        return RuleResult(status="pass", message=message, subjects=subjects)
    names = sorted({item.name for items in groups.values() for item in items})
    more = f" and {len(names) - NAMED} more" if len(names) > NAMED else ""
    return RuleResult(
        status="fail",
        severity=Severity.CRITICAL if "platform_build" in groups else Severity.WARNING,
        message=(
            f"'{machine.hostname}' runs {', '.join(names[:NAMED])}{more} at a version or build "
            "the project's spec does not allow"
        ),
        subjects=subjects,
        evidence={
            "machine": machine.hostname,
            "causes": {
                cause: [item.model_dump(mode="json") for item in items]
                for cause, items in groups.items()
            },
        },
    )


MODULE_INTERFACES: Final = FactNeed(
    name="module_interfaces",
    set_in=(
        "the code host or linked folder's policy and controller modules, read by the software "
        "reader (P6)"
    ),
)
CONTROLLER_INPUTS: Final = FactNeed(
    name="controller inputs",
    set_in=(
        "a controller config in the policy's own repository or folder: a mapping under a key "
        "that names the controller, with its `joints` list, `input_dim` or `command_dim`"
    ),
)
POLICY_ACTIONS: Final = FactNeed(
    name="policy action space",
    set_in=(
        "the policy's config (`action_dim` or `output_features`) or its environment's "
        "`action_space`, in the controller's own repository or folder"
    ),
)
PAIRING: Final = FactNeed(
    name="policy and controller pairing",
    set_in=(
        "the policy's own repository or folder: it states controllers of more than one width "
        "and nothing there says which one the policy feeds"
    ),
)


class ModuleContractMismatch(MatrixRule):
    """A policy's action space against the inputs of the controller it feeds, within one source.
    Which controller that is, is stated nowhere, so only a source whose controllers all take one
    width is judged (I1): unequal fails (WARNING) and equal passes. Controllers of more than one
    width answer ONE `unknown_input` for the pairing. An unsettled dimension, or a source holding
    only one side, answers `unknown_input`, and an unsettled controller leaves nothing judged."""

    rule_id = "module_contract_mismatch"
    matrix_cell = CELL
    needs = Needs(facts=(MODULE_INTERFACES,))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        grouped: dict[UUID | None, tuple[_Held, _Held]] = {}
        for holder, held in facts.module_interfaces.items():
            policies, controllers = grouped.setdefault(held.source_id, ([], []))
            for interface in held.interfaces:
                side = policies if interface.role == "policy" else controllers
                side.append((holder, interface))
        return [found for sides in grouped.values() for found in self._judge(*sides)]

    def _judge(self, policies: _Held, controllers: _Held) -> list[RuleResult]:
        if not controllers:
            return [unknown_input(self, CONTROLLER_INPUTS, *(holder for holder, _ in policies))]
        if not policies:
            return [unknown_input(self, POLICY_ACTIONS, *(holder for holder, _ in controllers))]
        unsettled = [
            unknown_input(self, _unsettled(interface, need), holder)
            for need, side in ((CONTROLLER_INPUTS, controllers), (POLICY_ACTIONS, policies))
            for holder, interface in side
            if _width(interface) is None
        ]
        widths = {interface.inputs for _, interface in controllers}
        if None in widths:  # the policy may feed the unsettled controller
            return unsettled
        if len(widths) > 1:
            holders = dict.fromkeys(holder for holder, _ in (*policies, *controllers))
            return [*unsettled, unknown_input(self, PAIRING, *holders)]
        return unsettled + [
            _compared(policy, controller)
            for policy in policies
            if policy[1].outputs is not None
            for controller in controllers
        ]


class LoopRateLatency(UnstatedFactRule):
    """A control loop's rate against the latency budget of the path it runs on."""

    rule_id = "loop_rate_latency"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="loop_latency_s",
                set_in="a `.solus` constraints/rules entry with `quantity: loop_latency_s`",
            ),
        )
    )


class ConfigProtocolMismatch(UnstatedFactRule):
    """The protocol a repo config names against the one the firmware speaks."""

    rule_id = "config_protocol_mismatch"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="firmware_protocol",
                set_in=(
                    "the robot's v2 config `protocol.driver_id`, against the firmware's bus "
                    "protocol in its hardware review"
                ),
            ),
        )
    )


def _width(interface: ModuleInterface) -> int | None:
    """The side a contract compares: a policy's outputs, a controller's inputs."""
    return interface.outputs if interface.role == "policy" else interface.inputs


def _unsettled(interface: ModuleInterface, need: FactNeed) -> FactNeed:
    """The field a module leaves unsettled, and where it is written."""
    name = interface.ambiguous[0] if interface.ambiguous else need.name
    return FactNeed(name=name, set_in=f"{interface.ref}, as a literal integer")


def _compared(
    policy: tuple[UUID, ModuleInterface], controller: tuple[UUID, ModuleInterface]
) -> RuleResult:
    (policy_id, acts), (controller_id, takes) = policy, controller
    acts_path, takes_path = acts.ref.rpartition(":")[0], takes.ref.rpartition(":")[0]
    evidence = {
        "policy_ref": acts.ref,
        "action_dim": acts.outputs,
        "controller_ref": takes.ref,
        "input_dim": takes.inputs,
    }
    subjects = (policy_id, controller_id)
    if acts.outputs == takes.inputs:
        message = (
            f"`{acts_path}`'s action space matches the {takes.inputs} inputs `{takes_path}` takes"
        )
        return RuleResult(status="pass", message=message, subjects=subjects, evidence=evidence)
    return RuleResult(
        status="fail",
        severity=Severity.WARNING,
        message=(
            f"`{acts_path}`'s action space is {acts.outputs} wide but `{takes_path}` takes "
            f"{takes.inputs} inputs"
        ),
        subjects=subjects,
        evidence=evidence,
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    PackageVersionConflict(),
    ModuleContractMismatch(),
    LoopRateLatency(),
    ConfigProtocolMismatch(),
)
