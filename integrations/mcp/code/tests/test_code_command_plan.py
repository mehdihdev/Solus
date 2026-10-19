"""SOLUSDEV-317 — planning `exec`, `process_start` and `profile_capture`
(docs/api/code-command-execution.md §2.1–2.4): argv validation, program
resolution order (never the inherited PATH), the deny table on the proposed AND
resolved program, profiles, the sandbox/profile/environment answer fields for
every action, and refusal when no sandbox is available."""

import os
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip
from sandbox_fixture import FAKE_KIND  # isort: skip
from venv_fixture import fake_venv  # isort: skip

plan = overlay_module("plan")
command_plan = overlay_module("command_plan")
profiles = overlay_module("profiles")
sandbox = overlay_module("sandbox")
execute = overlay_module("execute")


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "ws").mkdir()
    root = (tmp_path / "ws").resolve()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bins = tmp_path / "roots" / "bin"
    bins.mkdir(parents=True)
    for name in ("colcon", "make", "bash", "python3.12"):
        _executable(bins / name)
    monkeypatch.setattr(execute, "SEARCH_ROOTS", (str(bins),))
    return root


def _executable(path: Path, body: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _plan(root: Path, action: str, args: Any) -> Any:
    return plan.plan_action(root, action, args, which=lambda _name: None)


def test_bare_names_resolve_against_the_pinned_roots_never_path(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evil = tmp_path / "evil"
    _executable(evil / "colcon")
    monkeypatch.setenv("PATH", str(evil))
    result = _plan(ws, "exec", {"argv": ["colcon", "build", "--symlink-install"]})
    assert result.ok, result.reason
    assert result.argv == [str(tmp_path / "roots" / "bin" / "colcon"), "build", "--symlink-install"]
    assert result.timeout_seconds == 120 and result.cwd == "."
    assert not _plan(ws, "exec", {"argv": ["nope"]}).ok


def test_answer_carries_sandbox_profile_and_environment(ws: Path) -> None:
    answer = _plan(ws, "exec", {"argv": ["make"]}).answer()
    assert answer["sandbox"] == {
        "kind": FAKE_KIND,
        "writable": list(sandbox.WRITABLE_LABELS),
        "limitations": sandbox.limitations(FAKE_KIND),
    }
    assert answer["profile"] is None and answer["environment"] is None
    assert answer["ok"] is True and answer["reason"] is None and answer["cwd"] == "."


def test_every_old_action_answers_the_new_fields(ws: Path) -> None:
    fake_venv(ws)
    (ws / "a.py").write_text("")
    answer = _plan(ws, "run", {"script": "a.py"}).answer()
    assert set(answer) == {
        "argv",
        "cwd",
        "ok",
        "reason",
        "sandbox",
        "profile",
        "environment",
        "program_scope",
    }
    assert answer["sandbox"]["kind"] == FAKE_KIND and answer["environment"] == ".venv"
    refused = _plan(ws, "run", {"script": "../x"}).answer()
    assert refused["sandbox"] is None and refused["ok"] is False


def test_no_sandbox_refuses_every_action(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "available", lambda: (None, "unsupported platform: win32"))
    fake_venv(ws)
    (ws / "a.py").write_text("")
    for action, args in (("exec", {"argv": ["make"]}), ("run", {"script": "a.py"})):
        result = _plan(ws, action, args)
        assert not result.ok and result.reason == "sandbox unavailable: unsupported platform: win32"
        assert result.answer()["sandbox"] is None


def test_workspace_relative_programs(ws: Path, tmp_path: Path) -> None:
    script = _executable(ws / "scripts" / "build.sh")
    result = _plan(ws, "exec", {"argv": ["./scripts/build.sh", "-v"]})
    assert result.ok and result.argv == [str(script), "-v"]
    (ws / "scripts" / "data.txt").write_text("")
    assert not _plan(ws, "exec", {"argv": ["scripts/data.txt"]}).ok  # not executable
    outside = _executable(tmp_path / "outside.sh")
    (ws / "link.sh").symlink_to(outside)
    assert not _plan(ws, "exec", {"argv": ["link.sh"]}).ok  # bare, not in roots
    assert not _plan(ws, "exec", {"argv": ["./link.sh"]}).ok  # escapes the workspace
    assert not _plan(ws, "exec", {"argv": ["../outside.sh"]}).ok


def test_absolute_programs_must_sit_directly_in_an_allowed_root(ws: Path, tmp_path: Path) -> None:
    colcon = str(tmp_path / "roots" / "bin" / "colcon")
    assert _plan(ws, "exec", {"argv": [colcon]}).argv[0] == colcon
    other = _executable(tmp_path / "elsewhere" / "tool")
    assert not _plan(ws, "exec", {"argv": [str(other)]}).ok
    nested = _executable(tmp_path / "roots" / "bin" / "sub" / "tool")
    assert not _plan(ws, "exec", {"argv": [str(nested)]}).ok


def test_environment_bin_comes_first(ws: Path) -> None:
    fake_venv(ws)
    venv_make = _executable(ws / ".venv" / "bin" / "make")
    result = _plan(ws, "exec", {"argv": ["make"], "environment": ".venv"})
    assert result.ok and result.argv[0] == str(venv_make) and result.environment == ".venv"
    assert not _plan(ws, "exec", {"argv": ["make"], "environment": "missing"}).ok
    (ws / "fake").mkdir()
    assert not _plan(ws, "exec", {"argv": ["make"], "environment": "fake"}).ok


def test_profile_path_entries_resolve_before_search_roots(ws: Path, tmp_path: Path) -> None:
    ros_bin = tmp_path / "opt" / "ros" / "bin"
    ros_colcon = _executable(ros_bin / "colcon")
    saved = profiles.save(
        ws, "ros", "/opt/ros/jazzy/setup.bash", None, {"PATH": f"relative:{ros_bin}:/missing"}
    )
    result = _plan(ws, "exec", {"argv": ["colcon"], "profile": "ros"})
    assert result.ok and result.argv[0] == str(ros_colcon)
    assert result.answer()["profile"] == {"name": "ros", "digest": saved.digest}
    assert dict(result.profile.variables)["PATH"].startswith("relative:")
    assert _plan(ws, "exec", {"argv": [str(ros_colcon)], "profile": "ros"}).ok
    missing = _plan(ws, "exec", {"argv": ["colcon"], "profile": "nope"})
    assert not missing.ok and "no profile" in missing.reason


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-c", "ls"],
        ["python3.12", "-c", "1"],
        ["sudo", "make"],
        ["git", "status"],
    ],
)
def test_denied_programs_are_refused_by_the_planner(ws: Path, argv: list[str]) -> None:
    result = _plan(ws, "exec", {"argv": argv})
    assert not result.ok and "no shell" in result.reason


