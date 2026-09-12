"""I3 command results share the generic one-entry error recorder."""

from solus_api.agent.errors_filing import format_error_entry, run_failure
from solus_api.agent.tools.shapes import ToolCall, ToolResult


def test_i3_actions_opt_into_the_single_error_recorder() -> None:
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[3] / "integrations/mcp/code/allowlist.yaml"
    document = yaml.safe_load(path.read_text())
    actions = [tool for tool in document["tools"] if tool["requires_confirmation"]]
    assert {tool["name"] for tool in actions} == {"create_environment", "install", "run", "test"}
    assert all(tool.get("files_errors") is True for tool in actions)


def test_i3_failure_retains_both_redacted_output_tails() -> None:
    result = ToolResult.success(
        "fixture",
        {"exit_code": 1, "stdout_tail": "FAILED fixture", "stderr_tail": "Traceback fixture"},
    )
    assert "FAILED fixture" in (run_failure(result) or "")
    assert "Traceback fixture" in (run_failure(result) or "")
    text = format_error_entry(ToolCall(tool="code.test", args={}, call_id="fixture"), result)
    assert "FAILED fixture" in text and "Traceback fixture" in text


def test_error_record_preserves_the_executed_argv() -> None:
    result = ToolResult.success(
        "fixture", {"exit_code": 1, "argv": [".venv/bin/python", "-m", "pytest"]}
    )
    text = format_error_entry(ToolCall(tool="code.test", args={}, call_id="fixture"), result)
    assert ".venv/bin/python" in text and "pytest" in text
