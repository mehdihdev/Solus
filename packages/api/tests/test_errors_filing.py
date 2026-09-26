"""I3 command results share the generic one-entry error recorder."""

from solus_api.agent.errors_filing import format_error_entry, run_failure
from solus_api.agent.tools.shapes import ToolCall, ToolResult


def test_i3_actions_opt_into_the_single_error_recorder() -> None:
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[3] / "integrations/mcp/code/allowlist.yaml"
    document = yaml.safe_load(path.read_text())
    actions = [tool for tool in document["tools"] if tool["requires_confirmation"]]
    assert {tool["name"] for tool in actions} == {
        "create_environment",
        "install",
        "run",
        "test",
        "git_commit",
        "git_push",
        "arduino_prepare",
        "arduino_compile",
        "arduino_upload",
    }
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


def test_explicit_failure_after_zero_exit_is_recorded() -> None:
    result = ToolResult.success(
        "compile", {"ok": False, "exit_code": 0, "reason": "compilation_unverified"}
    )
    failure = run_failure(result)
    assert failure is not None and "failed" in failure
    assert "compilation_unverified" in failure


def test_started_failure_without_exit_is_recorded_but_legacy_refusal_is_not() -> None:
    value = {"ok": False, "exit_code": None, "reason": "resource_limit"}
    assert run_failure(ToolResult.success("refusal", value)) is None
    failure = run_failure(ToolResult.success("started", {**value, "started": True}))
    assert failure is not None and "failed" in failure and "resource_limit" in failure
    assert run_failure(ToolResult.success("cad", {"ok": False, "changed": False})) is None
    assert (
        run_failure(ToolResult.success("plan", {**value, "started": True, "dry_run": True})) is None
    )


def test_failed_zero_exit_step_is_recorded_with_its_position() -> None:
    result = ToolResult.success(
        "steps",
        {
            "results": [
                {"ok": True, "exit_code": 0},
                {"ok": False, "exit_code": 0, "reason": "readback_failed"},
            ]
        },
    )
    failure = run_failure(result)
    assert failure is not None and "step 2" in failure and "readback_failed" in failure
