"""SOLUSDEV-250 — `plan` (docs/api/code-environment.md §4): the exact argv
per action with and without uv, every refusal (option-shaped packages, URLs,
paths, whitespace, escapes, bad versions, timeouts over the cap), purity
(nothing executed or created), and no absolute path in any argv."""

import os
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from venv_fixture import fake_venv  # isort: skip

plan = overlay_module("plan")

UV_ONLY = {"uv": "/opt/homebrew/bin/uv"}
PY311_ONLY = {"python3.11": "/usr/local/bin/python3.11"}


def _which(available: dict[str, str]) -> Any:
    return lambda name: available.get(name)


def _venv(root: Path, name: str = ".venv") -> Path:
    return fake_venv(root, name)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    _venv(tmp_path)
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "train.py").write_text("print(1)\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "empty-env").mkdir()
    return tmp_path


def _plan(root: Path, action: object, args: object, available: dict[str, str] | None = None) -> Any:
    return plan.plan_action(root, action, args, which=_which(available or {}))


# --- create_environment ------------------------------------------------------------


def test_create_prefers_uv(ws: Path) -> None:
    result = _plan(ws, "create_environment", {"path": "env2", "python": "3.11"}, UV_ONLY)
    assert result.ok and result.argv == ["uv", "venv", "--python", "3.11", "env2"]
    assert result.path == "env2" and result.environment == "env2"
    assert result.answer() == {"argv": result.argv, "cwd": ".", "ok": True, "reason": None}
    assert not (ws / "env2").exists(), "plan must be pure"


def test_create_falls_back_to_the_versioned_interpreter(ws: Path) -> None:
    result = _plan(ws, "create_environment", {"path": "env2", "python": "3.11"}, PY311_ONLY)
    assert result.argv == ["python3.11", "-m", "venv", "env2"]


def test_create_defaults_and_nested_target(ws: Path) -> None:
    result = _plan(ws, "create_environment", {"path": "policy/.venv"}, UV_ONLY)
    assert result.argv == ["uv", "venv", "--python", "3.12", "policy/.venv"]
    assert _plan(ws, "create_environment", None, UV_ONLY).reason == ".venv already exists"


def test_create_refuses_when_neither_uv_nor_the_interpreter_exists(ws: Path) -> None:
    result = _plan(ws, "create_environment", {"path": "env2", "python": "3.9"}, PY311_ONLY)
    assert not result.ok and "python 3.9 is not installed" in result.reason


@pytest.mark.parametrize("python", ["3", "3.x", "2.7", "3.12.1", "v3.12", "3.12;rm", "", 312, None])
def test_create_refuses_bad_versions(ws: Path, python: object) -> None:
    result = _plan(ws, "create_environment", {"path": "env2", "python": python}, UV_ONLY)
    assert not result.ok and result.reason == "python must be a 3.X version"


@pytest.mark.parametrize(
    "path", ["/tmp/x", "../x", "-x", "", ".", "a/../x", "C:\\x", "x\\y", "a\nb", "x\x00", 42]
)
def test_create_refuses_unsafe_paths(ws: Path, path: object) -> None:
    result = _plan(ws, "create_environment", {"path": path}, UV_ONLY)
    assert (
        not result.ok and result.reason == "path must be a relative path inside the linked folder"
    )


def test_create_refuses_existing_missing_parent_and_symlink(ws: Path) -> None:
    assert (
        _plan(ws, "create_environment", {"path": "policy"}, UV_ONLY).reason
        == "policy already exists"
    )
    os.symlink("/nonexistent-target", ws / "dangling")
    assert (
        _plan(ws, "create_environment", {"path": "dangling"}, UV_ONLY).reason
        == "dangling already exists"
    )
    result = _plan(ws, "create_environment", {"path": "nope/env"}, UV_ONLY)
    assert result.reason == "path must be inside an existing folder of the linked folder"
    outside = ws.parent / "outside-dir"
    outside.mkdir()
    os.symlink(outside, ws / "escape")
    assert not _plan(ws, "create_environment", {"path": "escape/env"}, UV_ONLY).ok


# --- install -------------------------------------------------------------------------


def test_install_with_uv_and_with_pip(ws: Path) -> None:
    packages = ["torch==2.1.0", "numpy", "requests[socks]>=2.31,<3"]
    with_uv = _plan(ws, "install", {"packages": packages}, UV_ONLY)
    assert with_uv.ok and with_uv.argv == [
        "uv",
        "pip",
        "install",
        "--python",
        ".venv/bin/python",
        "--",
        *packages,
    ]
    with_pip = _plan(ws, "install", {"packages": packages})
    assert with_pip.argv == [".venv/bin/python", "-m", "pip", "install", "--", *packages]
    assert with_pip.environment == ".venv" and with_pip.timeout_seconds == 600


def test_install_uses_the_named_environment(ws: Path) -> None:
    _venv(ws, "venv-gpu")
    result = _plan(ws, "install", {"packages": ["numpy"], "environment": "venv-gpu"})
    assert result.argv[0] == "venv-gpu/bin/python" and result.environment == "venv-gpu"


@pytest.mark.parametrize(
    "item",
    [
        "-e",
        "--index-url=https://evil",
        "-r requirements.txt",
        "https://evil/x.whl",
        "git+https://github.com/x/y",
        "./local",
        "/etc/passwd",
        "..\\x",
        "torch ==2.1",
        "torch\t==2.1",
        "",
        "name==",
        "name @ https://x",
        "name;rm",
        "name$(id)",
        "a" * 129,
        "name[extra",
        "==1.0",
        42,
    ],
)
def test_install_refuses_option_url_path_and_malformed_packages(ws: Path, item: object) -> None:
    result = _plan(ws, "install", {"packages": ["numpy", item]}, UV_ONLY)
    assert not result.ok and result.reason and result.argv == []


def test_install_refuses_bad_lists(ws: Path) -> None:
    assert _plan(ws, "install", {"packages": []}).reason == "packages must be a non-empty list"
    assert _plan(ws, "install", {"packages": "numpy"}).reason == "packages must be a non-empty list"
    assert _plan(ws, "install", {}).reason == "packages must be a non-empty list"
    too_many = _plan(ws, "install", {"packages": [f"p{i}" for i in range(65)]})
    assert too_many.reason == "at most 64 packages per install"
    assert _plan(ws, "install", {"packages": [f"p{i}" for i in range(64)]}).ok


def test_install_echoes_a_bounded_slice_of_the_offender(ws: Path) -> None:
    result = _plan(ws, "install", {"packages": ["-" + "x" * 500]})
    assert len(result.reason) < 64 + 40


@pytest.mark.parametrize("environment", ["missing", "../x", "/abs", "empty-env", "-x", 7, ""])
def test_install_refuses_unusable_environments(ws: Path, environment: object) -> None:
    result = _plan(ws, "install", {"packages": ["numpy"], "environment": environment})
    assert not result.ok and result.reason


def test_install_refuses_a_venv_symlinked_outside(ws: Path) -> None:
    outside = ws.parent / "outside-venv"
    (outside / "bin").mkdir(parents=True)
    (outside / "bin" / "python").write_text("")
    os.symlink(outside, ws / "linked")
    result = _plan(ws, "install", {"packages": ["numpy"], "environment": "linked"})
    assert not result.ok and "no virtualenv found at linked" in result.reason


def test_windows_layout_venv_is_recognised(ws: Path) -> None:
    scripts = ws / "wenv" / "Scripts"
    scripts.mkdir(parents=True)
    (ws / "wenv" / "pyvenv.cfg").write_text("home = C:\\Python312\n")
    base = ws.parent / f"{ws.name}.interp-wenv"
    base.mkdir(exist_ok=True)
    (base / "python.exe").write_text("")
    os.symlink(base / "python.exe", scripts / "python.exe")
    result = _plan(ws, "install", {"packages": ["numpy"], "environment": "wenv"})
    assert result.argv[0] == "wenv/Scripts/python.exe"


# --- run -----------------------------------------------------------------------------


def test_run_argv_timeout_and_defaults(ws: Path) -> None:
    result = _plan(
        ws, "run", {"script": "policy/train.py", "args": ["--epochs", "3"], "timeout_seconds": 30}
    )
    assert result.ok and result.argv == [".venv/bin/python", "policy/train.py", "--epochs", "3"]
    assert result.timeout_seconds == 30 and result.environment == ".venv"
    default = _plan(ws, "run", {"script": "policy/train.py"})
    assert (
        default.argv == [".venv/bin/python", "policy/train.py"] and default.timeout_seconds == 600
    )
    assert _plan(ws, "run", {"script": "policy/train.py", "args": None, "timeout_seconds": None}).ok


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ("-x.py", "script must be a relative path inside the linked folder"),
        ("../etc/passwd", "script must be a relative path inside the linked folder"),
        ("/etc/passwd", "script must be a relative path inside the linked folder"),
        ("", "script must be a relative path inside the linked folder"),
        (None, "script must be a relative path inside the linked folder"),
        ("policy", "script not found inside the linked folder: policy"),
        ("missing.py", "script not found inside the linked folder: missing.py"),
    ],
)
def test_run_refuses_bad_scripts(ws: Path, script: object, reason: str) -> None:
    result = _plan(ws, "run", {"script": script})
    assert not result.ok and result.reason == reason