def test_resolved_realpath_is_checked_against_the_deny_table(ws: Path, tmp_path: Path) -> None:
    roots = tmp_path / "roots" / "bin"
    os.symlink(roots / "bash", roots / "innocent")
    result = _plan(ws, "exec", {"argv": ["innocent", "-c", "ls"]})
    assert not result.ok and "bash" in result.reason
    os.symlink(roots / "bash", ws / "build")
    os.chmod(ws / "build", 0o755)
    assert not _plan(ws, "exec", {"argv": ["./build"]}).ok


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"argv": []},
        {"argv": "make"},
        {"argv": [""]},
        {"argv": ["make", "a\nb"]},
        {"argv": ["make", "a\rb"]},
        {"argv": ["make", "a\x00b"]},
        {"argv": ["make", "x" * 1025]},
        {"argv": ["make"] * 65},
        {"argv": ["make", 3]},
        {"argv": ["make"], "cwd": "../x"},
        {"argv": ["make"], "cwd": "missing"},
        {"argv": ["make"], "timeout_seconds": 0},
        {"argv": ["make"], "timeout_seconds": 601},
        {"argv": ["make"], "timeout_seconds": True},
        {"argv": ["make"], "profile": "Bad Name"},
        {"argv": ["make"], "unexpected": 1},
    ],
)
def test_exec_refuses_bad_arguments(ws: Path, args: dict[str, Any]) -> None:
    result = _plan(ws, "exec", args)
    assert not result.ok and result.reason and result.argv == []


def test_cwd_is_a_workspace_directory(ws: Path) -> None:
    (ws / "ros_ws").mkdir()
    result = _plan(ws, "exec", {"argv": ["colcon"], "cwd": "ros_ws", "timeout_seconds": 300})
    assert result.ok and result.cwd == "ros_ws" and result.timeout_seconds == 300
    assert result.answer()["cwd"] == "ros_ws"


def test_process_start_plan(ws: Path) -> None:
    result = _plan(ws, "process_start", {"argv": ["make", "run"], "name": "bringup"})
    assert result.ok and result.label == "bringup" and result.max_runtime_seconds == 3600
    custom = _plan(ws, "process_start", {"argv": ["make"], "max_runtime_seconds": 60})
    assert custom.ok and custom.max_runtime_seconds == 60
    for bad in (
        {"argv": ["make"], "timeout_seconds": 5},
        {"argv": ["make"], "max_runtime_seconds": 59},
        {"argv": ["make"], "max_runtime_seconds": 14401},
        {"argv": ["make"], "name": ""},
        {"argv": ["make"], "name": "x" * 65},
        {"argv": ["make"], "name": "bad\nname"},
        {"argv": ["bash"]},
    ):
        assert not _plan(ws, "process_start", bad).ok, bad


