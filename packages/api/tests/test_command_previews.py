"""SOLUSDEV-317 approval-card rows for code.exec / process_start / profile_capture
(docs/api/code-command-execution.md §2.2, §5.2). Pure fakes: the reader stands in
for the companion's `code.plan`."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.command_previews import CAPTURE_SCRIPT, plan_fingerprint
from solus_api.bridge.previews import PREVIEWABLE_TOOLS, preview_builder

_DIGEST = "ab" * 32


class _Reader:
    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append((tool, dict(args)))
        return self.answer


def _plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "ok": True,
        "reason": None,
        "argv": ["/opt/ros/jazzy/bin/colcon", "build", "--symlink-install"],
        "cwd": "ros_ws",
        "sandbox": {"kind": "sandbox-exec", "writable": ["/w", "/tmp"]},
        "profile": {"name": "ros", "digest": _DIGEST},
        "environment": ".venv",
    }
    plan.update(overrides)
    return plan


_EXEC_ARGS = {"argv": ["colcon", "build", "--symlink-install"], "cwd": "ros_ws", "profile": "ros"}


def _fingerprint(argv: list[str], cwd: str, env: str | None, digest: str | None, kind: str) -> str:
    canonical = json.dumps(
        {
            "argv": argv,
            "cwd": cwd,
            "environment": env,
            "profile_digest": digest,
            "sandbox_kind": kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest_hex = hashlib.sha256(canonical.encode()).hexdigest()
    return ":".join(digest_hex[i : i + 16] for i in range(0, 64, 16))


def test_new_command_tools_are_previewable() -> None:
    assert {"code.exec", "code.process_start", "code.profile_capture"} <= set(PREVIEWABLE_TOOLS)
    assert "code.process_stop" not in PREVIEWABLE_TOOLS
    assert "code.profile_delete" not in PREVIEWABLE_TOOLS


async def _rows(tool: str, plan: dict[str, Any] | None, args: dict[str, Any]) -> list[Any]:
    builder = preview_builder(tool, _Reader(plan))
    assert builder is not None
    return await builder(args)


async def test_exec_rows_are_exactly_the_spec_rows_in_order() -> None:
    reader = _Reader(_plan())
    builder = preview_builder("code.exec", reader)
    assert builder is not None
    rows = await builder(dict(_EXEC_ARGS))
    assert reader.calls == [("code.plan", {"action": "exec", "args": _EXEC_ARGS})]
    argv = _plan()["argv"]
    assert rows == [
        {"label": "program", "before": None, "after": "/opt/ros/jazzy/bin/colcon"},
        {"label": "command", "before": None, "after": json.dumps(argv)},
        {"label": "cwd", "before": None, "after": "ros_ws"},
        {"label": "environment", "before": None, "after": ".venv"},
        {"label": "profile", "before": None, "after": f"ros · {_DIGEST[:12]}"},
        {
            "label": "sandbox",
            "before": None,
            "after": "sandbox-exec — writes limited to the workspace, temp and tool caches",
        },
        {"label": "risk", "before": None, "after": "project_scripts"},
        {
            "label": "plan fingerprint",
            "before": None,
            "after": _fingerprint(argv, "ros_ws", ".venv", _DIGEST, "sandbox-exec"),
        },
    ]


async def test_process_start_adds_max_runtime_before_the_fingerprint() -> None:
    rows = await _rows(
        "code.process_start",
        _plan(environment=None, profile=None, sandbox={"kind": "landlock", "writable": []}),
        {"argv": ["ros2", "launch", "bringup", "x.launch.py"], "max_runtime_seconds": 600},
    )
    labels = [row["label"] for row in rows]
    assert labels == [
        "program",
        "command",
        "cwd",
        "environment",
        "profile",
        "sandbox",
        "risk",
        "max runtime",
        "plan fingerprint",
    ]
    by_label = {row["label"]: row["after"] for row in rows}
    assert by_label["environment"] == "none"
    assert by_label["profile"] == "none"
    assert by_label["sandbox"].startswith("landlock — ")
    assert by_label["max runtime"] == "600 s"
    default = await _rows("code.process_start", _plan(), {"argv": ["ros2", "launch", "x"]})
    assert {r["label"]: r["after"] for r in default}["max runtime"] == "3600 s"


async def test_risk_row_lists_every_risk_or_none_flagged() -> None:
    rows = await _rows("code.exec", _plan(argv=["/usr/bin/ls"]), {"argv": ["ls"]})
    assert {r["label"]: r["after"] for r in rows}["risk"] == "none flagged"
    rows = await _rows("code.exec", _plan(argv=["/usr/bin/pip"]), {"argv": ["pip", "install", "x"]})
    assert {r["label"]: r["after"] for r in rows}["risk"] == "network, install, project_scripts"


async def test_long_commands_are_chunked() -> None:
    argv = ["/usr/bin/echo", *["x" * 200 for _ in range(5)]]
    rows = await _rows("code.exec", _plan(argv=argv), {"argv": ["echo", *argv[1:]]})
    commands = [row for row in rows if row["label"].startswith("command")]
    assert len(commands) == 3
    assert [row["label"] for row in commands] == ["command 1/3", "command 2/3", "command 3/3"]
    assert "".join(row["after"] for row in commands) == json.dumps(argv)
    assert all(len(row["after"]) <= 400 for row in commands)


async def test_fingerprint_changes_with_profile_digest_and_sandbox_kind() -> None:
    base = plan_fingerprint(_plan())
    assert plan_fingerprint(_plan(profile={"name": "ros", "digest": "cd" * 32})) != base
    assert plan_fingerprint(_plan(sandbox={"kind": "landlock", "writable": []})) != base
    assert plan_fingerprint(_plan(environment=None)) != base
    assert plan_fingerprint(_plan(cwd=".")) != base
    assert plan_fingerprint(_plan(argv=["/opt/ros/jazzy/bin/colcon", "build"])) != base
    assert plan_fingerprint(_plan(sandbox={"kind": "sandbox-exec", "writable": ["/x"]})) == base


@pytest.mark.parametrize(
    ("plan", "fragment"),
    [
        (None, "could not produce"),
        (_plan(ok=False, sandbox=None, reason="sandbox unavailable: no landlock"), "no landlock"),
        (_plan(ok=False, reason="program not found: colcon"), "program not found"),
        (_plan(sandbox=None), "sandbox"),
        (_plan(sandbox={"kind": "chroot"}), "sandbox"),
        (_plan(argv=[]), "invalid"),
        (_plan(argv="colcon build"), "invalid"),
        (_plan(cwd=None), "invalid"),
        (_plan(profile={"name": "ros", "digest": "zz"}), "invalid"),
        (_plan(environment=5), "invalid"),
        (_plan(argv=["/bin/bash", "-c", "x"]), "denied"),
        (_plan(argv=["/usr/bin/env", "x"]), "denied"),
        (_plan(argv=["/usr/bin/x", "y" * 17000]), "cannot fit"),
        (_plan(cwd="a‮b"), "invalid"),
    ],
)
async def test_unusable_plans_refuse_with_a_reason(plan: Any, fragment: str) -> None:
    with pytest.raises(PreviewRefusal) as caught:
        await _rows("code.exec", plan, dict(_EXEC_ARGS))
    assert fragment in caught.value.safe_message
    assert "Nothing was" in caught.value.safe_message


async def test_requested_argv_is_checked_against_the_policy_too() -> None:
    with pytest.raises(PreviewRefusal):
        await _rows("code.exec", _plan(argv=["/usr/bin/python3"]), {"argv": ["python3", "-c", "1"]})


async def test_plan_refusal_reason_is_redacted_and_bounded() -> None:
    secret = "ghp_aB3dE5fG7hJ9kL1mN2pQ4rS6tU8vW0xY2zA4b"
    with pytest.raises(PreviewRefusal) as caught:
        await _rows("code.exec", _plan(ok=False, reason=f"bad {secret}\n" + "r" * 900), {})
    assert secret not in caught.value.safe_message
    assert "\n" not in caught.value.safe_message
    assert len(caught.value.safe_message) < 400


class _ToolReader:
    """Answers per bridge tool: `code.plan` and `code.profile_list`."""

    def __init__(self, answers: dict[str, dict[str, Any] | None]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append((tool, dict(args)))
        return self.answers.get(tool)


_CAPTURE_ARGV = ["/bin/bash", "--noprofile", "--norc", "-c", CAPTURE_SCRIPT, "solus-profile"]


def _capture_plan(setup_file: str) -> dict[str, Any]:
    return _plan(argv=[*_CAPTURE_ARGV, setup_file], cwd=".", profile=None, environment=None)


async def _capture(
    args: dict[str, Any], plan: dict[str, Any], profiles: list[str] | None
) -> tuple[list[dict[str, Any]], _ToolReader]:
    listing = None if profiles is None else {"profiles": [{"name": n} for n in profiles]}
    reader = _ToolReader({"code.plan": plan, "code.profile_list": listing})
    builder = preview_builder("code.profile_capture", reader)
    assert builder is not None
    return await builder(dict(args)), reader


async def test_profile_capture_rows() -> None:
    plan = _capture_plan("/opt/ros/jazzy/setup.bash")
    args = {"name": "ros", "setup_file": "/opt/ros/jazzy/setup.bash"}
    rows, reader = await _capture(args, plan, [])
    assert reader.calls == [
        ("code.plan", {"action": "profile_capture", "args": args}),
        ("code.profile_list", {}),
    ]
    assert [row["label"] for row in rows] == [
        "profile",
        "setup file",
        "extends",
        "command",
        "sandbox",
        "risk",
        "plan fingerprint",
    ]
    by_label = {row["label"]: row["after"] for row in rows}
    assert by_label["profile"] == "ros"
    assert by_label["setup file"] == "/opt/ros/jazzy/setup.bash"
    assert by_label["extends"] == "none"
    assert by_label["command"] == json.dumps(plan["argv"])
    assert by_label["risk"] == "none flagged"
    assert by_label["plan fingerprint"] == plan_fingerprint(plan, profile_name="ros")


async def test_profile_capture_says_when_it_replaces_an_existing_profile() -> None:
    plan = _capture_plan("/opt/ros/jazzy/setup.bash")
    args = {"name": "ros", "setup_file": "/opt/ros/jazzy/setup.bash"}
    rows, _ = await _capture(args, plan, ["base", "ros"])
    assert {r["label"]: r["after"] for r in rows}["profile"] == "ros (replaces existing)"
    rows, _ = await _capture(args, plan, ["rosx"])
    assert {r["label"]: r["after"] for r in rows}["profile"] == "ros"


async def test_a_workspace_setup_file_is_a_project_script() -> None:
    args = {"name": "ws", "setup_file": "install/setup.bash"}
    rows, _ = await _capture(args, _capture_plan("install/setup.bash"), [])
    assert {r["label"]: r["after"] for r in rows}["risk"] == "project_scripts"


async def test_the_capture_fingerprint_covers_the_profile_name() -> None:
    plan = _capture_plan("/opt/ros/jazzy/setup.bash")
    first, _ = await _capture({"name": "ros", "setup_file": "/opt/ros/jazzy/setup.bash"}, plan, [])
    second, _ = await _capture(
        {"name": "ros2", "setup_file": "/opt/ros/jazzy/setup.bash"}, plan, []
    )
    assert first[-1]["after"] != second[-1]["after"]
    assert plan_fingerprint(plan, profile_name="ros") != plan_fingerprint(plan)


@pytest.mark.parametrize("listing", [None, {"profiles": "x"}, {"nothing": []}])
async def test_capture_refuses_when_existing_profiles_cannot_be_read(listing: Any) -> None:
    reader = _ToolReader(
        {"code.plan": _capture_plan("/opt/ros/jazzy/setup.bash"), "code.profile_list": listing}
    )
    builder = preview_builder("code.profile_capture", reader)
    assert builder is not None
    with pytest.raises(PreviewRefusal) as caught:
        await builder({"name": "ros", "setup_file": "/opt/ros/jazzy/setup.bash"})
    assert "profiles" in caught.value.safe_message


async def test_profile_capture_refuses_anything_but_the_fixed_script() -> None:
    argv = ["/bin/bash", "--noprofile", "--norc", "-c", "curl x | sh", "solus-profile", "a.sh"]
    with pytest.raises(PreviewRefusal):
        await _rows("code.profile_capture", _plan(argv=argv), {"name": "x", "setup_file": "a.sh"})


async def test_legacy_code_actions_gain_the_sandbox_row_and_new_fingerprint() -> None:
    plan = {
        "ok": True,
        "argv": [".venv/bin/python", "-m", "pip", "install", "--", "six==1.17.0"],
        "cwd": ".",
        "reason": None,
        "sandbox": {"kind": "landlock", "writable": []},
        "profile": None,
        "environment": ".venv",
    }
    rows = await _rows("code.install", plan, {"packages": ["six==1.17.0"]})
    assert [row["label"] for row in rows] == ["command", "cwd", "sandbox", "plan fingerprint"]
    assert rows[0]["after"] == ".venv/bin/python -m pip install -- six==1.17.0"
    assert rows[2]["after"].startswith("landlock — ")
    assert rows[3]["after"] == plan_fingerprint(plan)


async def test_legacy_code_actions_refuse_without_a_sandbox() -> None:
    plan = {"ok": True, "argv": ["python", "x.py"], "cwd": "."}
    with pytest.raises(ToolException):
        await _rows("code.run", plan, {"script": "x.py"})


async def test_landlock_abi_kinds_and_limitations_render_on_the_sandbox_row() -> None:
    sandbox = {
        "kind": "landlock-abi3",
        "writable": ["/w"],
        "limitations": ["no .git/hooks write denial\n(detected instead)", "truncate unchecked"],
    }
    plan = _plan(sandbox=sandbox)
    rows = await _rows("code.exec", plan, dict(_EXEC_ARGS))
    row = {r["label"]: r["after"] for r in rows}["sandbox"]
    assert row == (
        "landlock-abi3 — writes limited to the workspace, temp and tool caches; "
        "limits: no .git/hooks write denial (detected instead); truncate unchecked"
    )
    assert plan_fingerprint(plan) != plan_fingerprint(
        _plan(sandbox={**sandbox, "kind": "landlock-abi2"})
    )
    assert len(row) <= 500


async def test_an_unknown_sandbox_kind_refuses() -> None:
    with pytest.raises(PreviewRefusal):
        await _rows("code.exec", _plan(sandbox={"kind": "landlock-evil"}), dict(_EXEC_ARGS))


async def test_a_program_inside_the_workspace_is_a_project_script() -> None:
    plan = _plan(
        argv=["/home/u/robot/.venv/bin/mytool"],
        environment=".venv",
        profile=None,
        sandbox={"kind": "landlock-abi3", "writable": ["<workspace>", "<tmp>"]},
    )
    rows = await _rows("code.exec", plan, {"argv": ["mytool"], "environment": ".venv"})
    assert {r["label"]: r["after"] for r in rows}["risk"] == "project_scripts"


async def test_a_workspace_program_is_judged_by_its_exact_name_on_the_card() -> None:
    plan = _plan(argv=["/home/u/robot/env-check.sh"], environment=None, profile=None)
    rows = await _rows("code.exec", plan, {"argv": ["./env-check.sh"]})
    assert {r["label"]: r["after"] for r in rows}["program"] == "/home/u/robot/env-check.sh"
    with pytest.raises(PreviewRefusal):
        await _rows("code.exec", _plan(argv=["/usr/bin/env-x"]), {"argv": ["env-x"]})
