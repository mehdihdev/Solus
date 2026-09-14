"""Reviewed execution knowledge stays vendor-only and annotates existing tools only."""

import ast
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from solus_api.agent.tools import knowledge
from solus_api.contracts.tool_knowledge import ToolFamily, ToolKnowledge
from solus_api.toolkb.catalog import is_vendor_doc_url
from solus_api.toolkb.schema import AcquisitionMethod, version_key, version_keys

ROOT = Path(__file__).resolve().parents[3]
MAPPINGS = {
    "code.git_commit": "code.git.commit",
    "code.git_push": "code.git.push",
    "code.arduino_prepare": "code.arduino.core_install",
    "code.arduino_compile": "code.arduino.compile",
}


def entries() -> list[tuple[dict[str, Any], str]]:
    return cast(
        list[tuple[dict[str, Any], str]],
        runpy.run_path(str(ROOT / "scripts/seed-toolkb-mcp-controls.py"))["ENTRIES"],
    )


def test_reviewed_execution_seeds_are_versioned_and_pass_closed_contract() -> None:
    selected = {
        row["control_id"]: (row, url) for row, url in entries() if row["tool"] in {"code", "isaac"}
    }
    assert set(MAPPINGS.values()) | {"isaac.standalone.application"} <= selected.keys()
    for control, (row, url) in selected.items():
        tk = ToolKnowledge.model_validate(row)
        assert is_vendor_doc_url(tk.tool, url)
        assert tk.surface.value == "terminal"
        effects = {
            "code.git.status": "measure",
            "code.git.diff": "measure",
            "code.git.log": "navigate",
            "code.git.show": "navigate",
            "code.git.branch": "select",
            "code.git.remote": "settings",
            "isaac.urdf.import": "import",
            "isaac.articulation.position_drive": "modify_feature",
            "isaac.articulation.joint_limits": "settings",
            "isaac.sensor.contact": "measure",
            "isaac.transform.local_pose": "modify_feature",
        }
        assert tk.effect.value == effects.get(control, "execute")
        assert tk.provenance.value == "vendor_docs"
        expected = (
            "2.43.0"
            if control.startswith("code.git.")
            else "1.5.1"
            if control.startswith("code.arduino.")
            else "6.0.0"
        )
        low, high = version_keys(tk.version_range)
        assert low == version_key(expected)
        assert high is not None
        assert not low <= version_key("9.0.0") < high
        assert tk.invocation is None and tk.locator is None
        for forbidden in ({"command": "untrusted"}, {"description": "/home/customer/private.ino"}):
            with pytest.raises(ValidationError):
                ToolKnowledge.model_validate({**row, **forbidden})


def test_execution_mappings_name_registered_tools() -> None:
    parsed = ast.parse((ROOT / "integrations/mcp/code/solus/server.py").read_text())
    roster = next(
        node.value
        for node in parsed.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_TOOLS"
    )
    assert isinstance(roster, ast.Dict)
    names = {"code." + str(ast.literal_eval(key)) for key in roster.keys if key is not None}
    for name, control in MAPPINGS.items():
        assert name in names
        assert knowledge.TOOL_CONTROLS.get(name) == (ToolFamily.CODE, control)
    from solus_api.agent.tools.isaac_models import PUBLIC_MODELS

    assert "start" in PUBLIC_MODELS
    assert knowledge.TOOL_CONTROLS.get("isaac.start") == (
        ToolFamily.ISAAC,
        "isaac.standalone.application",
    )


@pytest.mark.parametrize("trusted", [True, False])
async def test_execution_notes_reuse_only_trusted_docs_path(
    monkeypatch: pytest.MonkeyPatch, trusted: bool
) -> None:
    rows = {
        row["control_id"]: ToolKnowledge.model_validate(row)
        for row, _ in entries()
        if row["tool"] == "code"
    }

    async def query(*args: Any, **kwargs: Any) -> tuple[list[Any], None]:
        tk = rows.get(kwargs["control_id"])
        return (
            []
            if tk is None
            else [
                SimpleNamespace(
                    **tk.model_dump(),
                    acquired_via=AcquisitionMethod.DOCS if trusted else AcquisitionMethod.OPERATOR,
                    confidence=0.8,
                    shortcut=None,
                )
            ]
        ), None

    monkeypatch.setattr(knowledge, "query_entries", query)
    notes = await knowledge.load_knowledge_notes(cast(Any, None))
    if not trusted:
        assert not notes
        return
    assert set(MAPPINGS) <= notes.keys()
    for name, control in MAPPINGS.items():
        assert notes[name].control_id == control
        assert len(notes[name].text) <= knowledge.NOTE_CAP


@pytest.mark.parametrize(
    "value",
    [
        {"ok": False, "exit_code": 0, "reason": "compilation_unverified"},
        {"ok": False, "exit_code": 1},
        {"ok": False, "uncertain": True},
        {"ok": True, "uncertain": True},
        {"ok": True, "timed_out": True},
        {"ok": True, "exit_code": 1},
        {"ok": True, "exit_code": None},
        {"ok": True, "exit_code": False},
        {"ok": True, "dry_run": True},
        {"exit_code": 0},
    ],
)
@pytest.mark.parametrize("name", list(MAPPINGS))
def test_failed_or_unverified_code_outcomes_do_not_vote_on_vendor_facts(
    name: str, value: dict[str, Any]
) -> None:
    from solus_api.agent.tools.shapes import ToolResult

    assert knowledge.write_verdict(name, ToolResult.success("call-1", value)) is None


@pytest.mark.parametrize(
    "value",
    [
        {"ok": True, "exit_code": 0, "started": True},
        {"ok": True, "changed": False, "started": False, "exit_code": 0},
        {"ok": True, "changed": True},
    ],
)
def test_explicit_successful_code_outcomes_can_confirm_vendor_facts(value: dict[str, Any]) -> None:
    from solus_api.agent.tools.shapes import ToolResult
    from solus_api.toolkb.schema import Verdict

    assert (
        knowledge.write_verdict("code.arduino_compile", ToolResult.success("call-1", value))
        is Verdict.CONFIRM
    )


@pytest.mark.parametrize("name", list(MAPPINGS))
def test_code_tool_failure_abstains_on_vendor_documentation(name: str) -> None:
    from solus_api.agent.tools.shapes import ToolError, ToolErrorCode, ToolResult

    result = ToolResult.failure(
        "call-1", ToolError(code=ToolErrorCode.TOOL_ERROR, message="refused")
    )
    assert knowledge.write_verdict(name, result) is None