def test_profile_capture_plan(ws: Path) -> None:
    (ws / "install").mkdir()
    (ws / "install" / "setup.bash").write_text("export A=1\n")
    result = _plan(ws, "profile_capture", {"name": "ws", "setup_file": "install/setup.bash"})
    assert result.ok, result.reason
    setup = str(ws / "install" / "setup.bash")
    assert result.argv == profiles.capture_argv(setup)
    assert result.timeout_seconds == 30 and result.capture_name == "ws"
    assert result.setup_file == setup and result.profile is None
    profiles.save(ws, "ros", "/opt/ros/x.bash", None, {"A": "1"})
    extended = _plan(
        ws, "profile_capture", {"name": "ws", "setup_file": "install/setup.bash", "extends": "ros"}
    )
    assert extended.ok and extended.profile.name == "ros"
    for bad in (
        {"name": "ws", "setup_file": "missing.bash"},
        {"name": "BAD", "setup_file": "install/setup.bash"},
        {"name": "ws", "setup_file": "install/setup.bash", "extends": "nope"},
        {"name": "ws", "setup_file": "/etc/profile"},
        {"name": "ws", "setup_file": "install/setup.bash", "argv": ["x"]},
    ):
        assert not _plan(ws, "profile_capture", bad).ok, bad


def test_unknown_action_lists_the_new_actions(ws: Path) -> None:
    reason = _plan(ws, "shell", {}).reason
    for action in ("exec", "process_start", "profile_capture"):
        assert action in reason


