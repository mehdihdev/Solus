"""Vendor control seed coverage, without ingestion or database access."""

import runpy
from pathlib import Path
from typing import Any, cast

import pytest
from solus_api.contracts.tool_knowledge import ToolKnowledge
from solus_api.toolkb.schema import version_key, version_keys

SEED = Path(__file__).resolve().parents[3] / "scripts" / "seed-toolkb-mcp-controls.py"


def _entries() -> list[tuple[dict[str, Any], str]]:
    return cast(list[tuple[dict[str, Any], str]], runpy.run_path(str(SEED))["ENTRIES"])


@pytest.mark.parametrize("version", ["8.0", "9.0", "10.0.6"])
def test_symbol_properties_covers_supported_kicad_versions(version: str) -> None:
    matched = []
    for entry, url in _entries():
        if entry["control_id"] != "kicad.eeschema.edit_symbol_properties":
            continue
        low, high = version_keys(entry["version_range"])
        if low <= version_key(version) and (high is None or version_key(version) < high):
            matched.append((entry, url))
    assert len(matched) == 1
    if version.startswith("10."):
        assert matched[0][0]["version_range"] == ">=10.0 <11.0"
        assert matched[0][1] == "https://docs.kicad.org/10.0/en/eeschema/eeschema.html"


@pytest.mark.parametrize(
    ("control", "description", "page"),
    [
        (
            "variable_table",
            "Creates, views, and edits variables in the current Part Studio. "
            "Variables referenced from another document are read-only in the inserted table.",
            "variable_table.htm",
        ),
        (
            "feature_list",
            "Lists the ordered features in a Part Studio and provides access "
            "to edit and reorder them.",
            "features_and_parts_lists.htm",
        ),
    ],
)
def test_onshape_seed_describes_documented_ui_control(
    control: str, description: str, page: str
) -> None:
    entry, url = next(
        pair for pair in _entries() if pair[0]["control_id"] == "onshape.partstudio." + control
    )
    assert entry["description"] == description
    assert url == "https://cad.onshape.com/help/Content/PartStudio/" + page
    # Preserve the pre-existing lookup identity; this is not a verified SaaS release.
    assert entry["version_range"] == ">=1.0 <2.0"


def test_all_seed_entries_pass_global_vendor_contract_with_unique_identities() -> None:
    identities = set()
    for entry, _ in _entries():
        validated = ToolKnowledge.model_validate(entry)
        assert validated.provenance.value == "vendor_docs"
        identity = (
            validated.tool,
            validated.control_id,
            validated.surface,
            validated.version_range,
        )
        assert identity not in identities
        identities.add(identity)


def test_supported_workflows_have_meaningful_vendor_control_coverage() -> None:
    required = {
        "code.git.status",
        "code.git.diff",
        "code.git.log",
        "code.git.show",
        "code.git.branch",
        "code.git.remote",
        "kicad.eeschema.wire",
        "kicad.eeschema.net_label",
        "kicad.eeschema.erc",
        "kicad.eeschema.symbol_chooser",
        "isaac.urdf.import",
        "isaac.articulation.position_drive",
        "isaac.articulation.joint_limits",
        "isaac.sensor.contact",
        "isaac.transform.local_pose",
        "isaac.physics.stepping",
    }
    entries = {entry["control_id"]: (entry, url) for entry, url in _entries()}
    assert required <= entries.keys()
    for control in required:
        entry, url = entries[control]
        assert 80 <= len(entry["description"]) <= 400
        assert url.startswith(
            (
                "https://git-scm.com/docs/",
                "https://docs.kicad.org/10.0/",
                "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/",
            )
        )


def test_seed_family_filter_preserves_existing_onshape_records() -> None:
    module = runpy.run_path(str(SEED))
    selected = module["select_entries"](["kicad", "code", "isaac"])
    assert selected
    assert {entry["tool"] for entry, _ in selected} == {"kicad", "code", "isaac"}
    assert len(module["ENTRIES"]) == len(_entries())
    with pytest.raises(ValueError, match="family"):
        module["select_entries"](["unknown"])
