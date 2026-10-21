"""SOLUSDEV-250 — `probe_environment`: injected `which`/capture, the §4 shape,
dedupe by real path, the ≤ 8 / ≤ 300 / ≤ 32 caps, venv discovery order,
every failure reading as null/empty, never raises; plus the real capture."""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip
from venv_fixture import fake_venv  # isort: skip

probe = overlay_module("probe")


def _which(available: dict[str, str]) -> Any:
    return lambda name: available.get(name)


def _capture(answers: Mapping[Any, str]) -> Any:
    return lambda argv, _timeout: answers.get(tuple(argv))


def _venv(root: Path, name: str) -> str:
    return str(fake_venv(root, name))


def _bins(tmp_path: Path, *names: str) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    paths: dict[str, str] = {}
    for name in names:
        (bindir / name).write_text("")
        paths[name] = str(bindir / name)
    return paths


def _site(root: Path, name: str, packages: list[tuple[str, str]], py: str = "3.12") -> Path:
    """Write `*.dist-info/METADATA` for `packages` under `<venv>/lib/pythonX/site-packages`."""
    site = root / name / "lib" / f"python{py}" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for package, version in packages:
        info = site / f"{package}-{version}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n\nName: body\n"
        )
    return site


def _recording(answers: Mapping[Any, str]) -> tuple[Any, list[list[str]]]:
    calls: list[list[str]] = []

    def capture(argv: list[str], _timeout: int) -> str | None:
        calls.append(list(argv))
        return answers.get(tuple(argv))

    return capture, calls


def test_full_shape(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    _venv(ws, ".venv")
    _site(ws, ".venv", [("torch", "2.1.0"), ("numpy", "1.26.4")])
    bins = _bins(tmp_path, "python3", "python3.11", "uv", "conda")
    answers = {
        (bins["python3"], "--version"): "Python 3.12.4\n",
        (bins["python3.11"], "--version"): "Python 3.11.9",
        (bins["uv"], "--version"): "uv 0.4.30 (Homebrew 2024-11-01)",
        (bins["conda"], "env", "list", "--json"): json.dumps(
            {"envs": ["/opt/conda", "/opt/conda/envs/robot"]}
        ),
    }
    result = probe.probe_environment(ws, which=_which(bins), capture=_capture(answers))
    assert result == {
        "python": {"path": bins["python3"], "version": "3.12.4"},
        "interpreters": [
            {"path": bins["python3"], "version": "3.12.4"},
            {"path": bins["python3.11"], "version": "3.11.9"},
        ],
        "venv": {
            "path": ".venv",
            "python_version": "3.12.0",
            "packages": [
                {"name": "numpy", "version": "1.26.4"},
                {"name": "torch", "version": "2.1.0"},
            ],
            "truncated": False,
        },
        "conda": {"path": bins["conda"], "envs": ["conda", "robot"]},
        "uv": {"path": bins["uv"], "version": "0.4.30"},
    }


def test_venv_inventory_never_executes_anything_in_the_venv(tmp_path: Path) -> None:
    """Phase 4 C1: no venv interpreter, pip or `uv pip list` is ever started."""
    ws = tmp_path / "ws"
    ws.mkdir()
    venv_python = _venv(ws, ".venv")
    _site(ws, ".venv", [("six", "1.17.0")])
    bins = _bins(tmp_path, "uv")
    capture, calls = _recording({(bins["uv"], "--version"): "uv 0.4.30"})
    result = probe.probe_environment(ws, which=_which(bins), capture=capture)
    assert result["venv"]["packages"] == [{"name": "six", "version": "1.17.0"}]
    assert all(venv_python not in call and "pip" not in call for call in calls)
    assert all(not call[0].startswith(str(ws)) for call in calls)


def test_planted_pth_in_a_real_interpreter_venv_has_no_side_effect(tmp_path: Path) -> None:
    """Phase 4 C1 (real capture): a venv whose bin/python links to a real system
    python and whose site-packages carries an import-time `.pth` payload. Running
    that interpreter (or pip with it) would execute the payload; the probe must
    not, and it still lists the packages."""
    ws = tmp_path / "ws"
    python = ws / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    os.symlink(os.path.realpath(sys.executable), python)
    (ws / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\nversion_info = 3.12.4.final.0\n")
    site = _site(ws, ".venv", [("evil", "6.6.6"), ("mujoco", "3.2.0")])
    marker = tmp_path / "pwned"
    (site / "evil.pth").write_text(f"import os; open({str(marker)!r}, 'w').close()\n")
    result = probe.probe_environment(ws, capture=probe.run_capture)
    assert not marker.exists()
    assert result["venv"] == {
        "path": ".venv",
        "python_version": "3.12.4",
        "packages": [
            {"name": "evil", "version": "6.6.6"},
            {"name": "mujoco", "version": "3.2.0"},
        ],
        "truncated": False,
    }


def test_nothing_installed_is_the_empty_shape(tmp_path: Path) -> None:
    result = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))
    assert result == probe.empty_probe()
    assert result == {"python": None, "interpreters": [], "venv": None, "conda": None, "uv": None}