@pytest.mark.real_writable_roots
def test_profile_path_into_tmp_never_resolves_a_program(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9.5: a program planted in TMP (or a cache) by an earlier command is never run,
    however it is reached: a profile PATH entry, an absolute path, or a pinned root."""
    planted = _executable(tmp_path / "scratch" / "planted-tool")
    roots = [str(planted.parent)]
    assert plan.plan_action  # the planner and its resolver share the rule
    command_plan = overlay_module("command_plan")
    assert command_plan.resolve_program(ws, "planted-tool", roots) is None
    assert command_plan.resolve_program(ws, str(planted), roots) is None
    inside = _executable(ws / "bin" / "tool")
    assert command_plan.resolve_program(ws, "bin/tool", roots) == str(inside)


def test_workspace_link_to_an_outside_shell_variant_is_refused(ws: Path, tmp_path: Path) -> None:
    # A workspace symlink whose target is a versioned shell outside the workspace is
    # judged by the target's name, fail-closed (`bash-5.2` → bash).
    outside = tmp_path / "outside-bin"
    outside.mkdir()
    shell = _executable(outside / "bash-5.2")
    (ws / "tools").mkdir(exist_ok=True)
    (ws / "tools" / "x").symlink_to(shell)
    answer = plan.plan_action(ws, "exec", {"argv": ["./tools/x"]}, which=lambda _n: None)
    assert answer.ok is False


def test_within_compares_by_inode(ws: Path, tmp_path: Path) -> None:
    (ws / "sub").mkdir(exist_ok=True)
    assert command_plan._within(ws, str(ws / "sub"))
    assert not command_plan._within(ws, str(tmp_path))


# --- §10.1 item 2: program_scope -----------------------------------------------------


def _scope(root: Path, action: str, args: Any, which: Any = lambda _name: None) -> Any:
    answer = plan.plan_action(root, action, args, which=which).answer()
    assert answer["ok"], answer["reason"]
    return answer["program_scope"]


def test_a_bare_system_program_is_system_scope(ws: Path, tmp_path: Path) -> None:
    assert _scope(ws, "exec", {"argv": ["make"]}) == "system"
    absolute = str(tmp_path / "roots" / "bin" / "colcon")
    assert _scope(ws, "process_start", {"argv": [absolute]}) == "system"


def test_a_workspace_script_is_workspace_scope(ws: Path) -> None:
    _executable(ws / "scripts" / "build.sh")
    assert _scope(ws, "exec", {"argv": ["./scripts/build.sh"]}) == "workspace"
    assert _scope(ws, "process_start", {"argv": ["scripts/build.sh"]}) == "workspace"


def test_venv_binaries_and_interpreters_are_workspace_scope(ws: Path) -> None:
    fake_venv(ws)  # bin/python links to an interpreter OUTSIDE the workspace
    _executable(ws / ".venv" / "bin" / "pytest")
    for program in ("pytest", "python"):
        scope = _scope(ws, "exec", {"argv": [program], "environment": ".venv"})
        assert scope == "workspace", program


def test_a_profile_path_entry_under_the_workspace_is_workspace_scope(ws: Path) -> None:
    tool = _executable(ws / "install" / "bin" / "talker")
    profiles.save(ws, "ws", "/x/setup.bash", None, {"PATH": str(tool.parent)})
    assert _scope(ws, "exec", {"argv": ["talker"], "profile": "ws"}) == "workspace"


def test_a_workspace_link_to_an_outside_program_is_system_scope(ws: Path, tmp_path: Path) -> None:
    bin_dir = ws / "install" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "colcon").symlink_to(tmp_path / "roots" / "bin" / "colcon")
    profiles.save(ws, "ws", "/x/setup.bash", None, {"PATH": str(bin_dir)})
    assert _scope(ws, "exec", {"argv": ["colcon"], "profile": "ws"}) == "system"
    # ...and its target's name is still checked fail-closed.
    outside = _executable(tmp_path / "outside-bin" / "bash-5.2")
    (bin_dir / "helper").symlink_to(outside)
    assert not _plan(ws, "exec", {"argv": ["helper", "x.sh"], "profile": "ws"}).ok


def test_old_actions_answer_program_scope(ws: Path) -> None:
    fake_venv(ws)
    (ws / "a.py").write_text("")
    (ws / "tests").mkdir()
    (ws / "install").mkdir()
    (ws / "install" / "setup.bash").write_text("export A=1\n")
    uv = lambda name: "/usr/bin/uv" if name == "uv" else None  # noqa: E731
    assert _scope(ws, "run", {"script": "a.py"}) == "workspace"
    assert _scope(ws, "test", {}) == "workspace"
    assert _scope(ws, "install", {"packages": ["numpy"]}) == "workspace"  # venv pip
    assert _scope(ws, "install", {"packages": ["numpy"]}, uv) == "system"
    assert _scope(ws, "create_environment", {"path": "env2"}, uv) == "system"
    capture = {"name": "ws", "setup_file": "install/setup.bash"}
    assert _scope(ws, "profile_capture", capture) == "system"


def test_refusals_answer_a_null_program_scope(ws: Path) -> None:
    for action, args in (("exec", {"argv": ["nope"]}), ("run", {"script": "../x"}), ("x", {})):
        answer = _plan(ws, action, args).answer()
        assert answer["ok"] is False and answer["program_scope"] is None


# --- §10.2: bash/sh workspace scripts ------------------------------------------------


def test_bash_runs_an_existing_workspace_script(ws: Path, tmp_path: Path) -> None:
    (ws / "scripts").mkdir()
    (ws / "scripts" / "build.sh").write_text("echo hi\n")  # need not be executable
    result = _plan(ws, "exec", {"argv": ["bash", "scripts/build.sh", "a", "b"]})
    assert result.ok, result.reason
    assert result.argv == [str(tmp_path / "roots" / "bin" / "bash"), "scripts/build.sh", "a", "b"]
    assert result.answer()["program_scope"] == "system"


def test_sh_resolves_the_script_from_the_cwd(ws: Path, tmp_path: Path) -> None:
    _executable(tmp_path / "roots" / "bin" / "sh")
    (ws / "sub").mkdir()
    (ws / "sub" / "x.sh").write_text("echo hi\n")
    assert _plan(ws, "exec", {"argv": ["sh", "./x.sh"], "cwd": "sub"}).ok
    assert not _plan(ws, "exec", {"argv": ["sh", "./x.sh"]}).ok  # not at the root
    assert _plan(ws, "process_start", {"argv": ["sh", "sub/x.sh"]}).ok


def test_the_script_must_be_a_regular_file_inside_the_workspace(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.sh"
    outside.write_text("echo out\n")
    (ws / "link.sh").symlink_to(outside)
    (ws / "dir.sh").mkdir()
    for script in ("missing.sh", "link.sh", "dir.sh"):
        result = _plan(ws, "exec", {"argv": ["bash", script]})
        assert not result.ok, script
        assert result.reason == (
            "script must be an existing .sh/.bash file inside the linked folder"
        )


@pytest.mark.parametrize(
    "argv",
    [["bash", "-c", "x"], ["bash", "-x", "s.sh"], ["bash", "s.py"], ["bash"], ["sh", "-s"]],
)
def test_other_shell_forms_are_refused_by_the_planner(ws: Path, argv: list[str]) -> None:
    (ws / "s.sh").write_text("")
    (ws / "s.py").write_text("")
    assert not _plan(ws, "exec", {"argv": argv}).ok
