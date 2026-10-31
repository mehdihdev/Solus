"""SOLUSDEV-321 P3-T2 — the software → software cell: `package_version_conflict` judges the
dependency files' pins (the reading the code-environment proposal shares) and each machine's
recorded divergences; the cell's other rules wait for their facts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.software_software import (
    CELL,
    DIVERGENCES,
    RULES,
    PackageVersionConflict,
)
from solus_api.checkers.core import DEFAULT_CHECKERS
from solus_api.checkers.environment import PinConflictChecker
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.services.solus_payloads import (
    DivergenceGroup,
    DivergenceItem,
    EnvironmentDivergencesDoc,
    MachineDivergences,
)

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
_EMPTY: Final = GraphContext(entities=[], edges=[])
RULE: Final = PackageVersionConflict()


def _requirement(name: str, specifier: str, source: str) -> EntityRead:
    return EntityRead(
        id=uuid.uuid4(),
        kind="python_requirement",
        domain="code",
        name=f"{name} {specifier}",
        attrs={"name": name, "specifier": specifier, "source_file": source},
    )


def _machine(**groups: list[DivergenceItem]) -> MachineDivergences:
    return MachineDivergences(
        machine_id=uuid.uuid4(),
        hostname="bench-pc",
        causes=[
            DivergenceGroup.model_validate({"cause": cause, "items": items})
            for cause, items in groups.items()
        ],
    )


def _doc(*machines: MachineDivergences) -> EnvironmentDivergencesDoc:
    stamp = datetime(2026, 10, 27, tzinfo=UTC)
    return EnvironmentDivergencesDoc(computed_at=stamp, spec_entry_id=None, machines=[*machines])


def test_a_pin_conflict_fails_and_compatible_pins_are_silent() -> None:
    sim = _requirement("torch", "==2.1.0", "sim/requirements.txt")
    policy = _requirement("torch", "==2.3.0", "requirements.txt")
    graph = GraphContext(entities=[sim, policy], edges=[])

    pinned, unknown = RULE.results(graph, FactStore())

    assert (pinned.status, pinned.severity) == ("fail", Severity.CRITICAL)
    assert set(pinned.subjects) == {sim.id, policy.id}
    (legacy,) = PinConflictChecker().check(graph, _PARTS)
    assert pinned.message == legacy.message and pinned.evidence == legacy.evidence
    assert (unknown.status, unknown.missing) == ("unknown_input", DIVERGENCES)
    (warning,) = RULE.check(graph, _PARTS)
    assert warning.checker_id == "package_version_conflict"
    compatible = GraphContext(
        entities=[
            _requirement("numpy", ">=1.26", "requirements.txt"),
            _requirement("numpy", "<3", "sim/requirements.txt"),
        ],
        edges=[],
    )
    assert [r.status for r in RULE.results(compatible, FactStore())] == ["unknown_input"]


def test_a_machine_whose_versions_drift_fails_and_one_that_matches_passes() -> None:
    drift = _machine(version_drift=[DivergenceItem(name="torch", expected="==2.3", actual="2.1")])
    build = _machine(platform_build=[DivergenceItem(name="torch", expected="+cu121")])
    clean = _machine(missing=[DivergenceItem(name="rich")], extra=[DivergenceItem(name="tqdm")])

    results = RULE.results(_EMPTY, FactStore(divergences=_doc(drift, build, clean)))

    assert [(r.status, r.severity, r.subjects) for r in results] == [
        ("fail", Severity.WARNING, (drift.machine_id,)),
        ("fail", Severity.CRITICAL, (build.machine_id,)),
        ("pass", Severity.INFO, (clean.machine_id,)),
    ]
    assert results[0].evidence == {
        "machine": "bench-pc",
        "causes": {
            "version_drift": [
                {"name": "torch", "expected": "==2.3", "actual": "2.1", "detail": None}
            ]
        },
    }
    assert "torch" in results[0].message


def test_one_conflict_is_raised_once_project_wide() -> None:
    """The matrix raises the pin conflict; the legacy checker stays for the code-environment
    proposal and is no longer in the default roster (R38/R51)."""
    assert not any(isinstance(checker, PinConflictChecker) for checker in DEFAULT_CHECKERS)
    assert RULE.rule_id in {rule.rule_id for rule in RULES}


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    # SOLUSDEV-321 P6: `module_contract_mismatch` judges the software reader's module interfaces
    assert [rule.rule_id for rule in waiting] == ["loop_rate_latency", "config_protocol_mismatch"]
    for rule in waiting:
        (only,) = rule.evaluate(_EMPTY, FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
