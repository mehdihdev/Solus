"""SOLUSDEV-321 P4-T4 — the external routing targets (D1); SOLUSDEV-322 P1-T3 — connected is
registered.

Rungs 2 and 4 are other systems. models.yaml names them (`simulation.targets`) and the module
names none: each is wrapped as a provider the ladder ranks, and reached only through its own
routine tool, `<target>.run_routine`, whose gate decides per call. A target whose routine tool the
turn's registry does not hold is "not connected". None ever runs in process.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Final

import pytest
from solus_api.orchestration.config import SimTargetConfig, SimulationConfig
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.simulation.providers import external_providers
from solus_api.simulation.providers.external_providers import (
    NOT_CONNECTED,
    ExternalProviders,
    ExternalTarget,
)
from solus_api.simulation.sim_capability import (
    SimProvider,
    SimQuestion,
    SimulationRefusedError,
)
from solus_api.simulation.sim_ladder import LadderContext, _order, propose_for

#: A yaml of the test's own: a rung-2 routing target and a rung-4 full simulation.
TWO: Final = SimulationConfig(
    targets=(
        SimTargetConfig(name="routing_x", rung=2, domain="electrical", quantities=("ripple_v",)),
        SimTargetConfig(
            name="full_y", rung=4, domain="mechanical", quantities=("joint_trajectory",), cost=9
        ),
    )
)


def test_targets_come_from_yaml() -> None:
    shipped = default_orchestration_config().simulation
    providers = ExternalProviders.of(shipped, registered=frozenset())
    assert [target.name for target in providers.targets] == [row.name for row in shipped.targets]
    for target, row in zip(providers.targets, shipped.targets, strict=True):
        assert (target.rung, target.domain) == (row.rung, row.domain)
        assert target.quantities == frozenset(row.quantities)
        assert target.tool == f"{row.name}.run_routine"
    assert providers.connected == frozenset()

    both = ExternalProviders.of(TWO, registered=frozenset({"routing_x.run_routine"}))
    assert [(target.name, target.rung) for target in both.targets] == [
        ("routing_x", 2),
        ("full_y", 4),
    ]
    assert both.connected == frozenset({"routing_x"})
    # The yaml names the targets; the module never does (both hygiene ratchets sweep it too).
    source = Path(external_providers.__file__).read_text(encoding="utf-8")
    for name in ("routing_x", "full_y", *(row.name for row in shipped.targets)):
        assert name not in source


def test_a_target_connects_when_its_routine_tool_is_registered_regardless_of_gate() -> None:
    """Connection is registration (P1-T3): the registry holds the routine tool, gated or not. A
    sibling tool of the same server never connects it."""
    connected = ExternalProviders.of(TWO, registered=frozenset({"full_y.run_routine"}))
    assert connected.connected == frozenset({"full_y"})
    route = connected.route("full_y")
    assert route is not None
    assert (route["connected"], route["rung"], route["tool"]) == (True, 4, "full_y.run_routine")
    assert route["status"].startswith("call full_y.run_routine: it previews the run")
    for registered in (frozenset(), frozenset({"full_y.status", "routing_x.run_routine"})):
        route = ExternalProviders.of(TWO, registered=registered).route("full_y")
        assert route is not None
        assert (route["connected"], route["status"]) == (False, NOT_CONNECTED)
    assert connected.route("a_provider_not_in_the_yaml") is None


def test_route_says_per_call_gate() -> None:
    """A route no longer promises a card: the tool's gate decides per call (P2-T2), so the
    route says `gate: "per call"` and carries no `requires_confirmation`."""
    for registered in (frozenset(), frozenset({"full_y.run_routine"})):
        route = ExternalProviders.of(TWO, registered=registered).route("full_y")
        assert route is not None
        assert route["gate"] == "per call"
        assert "requires_confirmation" not in route
        assert set(route) == {"rung", "target", "tool", "gate", "connected", "status"}


def test_gazebo_ranks_before_isaac_on_cost_when_both_connected() -> None:
    """The shipped yaml's two rung-4 targets both compute `joint_trajectory`; the cheaper one
    (`gazebo`, cost 3) wins the where-order when both are connected."""
    shipped = default_orchestration_config().simulation
    both = frozenset(f"{row.name}.run_routine" for row in shipped.targets)
    providers = ExternalProviders.of(shipped, registered=both)
    assert providers.connected == {"gazebo", "isaac"}
    ladder = LadderContext(
        config=shipped, providers=providers.targets, available=providers.connected
    )
    ordered = sorted(providers.targets, key=lambda p: _order(p, None, ladder))
    assert [p.name for p in ordered][:2] == ["gazebo", "isaac"]
    gazebo, isaac = (shipped.target("gazebo"), shipped.target("isaac"))
    assert gazebo is not None and isaac is not None
    assert (gazebo.rung, gazebo.cost, gazebo.fidelity) == (4, 3, 3)
    assert (isaac.rung, isaac.cost, isaac.fidelity) == (4, 4, 4)
    assert gazebo.quantities == isaac.quantities == ("joint_trajectory",)


def test_a_target_never_runs_here() -> None:
    target: SimProvider = ExternalTarget(
        name="full_y", domain="mechanical", rung=4, quantities=frozenset({"joint_trajectory"})
    )
    asked = SimQuestion(subject_id=uuid.uuid4(), quantity="joint_trajectory", facts={})
    lacks = target.can_answer(asked)
    assert (lacks.missing, lacks.derivable) == ((), ())
    with pytest.raises(ValueError, match="does not compute 'stress_mpa'"):
        target.can_answer(asked.model_copy(update={"quantity": "stress_mpa"}))
    with pytest.raises(SimulationRefusedError, match=r"only through full_y\.run_routine"):
        target.run({})


def test_the_ladder_proposes_a_target_and_says_when_it_is_not_connected() -> None:
    providers = ExternalProviders.of(TWO, registered=frozenset())
    ladder = LadderContext(config=TWO, providers=providers.targets, available=providers.connected)
    question = SimQuestion(subject_id=uuid.uuid4(), quantity="joint_trajectory", facts={})
    proposal = propose_for(question, trigger="user", context=ladder)
    assert proposal is not None
    assert (proposal.rung, proposal.target, proposal.decision) == (4, "full_y", "run")
    assert proposal.available is False
