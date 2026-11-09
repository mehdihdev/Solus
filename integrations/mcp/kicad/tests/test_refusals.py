"""Strict refusals reach SOL as `<code>: <explanation>`, never a bare code."""

import re
from pathlib import Path

import pytest

from test_overlay_support import FakeMCP  # isort: skip
from solus.refusals import REFUSAL_EXPLANATIONS, refusal_message
from solus.registration import register_allowlisted_tools

SOLUS_DIR = Path(__file__).parents[1] / "solus"


def test_known_reason_gets_its_explanation() -> None:
    assert refusal_message("stale_plan") == f"stale_plan: {REFUSAL_EXPLANATIONS['stale_plan']}"


def test_unknown_reason_passes_through_unchanged() -> None:
    assert refusal_message("something_new") == "something_new"


def test_drawing_tool_refusal_carries_code_and_explanation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FakeMCP()
    register_allowlisted_tools(server)
    with pytest.raises(ValueError) as refused:
        server.tools["create_schematic"](
            schematic_path="robot.kicad_sch", title="Robot", expected_absent=False, dry_run=True
        )
    assert str(refused.value) == refusal_message("already_exists")


def test_confined_path_refusal_carries_code_and_explanation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    server = FakeMCP()
    register_allowlisted_tools(server)
    with pytest.raises(ValueError) as refused:
        server.tools["create_schematic"](
            schematic_path="../robot.kicad_sch", title="Robot", expected_absent=True
        )
    assert str(refused.value) == refusal_message("path_escapes_workspace")


def test_every_write_tool_reason_has_an_explanation() -> None:
    source = "".join(path.read_text() for path in SOLUS_DIR.rglob("*.py"))
    raised = set(
        re.findall(r'(?:DevelopmentError|RefusalError|refusal_message)\("([a-z_]+)"', source)
    )
    raised |= set(re.findall(r'^REASON_[A-Z_]+ = "([a-z_]+)"', source, re.M))
    assert raised
    assert raised <= set(REFUSAL_EXPLANATIONS)


def test_editor_lock_explanation_tells_sol_to_ask_the_user_to_close_it() -> None:
    message = refusal_message("open_in_editor")
    assert message.startswith("open_in_editor: ")
    assert "close" in message and "KiCad" in message