def test_interpreters_dedupe_by_real_path_and_skip_version_failures(tmp_path: Path) -> None:
    bins = _bins(tmp_path, "python3.12", "python")
    os.symlink(bins["python3.12"], tmp_path / "bin" / "python3")
    bins["python3"] = str(tmp_path / "bin" / "python3")
    answers = {
        (bins["python3"], "--version"): "Python 3.12.1",
        (bins["python3.12"], "--version"): "Python 3.12.1",
    }
    result = probe.probe_environment(tmp_path, which=_which(bins), capture=_capture(answers))
    assert result["interpreters"] == [
        {"path": bins["python3"], "version": "3.12.1"}
    ]  # `python` had no version


def test_interpreters_cap_at_eight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = tuple(f"python3.{i}" for i in range(12))
    monkeypatch.setattr(probe, "INTERPRETER_NAMES", names)
    bins = _bins(tmp_path, *names)
    answers = {(path, "--version"): "Python 3.9.9" for path in bins.values()}
    result = probe.probe_environment(tmp_path, which=_which(bins), capture=_capture(answers))
    assert len(result["interpreters"]) == probe.MAX_INTERPRETERS == 8


def test_venv_discovery_order_and_package_cap(tmp_path: Path) -> None:
    _venv(tmp_path, "venv")
    _venv(tmp_path, ".venv")
    _site(tmp_path, ".venv", [(f"p{i:03}", "1") for i in range(350)])
    result = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))
    assert result["venv"]["path"] == ".venv"
    assert len(result["venv"]["packages"]) == 300 and result["venv"]["truncated"] is True


def test_site_entry_scan_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "MAX_SITE_ENTRIES", 5)
    _venv(tmp_path, ".venv")
    _site(tmp_path, ".venv", [(f"p{i}", "1") for i in range(10)])
    venv = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))["venv"]
    assert len(venv["packages"]) <= 5 and venv["truncated"] is True


def test_python_version_unreadable_cfg_is_null(tmp_path: Path) -> None:
    _venv(tmp_path, ".venv")
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\nversion = garbage\n")
    venv = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))["venv"]
    assert venv["python_version"] is None and venv["packages"] == []


def test_windows_layout_is_read(tmp_path: Path) -> None:
    _venv(tmp_path, ".venv")
    site = tmp_path / ".venv" / "Lib" / "site-packages" / "rclpy-1.0.dist-info"
    site.mkdir(parents=True)
    (site / "METADATA").write_text("Name: rclpy\nVersion: 1.0\n")
    venv = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))["venv"]
    assert venv["packages"] == [{"name": "rclpy", "version": "1.0"}]


def test_malformed_and_escaping_metadata_is_skipped_and_marked_incomplete(tmp_path: Path) -> None:
    _venv(tmp_path, ".venv")
    site = _site(tmp_path, ".venv", [("good", "1.0")])
    (site / "noversion-1.dist-info").mkdir()
    (site / "noversion-1.dist-info" / "METADATA").write_text("Name: noversion\n")
    (site / "nometa-1.dist-info").mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.dist-info"
    outside.mkdir()
    (outside / "METADATA").write_text("Name: secret\nVersion: 9\n")
    (site / "link-1.dist-info").symlink_to(outside, target_is_directory=True)
    linked = site / "filelink-1.dist-info"
    linked.mkdir()
    (linked / "METADATA").symlink_to(outside / "METADATA")
    venv = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))["venv"]
    assert venv["packages"] == [{"name": "good", "version": "1.0"}]
    assert venv["truncated"] is True


def test_successful_empty_inventory_remains_complete(tmp_path: Path) -> None:
    _venv(tmp_path, "env")
    _site(tmp_path, "env", [])
    result = probe.probe_environment(tmp_path, which=_which({}), capture=_capture({}))
    assert result["venv"]["path"] == "env"
    assert result["venv"]["packages"] == []
    assert result["venv"]["truncated"] is False


def test_shortened_package_metadata_is_marked_incomplete(tmp_path: Path) -> None:
    _venv(tmp_path, "sim")
    _site(tmp_path, "sim", [("ok", "y" * 80)])
    result = probe.probe_environment(
        tmp_path, environment="sim", which=_which({}), capture=_capture({})
    )
    assert result["venv"]["truncated"] is True
    assert len(result["venv"]["packages"][0]["version"]) == 39


def test_conda_garbage_and_cap(tmp_path: Path) -> None:
    bins = _bins(tmp_path, "conda")
    envs = [f"/opt/conda/envs/e{i}" for i in range(40)] + [3, ""]
    for text, expected in (
        ("nope", []),
        ("[]", []),
        (json.dumps({"envs": envs}), [f"e{i}" for i in range(32)]),
    ):
        answers = {(bins["conda"], "env", "list", "--json"): text}
        result = probe.probe_environment(tmp_path, which=_which(bins), capture=_capture(answers))
        assert result["conda"] == {"path": bins["conda"], "envs": expected}