def test_run_refuses_a_script_symlinked_outside(ws: Path) -> None:
    outside = ws.parent / "outside.py"
    outside.write_text("print(1)")
    os.symlink(outside, ws / "policy" / "link.py")
    assert not _plan(ws, "run", {"script": "policy/link.py"}).ok


@pytest.mark.parametrize("args", ["--flag", [1], ["a" * 257], ["a\nb"], ["a\x00"], ["x"] * 33])
def test_run_refuses_bad_args(ws: Path, args: object) -> None:
    result = _plan(ws, "run", {"script": "policy/train.py", "args": args})
    assert not result.ok and result.reason


@pytest.mark.parametrize("timeout", [0, 601, -1, "5", True, 5.5])
def test_run_refuses_bad_timeouts(ws: Path, timeout: object) -> None:
    result = _plan(ws, "run", {"script": "policy/train.py", "timeout_seconds": timeout})
    assert result.reason == "timeout_seconds must be an integer from 1 to 600"


def test_run_args_may_be_option_shaped_but_the_script_may_not(ws: Path) -> None:
    result = _plan(ws, "run", {"script": "policy/train.py", "args": ["-c", "--", "-"]})
    assert result.ok and result.argv[2:] == ["-c", "--", "-"]


# --- test ----------------------------------------------------------------------------


