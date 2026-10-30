"""SOLUSDEV-320 T3: `graph/kinds.py` is the one vocabulary of `graph_entity.kind`."""

from __future__ import annotations

from typing import Final

from solus_api.graph import kinds

#: Literals that pre-date kinds.py and keep their module-local name for now.
_TWINS: Final[list[tuple[str, str, str]]] = [
    ("solus_api.services.solus_graph", "SOLUS_KIND", "SOLUS_CONFIG"),
    ("solus_api.services.solus_graph", "DOCUMENT_KIND", "DOCUMENT"),
    ("solus_api.services.solus_graph", "CONFIG_NODE_KIND", "HARDWARE_CONFIG"),
    ("solus_api.hardware.store", "ROBOT_KIND", "PHYSICAL_ROBOT"),
    ("solus_api.hardware.store", "CATEGORY_KIND", "ROBOT_CATEGORY"),
    ("solus_api.hardware.store", "PART_KIND", "PART"),
    ("solus_api.hardware.companion_deployment", "KIND", "COMPANION_DEPLOYMENT_PLAN"),
    ("solus_api.hardware.presence_topology", "KIND", "HARDWARE_WIRING_PROPOSAL"),
    ("solus_api.hardware.presence", "KIND", "HARDWARE_PRESENCE_PLAN"),
    ("solus_api.fingerprint.ingest", "CANONICAL_KIND", "CANONICAL_PART"),
    ("solus_api.livebench.scene.service", "KIND", "BENCH_SCENE_MODEL"),
    ("solus_api.livebench.scene.cad_import", "IMPORT_KIND", "BENCH_SCENE_CAD_IMPORT"),
    ("solus_api.livebench.runs.store", "RUN_KIND", "BENCH_RUN"),
    ("solus_api.widgets.graph_nodes", "WORKSPACE_KIND", "WORKSPACE"),
    ("solus_api.widgets.graph_nodes", "LIVE_BENCH_KIND", "LIVE_BENCH"),
    ("solus_api.widgets.graph_nodes", "WIDGET_KIND", "WIDGET"),
    ("solus_api.widgets.solus_config", "SOLUS_CONFIG_KIND", "SOLUS_PROJECT_TOML"),
    ("solus_api.sourcing.service", "RULES_KIND", "SOURCING_RULES"),
]


def _constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(kinds).items()
        if name.isupper() and isinstance(value, str) and name != "ALL_KINDS"
    }


def test_every_kind_is_unique_and_in_all_kinds() -> None:
    values = list(_constants().values())
    assert len(values) == len(set(values))
    assert kinds.ALL_KINDS == frozenset(values)
    assert isinstance(kinds.ALL_KINDS, frozenset)


def test_every_kind_is_lowercase_except_the_legacy_camel_case_plan() -> None:
    # `companionDeploymentPlan` pre-dates the convention and is stored in dev DBs;
    # renaming it is a data migration, not a constants file.
    for name, value in _constants().items():
        if name == "COMPANION_DEPLOYMENT_PLAN":
            assert value == "companionDeploymentPlan"
            continue
        assert value == value.lower(), name


def test_new_kinds_exist() -> None:
    assert kinds.FINDING == "finding"
    assert kinds.MACHINE == "machine"
    assert kinds.MEMBER == "member"
    assert kinds.SOLUS_SUBSECTION == "solus_subsection"
    assert kinds.SOLUS_GOAL == "solus_goal"
    assert kinds.SOLUS_CONSTRAINT == "solus_constraint"
    assert kinds.PACKAGE_REQUIREMENT == "package_requirement"


def test_existing_literals_match_the_constants() -> None:
    import importlib

    for module_name, attr, constant in _TWINS:
        module = importlib.import_module(module_name)
        assert getattr(module, attr) == getattr(kinds, constant), (module_name, attr)