def test_uv_without_a_version_is_null(tmp_path: Path) -> None:
    bins = _bins(tmp_path, "uv")
    result = probe.probe_environment(tmp_path, which=_which(bins), capture=_capture({}))
    assert result["uv"] is None


def test_never_raises_when_probes_explode(tmp_path: Path) -> None:
    def boom(*_args: object) -> Any:
        raise RuntimeError("fire")

    _venv(tmp_path, ".venv")
    result = probe.probe_environment(tmp_path, which=boom, capture=boom)
    # The venv is read from disk, so it survives exploding interpreter probes.
    assert {**result, "venv": None} == probe.empty_probe()
    assert result["venv"]["path"] == ".venv"


def test_probe_env_is_scrubbed_and_path_is_the_pinned_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_THING", "x")
    monkeypatch.setenv("PATH", "/evil")
    env = probe._probe_env()
    assert set(env) <= {"PATH", "HOME", "LANG", "TMPDIR"}
    assert "/evil" not in env["PATH"] and env["PATH"].endswith("/usr/bin:/bin")


def test_run_capture_real_success_failure_missing_and_timeout() -> None:
    assert (probe.run_capture([sys.executable, "--version"], 30) or "").startswith("Python 3")
    assert probe.run_capture([sys.executable, "-c", "import sys; sys.exit(2)"], 30) is None
    assert probe.run_capture(["/nonexistent/binary", "--version"], 30) is None
    assert probe.run_capture([sys.executable, "-c", "import time; time.sleep(30)"], 1) is None


def test_run_capture_bounds_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "MAX_CAPTURE_BYTES", 5)
    assert probe.run_capture([sys.executable, "-c", "print('x' * 100)"], 30) == "xxxxx"


def test_a_planted_workspace_interpreter_is_never_executed(tmp_path: Path) -> None:
    """Security review C1: the ungated probe must not run a `.venv/bin/python`
    that is workspace content. Real `run_capture`; the planted script would
    leave a marker file if it ever ran."""
    ws = tmp_path / "ws"
    planted = ws / ".venv" / "bin" / "python"
    planted.parent.mkdir(parents=True)
    marker = tmp_path / "pwned"
    planted.write_text(f"#!/bin/sh\ntouch {marker}\necho 'Python 3.12.0'\n")
    planted.chmod(0o755)
    (ws / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    result = probe.probe_environment(ws, which=_which({}), capture=probe.run_capture)
    assert result["venv"] is None
    assert not marker.exists()


def test_run_capture_kills_the_whole_group_on_timeout() -> None:
    import sys
    import time

    started = time.monotonic()
    assert (
        probe.run_capture(
            [
                sys.executable,
                "-c",
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "time.sleep(30)",
            ],
            1,
        )
        is None
    )
    assert time.monotonic() - started < 10


@pytest.mark.parametrize("environment", ["sim", "environments/sim"])
def test_named_environment_observes_only_requested_target(tmp_path: Path, environment: str) -> None:
    _venv(tmp_path, ".venv")
    _site(tmp_path, ".venv", [("default", "1")])
    _venv(tmp_path, environment)
    _site(tmp_path, environment, [("mujoco", "3.2.0")])
    capture, calls = _recording({})
    result = probe.probe_environment(
        tmp_path, environment=environment, which=_which({}), capture=capture
    )
    assert result["venv"] == {
        "path": environment,
        "python_version": "3.12.0",
        "packages": [{"name": "mujoco", "version": "3.2.0"}],
        "truncated": False,
    }
    assert calls == []


@pytest.mark.parametrize(
    "environment",
    ["missing", "", "../escape", "/tmp", "sim/../.venv", "C:\\sim", "-sim", "sim\n", 7, [], {}],
)
def test_invalid_named_environment_never_falls_back_or_captures(
    tmp_path: Path, environment: Any
) -> None:
    _venv(tmp_path, ".venv")
    calls: list[list[str]] = []

    def capture(argv: list[str], _timeout: int) -> None:
        calls.append(argv)

    result = probe.probe_environment(
        tmp_path, environment=environment, which=_which({}), capture=capture
    )
    assert result["venv"] is None
    assert calls == []


def test_named_environment_escaping_symlink_is_not_probed(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    _venv(tmp_path, "outside")
    _venv(ws, ".venv")
    (ws / "sim").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert probe.probe_environment(ws, environment="sim", which=_which({}))["venv"] is None


def test_named_environment_planted_interpreter_is_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    python = tmp_path / "sim/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/sh\ntouch {marker}\n")
    python.chmod(0o755)
    (tmp_path / "sim/pyvenv.cfg").write_text("home = /usr/bin\n")
    assert probe.probe_environment(tmp_path, environment="sim", which=_which({}))["venv"] is None
    assert not marker.exists()
