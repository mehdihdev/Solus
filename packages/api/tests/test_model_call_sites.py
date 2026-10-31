"""SOLUSDEV-321 — the model-free modules name no model call.

The scope planner (`agent/turn_scope.py`, P1-T1) decides what SOL looks at without a model call
of its own: its one tie-break is a callable the runner injects. The first tier
(`agent/deterministic.py` and its facts, P1-T2) answers lookups with none at all. This ratchet
holds that line by text, comments included, so a call cannot hide in one either. A later
model-free module appends its path to `MODEL_FREE_PATHS`. A path ending in `/` is a package, and
every module in it is swept. `checkers/` (P3) is one: a rule judges the graph and the facts it is
given. `simulation/` (P4-T1) is another: the ladder only proposes, and neither it nor the facts
writer calls a model. Its rung-1 providers (P4-T2) are closed-form code. `software/` (P6) is a
third: its readers run inside a sync, and what they cannot read is recorded, never asked about.
P7's reasoning parser and reply citations read the model's text after the call, and its versioned
tool notes read the knowledge base; none of them makes one. Nor do P8's outcome recorder and its
design signals: a decision is recorded from what Solus already holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import solus_api

SRC_ROOT: Final = Path(solus_api.__file__).resolve().parent
MODEL_FREE_PATHS: Final = (
    "agent/turn_scope.py",
    "agent/deterministic.py",
    "agent/deterministic_facts.py",
    "agent/reasoning_frame.py",
    "agent/citations.py",
    "agent/guide_toolkb_version.py",
    "services/outcomes.py",
    "services/change_signals.py",
    "checkers/",
    "simulation/",
    "software/",
)
MODEL_CALL_WORDS: Final = ("gateway", "complete(", "stream(", ".invoke(")


def model_free_files(root: Path) -> list[Path]:
    """Each listed module, and every module in each listed package."""
    return [
        module
        for path in MODEL_FREE_PATHS
        for module in (sorted((root / path).rglob("*.py")) if path.endswith("/") else [root / path])
    ]


def test_model_free_modules_name_no_model_call() -> None:
    found = [
        f"{module.relative_to(SRC_ROOT)}: {word}"
        for module in model_free_files(SRC_ROOT)
        for word in MODEL_CALL_WORDS
        if word in module.read_text()
    ]
    assert found == []


def test_the_checkers_package_is_swept_module_by_module() -> None:
    """P3: the matrix runner, its rules and the fact store judge with no model of their own. Their
    line was never added, and a module added to the package is swept with them."""
    swept = {module.relative_to(SRC_ROOT).as_posix() for module in model_free_files(SRC_ROOT)}
    assert {
        "checkers/matrix_runner.py",
        "checkers/matrix_rule.py",
        "checkers/fact_store.py",
        "checkers/checker_trigger.py",
        "checkers/cells/mechanical_mechanical.py",
    } <= swept


def test_the_software_package_is_swept_module_by_module() -> None:
    """P6: the ROS and policy readers run during a sync and read by structure, with no model:
    ambiguity is recorded as `unknown_input`, never asked about. A module added to the package is
    swept with them."""
    swept = {module.relative_to(SRC_ROOT).as_posix() for module in model_free_files(SRC_ROOT)}
    assert "software/__init__.py" in swept
    assert "software/" in MODEL_FREE_PATHS


def test_the_simulation_package_is_swept_module_by_module() -> None:
    """P4-T1: the ladder, the capability and the facts writer are model-free from their first
    commit, and a module added to the package is swept with them."""
    swept = {module.relative_to(SRC_ROOT).as_posix() for module in model_free_files(SRC_ROOT)}
    assert {
        "simulation/sim_capability.py",
        "simulation/sim_ladder.py",
        "simulation/sim_facts.py",
    } <= swept
