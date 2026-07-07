"""Tests for the shared code-host mapping (W0-08) used by GitHub and GitLab."""

from solus_api.connectors.code_host import (
    basename,
    design_export_for,
    file_entity,
    module_entity,
    parent_key,
)
from solus_api.connectors.contracts import Domain

REPO_ROOT = ":repo"


def test_design_export_detection_by_extension() -> None:
    assert design_export_for("hw/board.GBR") == ("gerber", Domain.ELECTRICAL)
    assert design_export_for("mech/chassis.step") == ("step", Domain.MECHANICAL)
    assert design_export_for("elec/power.net") == ("netlist", Domain.ELECTRICAL)
    assert design_export_for("elec/filter.cir") == ("spice", Domain.ELECTRICAL)
    assert design_export_for("src/main.py") is None
    assert design_export_for("README") is None


def test_basename() -> None:
    assert basename("a/b/c.py") == "c.py"
    assert basename("solo") == "solo"


def test_parent_key_falls_back_to_root() -> None:
    known = {"src"}
    assert parent_key("src/main.py", known) == "src"
    assert parent_key("elided/dir/file.py", known) == REPO_ROOT
    assert parent_key("top.py", known) == REPO_ROOT


def test_file_entity_marks_design_export() -> None:
    entity = file_entity("hw/board.gbr", {"size": 10, "sha": "x"})
    assert entity.type == "design_export"
    assert entity.domain == Domain.ELECTRICAL
    assert entity.properties["export_kind"] == "gerber"

    code = file_entity("src/a.py", {"size": 5, "sha": "y"})
    assert code.type == "code_file"
    assert code.domain == Domain.SOFTWARE


def test_module_entity_shape() -> None:
    entity = module_entity("src/pkg")
    assert entity.type == "code_module"
    assert entity.name == "pkg"
    assert entity.source_key == "src/pkg"