def test_test_argv_and_defaults(ws: Path) -> None:
    result = _plan(ws, "test", {})
    assert result.ok and result.argv == [".venv/bin/python", "-m", "pytest", "-q", "--", "tests"]
    single = _plan(ws, "test", {"target": "policy/train.py", "timeout_seconds": 120})
    assert single.argv[-1] == "policy/train.py" and single.timeout_seconds == 120


@pytest.mark.parametrize("target", ["missing", "../x", "/abs", "-k", "", 3])
def test_test_refuses_bad_targets(ws: Path, target: object) -> None:
    assert not _plan(ws, "test", {"target": target}).ok


def test_test_refuses_missing_environment_and_bad_timeout(ws: Path) -> None:
    assert "no virtualenv found at gone" in _plan(ws, "test", {"environment": "gone"}).reason
    assert not _plan(ws, "test", {"timeout_seconds": 10_000}).ok


# --- dispatch & invariants -------------------------------------------------------------


def test_unknown_action_and_bad_args_shape(ws: Path) -> None:
    result = _plan(ws, "shell", {})
    assert not result.ok and result.reason.startswith("unknown action")
    assert _plan(ws, "install", "packages").reason == "args must be an object"
    assert not _plan(ws, None, {}).ok
    assert len(_plan(ws, "x" * 500, {}).action) <= 64


def test_no_ok_argv_carries_an_absolute_path(ws: Path) -> None:
    plans = [
        _plan(ws, "create_environment", {"path": "env2"}, UV_ONLY),
        _plan(ws, "install", {"packages": ["numpy"]}, UV_ONLY),
        _plan(ws, "install", {"packages": ["numpy"]}),
        _plan(ws, "run", {"script": "policy/train.py"}),
        _plan(ws, "test", {}),
    ]
    for item in plans:
        assert item.ok, item.reason
        assert all(not part.startswith("/") and str(ws) not in part for part in item.argv)


def test_venv_python_helper(ws: Path) -> None:
    assert plan.venv_python(ws, ".venv") == ".venv/bin/python"
    assert plan.venv_python(ws, "policy") is None
    assert plan.venv_python(ws, "nope") is None
    assert plan.venv_python(ws, "../x") is None


def test_a_directory_with_a_planted_interpreter_is_not_a_venv(tmp_path: Path) -> None:
    """Security review C1/H2: workspace content that merely contains
    `bin/python` (a cloned repo can commit one) is never treated as a venv —
    no `pyvenv.cfg`, or an interpreter resolving INSIDE the workspace, refuses
    every action that would run it."""
    planted = tmp_path / "vendor" / "bin" / "python"
    planted.parent.mkdir(parents=True)
    planted.write_text("#!/bin/sh\ntouch pwned\n")
    planted.chmod(0o755)
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "train.py").write_text("print(1)\n")
    (tmp_path / "tests").mkdir()
    assert plan.venv_python(tmp_path, "vendor") is None
    (tmp_path / "vendor" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    assert plan.venv_python(tmp_path, "vendor") is None  # a marker alone is not enough
    for action, args in (
        ("install", {"packages": ["requests"], "environment": "vendor"}),
        ("run", {"script": "policy/train.py", "environment": "vendor"}),
        ("test", {"environment": "vendor"}),
    ):
        result = _plan(tmp_path, action, args)
        assert not result.ok and "no virtualenv found" in (result.reason or ""), action
    # A venv whose interpreter links outside the workspace is accepted.
    fake_venv(tmp_path, "real")
    assert plan.venv_python(tmp_path, "real") == "real/bin/python"
