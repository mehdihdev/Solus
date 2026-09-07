"""`PinConflictChecker` + the environment proposal (SOLUSDEV-250 / INTEGRATIONS I3): pure
rules over `python_requirement` nodes. No DB."""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.core import DEFAULT_CHECKERS, run_all
from solus_api.checkers.environment import (
    PinConflictChecker,
    normalize_package_name,
    propose_environments,
)
from solus_api.checkers.interface import Severity
from solus_api.fingerprint.contract import FingerprintOutput


def _req(name: str, specifier: str, source: str, **extra: Any) -> EntityRead:
    return EntityRead(
        id=uuid.uuid4(),
        kind="python_requirement",
        domain="code",
        name=f"{name} {specifier}".strip(),
        attrs={"name": name, "specifier": specifier, "source_file": source, **extra},
    )


def _ctx(*entities: EntityRead) -> GraphContext:
    return GraphContext(entities=list(entities), edges=[])


EMPTY = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])


def test_registered_in_the_default_roster() -> None:
    assert any(isinstance(c, PinConflictChecker) for c in DEFAULT_CHECKERS)


def test_normalises_names_per_pep_503() -> None:
    assert normalize_package_name("Torch") == "torch"
    assert normalize_package_name("scikit_learn") == "scikit-learn"
    assert normalize_package_name("Py.Test") == "py-test"


def test_two_different_pins_are_a_critical_conflict() -> None:
    isaac = _req("torch", "==2.1.0", "isaac/requirements.txt")
    policy = _req("Torch", "==2.3.0", "requirements.txt")
    (warning,) = PinConflictChecker().check(_ctx(isaac, policy), EMPTY)
    assert warning.checker_id == "python_pin_conflict"
    assert warning.severity is Severity.CRITICAL
    assert warning.domains == ("code",)
    assert "torch" in warning.message and "isaac/requirements.txt" in warning.message
    assert set(warning.entity_ids) == {isaac.id, policy.id}
    pins = {p["source_file"]: p["specifier"] for p in warning.evidence["pins"]}
    assert pins == {"isaac/requirements.txt": "==2.1.0", "requirements.txt": "==2.3.0"}
    assert "split" in (warning.suggested_area or "")


def test_a_pin_outside_another_range_is_a_warning() -> None:
    pinned = _req("torch", "==2.1.0", "isaac/requirements.txt")
    ranged = _req("torch", ">=2.3", "pyproject.toml")
    (warning,) = PinConflictChecker().check(_ctx(pinned, ranged), EMPTY)
    assert warning.severity is Severity.WARNING
    assert warning.evidence["package"] == "torch"


def test_compatible_specifiers_and_unpinned_are_silent() -> None:
    ctx = _ctx(
        _req("numpy", ">=1.26", "requirements.txt"),
        _req("numpy", "<3", "isaac/requirements.txt"),
        _req("numpy", "", "pyproject.toml"),
        _req("torch", "==2.3.0", "requirements.txt"),
        _req("torch", "==2.3.0", "requirements-dev.txt"),  # same pin twice: fine
    )
    assert PinConflictChecker().check(ctx, EMPTY) == []


def test_malformed_specifiers_skip_rather_than_guess() -> None:
    ctx = _ctx(_req("torch", "==2.1.0", "a.txt"), _req("torch", "not a spec!!", "b.txt"))
    assert PinConflictChecker().check(ctx, EMPTY) == []
    # And nodes without the attributes a rule needs are skipped, never a crash.
    bare = EntityRead(id=uuid.uuid4(), kind="python_requirement", domain="code", name="x")
    assert PinConflictChecker().check(_ctx(bare, bare), EMPTY) == []


def test_run_all_includes_the_environment_rule() -> None:
    ctx = _ctx(_req("torch", "==2.1.0", "a.txt"), _req("torch", "==2.3.0", "b.txt"))
    assert [w.checker_id for w in run_all(ctx, EMPTY)] == ["python_pin_conflict"]


def test_proposal_splits_by_source_file_only_when_pins_conflict() -> None:
    reqs = [
        _req("torch", "==2.1.0", "isaac/requirements.txt"),
        _req("numpy", "", "isaac/requirements.txt"),
        _req("torch", "==2.3.0", "requirements.txt"),
        _req("gymnasium", ">=0.29", "requirements.txt"),
    ]
    proposal = propose_environments(_ctx(*reqs))
    assert proposal["split"] is True
    names = {e["name"]: e for e in proposal["environments"]}
    assert set(names) == {"isaac", "policy"} or len(names) == 2
    for env in proposal["environments"]:
        assert env["source_files"] and env["requirements"]
        assert all(r["source_file"] in env["source_files"] for r in env["requirements"])
    assert [w["checker_id"] for w in proposal["conflicts"]] == ["python_pin_conflict"]

    single = propose_environments(_ctx(reqs[1], reqs[3]))
    assert single["split"] is False
    (env,) = single["environments"]
    assert env["name"] == "default" and len(env["requirements"]) == 2

    empty = propose_environments(_ctx())
    assert empty == {"environments": [], "conflicts": [], "split": False}
