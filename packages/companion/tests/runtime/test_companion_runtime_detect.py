"""Interpreter detection and the base-interpreter health probe (§3 step 1)."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from collections.abc import Mapping
from pathlib import Path

import pytest
from companion_runtime_fakes import FakeRunner, probe_json, write_exe
from solus_companion.runtime.detect import (
    Detector,
    HostView,
    assess,
    best_candidate,
    parse_py_launcher,
    windows_registry_pythons,
)
from solus_companion.runtime.errors import MESSAGES
from solus_companion.runtime.probe import PROBE_SCRIPT, ProbeReport, is_store_alias, judge
from solus_companion.runtime.proc import ProcResult


def _report(version: str = "3.12.7", impl: str = "cpython") -> ProbeReport:
    return ProbeReport(implementation=impl, version=version, executable="/x/python")


@pytest.mark.parametrize("version", ["3.12.0", "3.12.7", "3.13.1"])
def test_cpython_312_and_313_are_accepted(version: str) -> None:
    verdict = judge(_report(version))
    assert verdict.supported and verdict.reason is None
    assert verdict.version == version and verdict.implementation == "cpython"


@pytest.mark.parametrize("version", ["3.11.9", "3.14.0", "3.9.6", "3.13.0rc1", "2.7.18"])
def test_other_versions_are_refused(version: str) -> None:
    verdict = judge(_report(version))
    assert not verdict.supported
    assert verdict.reason == "python_unsupported_version"


def test_pypy_is_refused_as_not_cpython() -> None:
    verdict = judge(_report("3.10.14", "pypy"))
    assert verdict.reason == "python_not_cpython"
    assert verdict.implementation == "pypy"


def test_unknown_implementation_is_refused() -> None:
    verdict = judge(_report("3.12.1", "graalpy"))
    assert verdict.reason == "python_not_cpython"
    assert verdict.implementation == "unknown"


def test_a_venv_interpreter_is_refused_as_a_base() -> None:
    report = ProbeReport(implementation="cpython", version="3.12.7", executable="/v/python", venv=True)
    verdict = judge(report)
    assert (verdict.supported, verdict.reason) == (False, "python_is_venv")
    assert verdict.version == "3.12.7" and verdict.implementation == "cpython"


def test_a_report_without_the_venv_key_is_not_a_venv() -> None:
    report = ProbeReport.model_validate(
        {"implementation": "cpython", "version": "3.12.7", "executable": "/x/python"}
    )
    assert report.venv is False and judge(report).supported


def test_the_real_probe_reports_whether_it_runs_in_a_venv() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", PROBE_SCRIPT], capture_output=True, text=True, check=True
    )
    report = ProbeReport.model_validate_json(result.stdout)
    assert report.venv is (sys.prefix != sys.base_prefix)


def test_venv_message_tells_the_user_what_to_pick() -> None:
    assert MESSAGES["python_is_venv"] == (
        "This Python is a virtual environment; choose the Python it was created from."
    )


def test_no_report_is_a_probe_failure() -> None:
    verdict = judge(None)
    assert verdict.reason == "python_probe_failed" and verdict.version is None


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps\python.exe",
        r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps\python3.12.exe",
        "C:/Users/dev/AppData/Local/Microsoft/windowsapps/PYTHON3.EXE",
    ],
)
def test_store_alias_paths_are_recognised(path: str) -> None:
    assert is_store_alias(path)


def test_ordinary_windows_python_is_not_a_store_alias() -> None:
    assert not is_store_alias(r"C:\Program Files\Python312\python.exe")


def _host(
    tmp_path: Path,
    *,
    platform: str = "darwin",
    path_dirs: list[Path] | None = None,
    extra: Mapping[str, str] | None = None,
) -> HostView:
    env = {"PATH": os.pathsep.join(str(d) for d in (path_dirs or []))}
    env.update(extra or {})
    return HostView(
        platform=platform, env=env, home=tmp_path / "home", system_root=tmp_path / "sys"
    )


def _probing(versions: Mapping[str, str]) -> FakeRunner:
    """Probe answers by the realpath of argv[0]; unknown paths fail the probe."""

    def handler(argv: list[str], env: Mapping[str, str]) -> ProcResult:
        assert argv[1:] == ["-I", "-c", PROBE_SCRIPT]
        version = versions.get(os.path.realpath(argv[0]))
        if version is None:
            return ProcResult(returncode=1, stdout="", stderr="boom")
        impl = "pypy" if "pypy" in argv[0] else "cpython"
        return ProcResult(returncode=0, stdout=probe_json(argv[0], version, impl), stderr="")

    return FakeRunner(handler)


def test_path_candidates_are_probed_argv_only_and_deduped_by_realpath(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    real = write_exe(bindir / "python3.12")
    (bindir / "python3").symlink_to(real)
    (bindir / "python").symlink_to(real)
    runner = _probing({os.path.realpath(real): "3.12.7"})

    found = Detector(runner, _host(tmp_path, path_dirs=[bindir])).detect()

    assert [c.path for c in found] == [str(real)]
    assert found[0].source == "path" and found[0].verdict.supported
    assert len(runner.calls) == 1
    argv, env, timeout = runner.calls[0]
    assert argv == [str(real), "-I", "-c", PROBE_SCRIPT]
    assert timeout > 0 and "PYTHONPATH" not in env


def test_known_locations_include_pyenv_and_conda(tmp_path: Path) -> None:
    home = tmp_path / "home"
    pyenv = write_exe(home / ".pyenv" / "versions" / "3.12.4" / "bin" / "python3")
    conda = write_exe(home / "miniconda3" / "bin" / "python3")
    runner = _probing({os.path.realpath(pyenv): "3.12.4", os.path.realpath(conda): "3.11.5"})

    found = Detector(runner, _host(tmp_path)).detect()

    by_path = {c.path: c for c in found}
    assert by_path[str(pyenv)].source == "known_location"
    assert by_path[str(pyenv)].verdict.supported
    assert by_path[str(conda)].verdict.reason == "python_unsupported_version"


def test_managed_interpreters_are_listed_as_managed(tmp_path: Path) -> None:
    managed_root = tmp_path / "mcp-python"
    py = write_exe(managed_root / "20261001" / "python" / "bin" / "python3")
    runner = _probing({os.path.realpath(py): "3.12.7"})

    found = Detector(runner, _host(tmp_path), managed_root=managed_root).detect()

    assert [(c.path, c.source) for c in found] == [(str(py), "managed")]


def test_store_alias_is_refused_without_probing(tmp_path: Path) -> None:
    runner = _probing({})
    alias = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps\python.exe"

    candidate = assess(alias, "path", runner, _host(tmp_path, platform="win32"))

    assert candidate.verdict.reason == "python_store_alias"
    assert runner.calls == []


def test_xcode_stub_without_developer_tools_is_not_probed(tmp_path: Path) -> None:
    """Probing /usr/bin/python3 with no CLT installed pops the install dialog."""
    runner = _probing({})
    host = HostView(platform="darwin", env={}, home=tmp_path, system_root=tmp_path / "none")

    candidate = assess("/usr/bin/python3", "path", runner, host)

    assert candidate.verdict.reason == "python_unsupported_version"
    assert runner.calls == []


def test_xcode_stub_with_developer_tools_is_probed_and_refused_by_version(tmp_path: Path) -> None:
    (tmp_path / "Library" / "Developer" / "CommandLineTools").mkdir(parents=True)
    host = HostView(platform="darwin", env={}, home=tmp_path, system_root=tmp_path)
    runner = FakeRunner(lambda argv, env: ProcResult(0, probe_json(argv[0], "3.9.6"), ""))

    candidate = assess("/usr/bin/python3", "path", runner, host)

    assert candidate.verdict.reason == "python_unsupported_version"
    assert candidate.verdict.version == "3.9.6"


def test_garbage_probe_output_is_a_probe_failure(tmp_path: Path) -> None:
    py = write_exe(tmp_path / "python3")
    runner = FakeRunner(lambda argv, env: ProcResult(0, "not json" * 10, ""))
    assert assess(str(py), "path", runner, _host(tmp_path)).verdict.reason == "python_probe_failed"


def test_timed_out_probe_is_a_probe_failure(tmp_path: Path) -> None:
    py = write_exe(tmp_path / "python3")
    runner = FakeRunner(lambda argv, env: ProcResult(None, "", "", timed_out=True))
    assert assess(str(py), "path", runner, _host(tmp_path)).verdict.reason == "python_probe_failed"


def test_best_prefers_312_then_order(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    p313 = write_exe(bindir / "python3.13")
    p312 = write_exe(bindir / "python3.12")
    runner = _probing({os.path.realpath(p313): "3.13.1", os.path.realpath(p312): "3.12.7"})

    found = Detector(runner, _host(tmp_path, path_dirs=[bindir])).detect()

    assert [c.path for c in found] == [str(p313), str(p312)]  # PATH name order
    best = best_candidate(found)
    assert best is not None and best.path == str(p312)
    assert best_candidate([]) is None


def test_candidate_line_matches_the_protocol(tmp_path: Path) -> None:
    py = write_exe(tmp_path / "pypy3")
    runner = _probing({os.path.realpath(py): "3.10.14"})
    line = assess(str(py), "path", runner, _host(tmp_path)).to_line()
    assert line.implementation == "pypy" and line.reason == "python_not_cpython"
    assert line.version == "3.10.14" and line.supported is False


def test_py_launcher_output_is_parsed() -> None:
    out = (
        " -V:3.13 *        C:\\Python313\\python.exe\n"
        " -V:3.12          C:\\Users\\u\\AppData\\Local\\Programs\\Python\\Python312\\python.exe\n"
        " -3.11-64         C:\\Python311\\python.exe\n"
        "garbage line\n"
    )
    assert parse_py_launcher(out) == [
        "C:\\Python313\\python.exe",
        "C:\\Users\\u\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
        "C:\\Python311\\python.exe",
    ]


def test_windows_detection_uses_py_launcher_registry_and_known_dirs(tmp_path: Path) -> None:
    system = tmp_path / "Windows"
    write_exe(system / "py.exe")
    local = tmp_path / "Local"
    known = write_exe(local / "Programs" / "Python" / "Python312" / "python.exe")
    launched = write_exe(tmp_path / "Py313" / "python.exe")
    registry = write_exe(tmp_path / "Reg312" / "python.exe")

    def handler(argv: list[str], env: Mapping[str, str]) -> ProcResult:
        if argv[1:] == ["-0p"]:
            return ProcResult(0, f" -V:3.13 *   {launched}\n", "")
        return ProcResult(0, probe_json(argv[0], "3.12.7"), "")

    host = HostView(
        platform="win32",
        env={"LOCALAPPDATA": str(local), "PATH": ""},
        home=tmp_path,
        system_root=system,
        registry=lambda: [str(registry)],
    )

    found = Detector(FakeRunner(handler), host).detect()

    sources = {c.path: c.source for c in found}
    assert sources[str(launched)] == "py_launcher"
    assert sources[str(registry)] == "registry"
    assert sources[str(known)] == "known_location"


class _FakeKey:
    def __init__(self, children: dict[str, object], values: dict[str, str]) -> None:
        self.children = children
        self.values = values

    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _fake_winreg(tree: _FakeKey) -> types.SimpleNamespace:
    def open_key(parent: object, sub: str) -> _FakeKey:
        node = tree if parent in ("HKCU", "HKLM") else parent
        assert isinstance(node, _FakeKey)
        for part in sub.split("\\"):
            child = node.children.get(part)
            if not isinstance(child, _FakeKey):
                raise OSError(sub)
            node = child
        return node

    def enum_key(key: _FakeKey, index: int) -> str:
        names = list(key.children)
        if index >= len(names):
            raise OSError("no more")
        return names[index]

    def query_value_ex(key: _FakeKey, name: str) -> tuple[str, int]:
        if name not in key.values:
            raise OSError(name)
        return key.values[name], 1

    return types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_LOCAL_MACHINE="HKLM",
        OpenKey=open_key,
        EnumKey=enum_key,
        QueryValueEx=query_value_ex,
    )


def test_pep514_registry_walk_reads_executable_paths() -> None:
    install = _FakeKey({}, {"ExecutablePath": r"C:\Py312\python.exe", "": r"C:\Py312"})
    bare = _FakeKey({}, {"": "C:\\Py313\\"})
    tree = _FakeKey(
        {
            "Software": _FakeKey(
                {
                    "Python": _FakeKey(
                        {
                            "PythonCore": _FakeKey(
                                {
                                    "3.12": _FakeKey({"InstallPath": install}, {}),
                                    "3.13": _FakeKey({"InstallPath": bare}, {}),
                                    "3.11": _FakeKey({}, {}),
                                },
                                {},
                            )
                        },
                        {},
                    )
                },
                {},
            ),
        },
        {},
    )

    found = windows_registry_pythons(_fake_winreg(tree))

    assert r"C:\Py312\python.exe" in found
    assert "C:\\Py313\\python.exe" in found


def test_registry_walk_without_winreg_is_empty() -> None:
    assert windows_registry_pythons(None) == []
