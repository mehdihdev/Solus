"""`solus-companion runtime …` — subcommands, JSONL output, exit codes (§6)."""

from __future__ import annotations

import hashlib
import io
import os
import signal
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from companion_runtime_fakes import (
    FakeRunner,
    ProvisionScript,
    make_fork,
    probe_json,
    trusted_env,
    write_exe,
)
from solus_companion.runtime import cli
from solus_companion.runtime.detect import HostView
from solus_companion.runtime.errors import Cancelled
from solus_companion.runtime.managed import ManagedAsset, ManagedManifest, load_manifest
from solus_companion.runtime.ownership import PosixOwnerOnly
from solus_companion.runtime.proc import ProcResult
from solus_companion.runtime.protocol import (
    MAX_LINE_BYTES,
    CandidateLine,
    DoneLine,
    ErrorLine,
    ForkResultLine,
    RuntimeLine,
    StatusLine,
    parse_line,
)
from solus_companion.runtime.stamp import STAMP_NAME, read_stamp

NET_DOWN = ProcResult(1, "", "Failed to establish a new connection: [Errno 8] nodename")


class Env:
    """One sandboxed machine: integrations tree, envs root, PATH, managed root."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "mcp"
        self.envs = tmp_path / "data" / "mcp-envs"
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        make_fork(self.root, "kicad")
        make_fork(self.root, "code")
        make_fork(self.root, "altium", platforms=["win32"], display="Altium Designer")
        make_fork(self.root, "mock", lock=None)
        self.python = write_exe(self.bindir / "python3.12")
        self.versions: dict[str, tuple[str, str]] = {str(self.python): ("3.12.7", "cpython")}
        self.venvs: set[str] = set()
        self.script = ProvisionScript()
        self.policy = PosixOwnerOnly()
        self.manifest = load_manifest()
        self.fetch_data = b""

    def _handler(self, argv: list[str], env: Mapping[str, str]) -> ProcResult:
        is_probe = argv[1:] == ["-I", "-c", cli.PROBE_SCRIPT]
        if is_probe and not argv[0].startswith(str(self.envs)):
            # A base-interpreter probe: only the registered versions start.
            if argv[0] not in self.versions:
                return ProcResult(1, "", "no such interpreter")
            version, impl = self.versions[argv[0]]
            venv = argv[0] in self.venvs
            return ProcResult(0, probe_json(argv[0], version, impl, venv=venv), "")
        return self.script(argv, env)

    def deps(self) -> cli.CliDeps:
        host = HostView(
            platform="darwin",
            env={"PATH": str(self.bindir), "HOME": str(self.tmp)},
            home=self.tmp / "home",
            system_root=self.tmp / "sys",
        )
        data = self.fetch_data

        class Stream:
            def __init__(self) -> None:
                self.buf = io.BytesIO(data)

            def read(self, n: int, /) -> bytes:
                return self.buf.read(n)

            def close(self) -> None:
                return None

        return cli.CliDeps(
            runner=FakeRunner(self._handler),
            policy=self.policy,
            host=host,
            fetcher=lambda url, timeout: (Stream(), len(data)),
            manifest=lambda: self.manifest,
            integrations_root=self.root,
            asset_key="darwin-arm64",
        )

    def run(self, *argv: str) -> tuple[int, list[RuntimeLine]]:
        out = io.BytesIO()
        code = cli.main([*argv, "--envs-root", str(self.envs)], deps=self.deps(), stdout=out)
        raw = out.getvalue().splitlines(keepends=True)
        parsed = [parse_line(line) for line in raw]
        assert all(len(line) <= MAX_LINE_BYTES for line in raw)
        assert None not in parsed, raw
        return code, [p for p in parsed if p is not None]


@pytest.fixture
def machine(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _done(lines: list[RuntimeLine]) -> DoneLine:
    assert isinstance(lines[-1], DoneLine)
    assert sum(isinstance(line, DoneLine) for line in lines) == 1
    return lines[-1]


def _of[T](lines: list[RuntimeLine], kind: type[T]) -> list[T]:
    return [line for line in lines if isinstance(line, kind)]


# ------------------------------------------------------------------- usage


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["provision"],
        ["provision", "--all", "--python", "relative/python3"],
        ["provision", "--all", "--python", "/x", "--managed"],
        ["provision", "--fork", "nope"],
        ["provision", "--fork", "mock"],
        ["provision", "--fork", "../etc"],
        ["detect", "--envs-root", "relative"],
    ],
)
def test_usage_errors_exit_3_with_nothing_on_stdout(argv: list[str], machine: Env) -> None:
    out = io.BytesIO()
    assert cli.main(argv, deps=machine.deps(), stdout=out) == 3
    assert out.getvalue() == b""


# ------------------------------------------------------------------- detect


def test_detect_lists_candidates_then_done(machine: Env) -> None:
    pypy = write_exe(machine.bindir / "python3")
    machine.versions[str(pypy)] = ("3.10.14", "pypy")

    code, lines = machine.run("detect")

    assert code == 0
    candidates = _of(lines, CandidateLine)
    assert [(c.path, c.supported) for c in candidates] == [
        (str(machine.python), True),
        (str(pypy), False),
    ]
    done = _done(lines)
    assert (done.outcome, done.ok, done.failed, done.skipped) == ("ok", 1, 0, 1)


def test_detect_with_nothing_supported_fails(machine: Env) -> None:
    machine.versions[str(machine.python)] = ("3.11.4", "cpython")
    code, lines = machine.run("detect")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["python_not_found"]
    done = _done(lines)
    assert (done.outcome, done.ok, done.skipped) == ("failed", 0, 1)


# ------------------------------------------------------------------- status


def test_status_reports_each_python_fork(machine: Env) -> None:
    trusted_env(machine.envs, "kicad", machine.root / "kicad" / "requirements.lock.txt")

    code, lines = machine.run("status")

    assert code == 0
    by_fork = {s.fork: s for s in _of(lines, StatusLine)}
    assert sorted(by_fork) == ["altium", "code", "kicad"]
    assert (by_fork["kicad"].state, by_fork["kicad"].detail) == ("ready", None)
    assert by_fork["kicad"].base_version == "3.12.7"
    assert (by_fork["code"].state, by_fork["code"].detail) == ("needs_setup", "needs_setup:no_env")
    assert by_fork["altium"].state == "unsupported_platform"
    done = _done(lines)
    assert (done.outcome, done.ok, done.failed, done.skipped) == ("ok", 1, 1, 1)


def test_status_without_an_integrations_root_fails(machine: Env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("SOLUS_COMPANION_INTEGRATIONS_ROOT", raising=False)
    deps = machine.deps()
    out = io.BytesIO()
    no_root = cli.CliDeps(**{**deps.__dict__, "integrations_root": None})
    assert cli.main(["status"], deps=no_root, stdout=out) == 2


def test_provision_without_an_integrations_root_fails_instead_of_reporting_ok(  # type: ignore[no-untyped-def]
    machine: Env, monkeypatch
) -> None:
    """SOLUSDEV-329: with no forks tree found, `provision --all` used to emit
    done/ok with zero forks — a silent no-op the desktop showed as success."""
    monkeypatch.delenv("SOLUS_COMPANION_INTEGRATIONS_ROOT", raising=False)
    deps = machine.deps()
    out = io.BytesIO()
    no_root = cli.CliDeps(**{**deps.__dict__, "integrations_root": None})
    code = cli.main(
        ["provision", "--all", "--python", str(machine.python)], deps=no_root, stdout=out
    )
    assert code == 2
    assert b'"outcome":"ok"' not in out.getvalue()


# ---------------------------------------------------------------- provision


def test_provision_all_with_an_explicit_python(machine: Env) -> None:
    code, lines = machine.run("provision", "--all", "--python", str(machine.python))

    assert code == 0
    results = {r.fork: r.outcome for r in _of(lines, ForkResultLine)}
    assert results == {"altium": "skipped", "code": "ok", "kicad": "ok"}
    done = _done(lines)
    assert (done.outcome, done.ok, done.failed, done.skipped) == ("ok", 2, 0, 1)
    stamp = read_stamp(machine.envs / "kicad" / STAMP_NAME)
    assert stamp is not None and stamp.base.path == str(machine.python)


def test_provision_partial_exits_1(machine: Env) -> None:
    machine.script = ProvisionScript(pip={"code": NET_DOWN})
    code, lines = machine.run("provision", "--fork", "kicad", "--fork", "code")
    assert code == 1
    results = {r.fork: (r.outcome, r.error_code) for r in _of(lines, ForkResultLine)}
    assert results == {"kicad": ("ok", None), "code": ("failed", "network_unreachable")}
    assert _done(lines).outcome == "partial"


def test_provision_all_failed_exits_2_with_an_error_line(machine: Env) -> None:
    machine.script = ProvisionScript(pip={"code": NET_DOWN, "kicad": NET_DOWN})
    code, lines = machine.run("provision", "--all")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["network_unreachable"]
    done = _done(lines)
    assert (done.outcome, done.ok, done.failed) == ("failed", 0, 2)


def test_provision_refuses_an_unsupported_python(machine: Env) -> None:
    pypy = write_exe(machine.tmp / "pypy3")
    machine.versions[str(pypy)] = ("3.10.14", "pypy")
    code, lines = machine.run("provision", "--all", "--python", str(pypy))
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["python_not_cpython"]
    assert not machine.envs.exists() or list(machine.envs.iterdir()) == []


def test_provision_refuses_an_explicit_venv_python(machine: Env) -> None:
    """A venv's interpreter is not a base: `venv --copies` from it is fragile."""
    venv = write_exe(machine.tmp / "venv" / "bin" / "python3")
    machine.versions[str(venv)] = ("3.12.7", "cpython")
    machine.venvs.add(str(venv))
    code, lines = machine.run("provision", "--all", "--python", str(venv))
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["python_is_venv"]
    assert not machine.envs.exists() or list(machine.envs.iterdir()) == []


def test_detect_marks_a_venv_on_path_unsupported(machine: Env) -> None:
    machine.venvs.add(str(machine.python))
    code, lines = machine.run("detect")
    assert code == 2
    [candidate] = _of(lines, CandidateLine)
    assert (candidate.supported, candidate.reason) == (False, "python_is_venv")


def test_provision_auto_without_any_python(machine: Env) -> None:
    machine.versions.clear()
    code, lines = machine.run("provision", "--all")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["python_not_found"]


def test_provision_managed_requires_an_installed_managed_python(machine: Env) -> None:
    code, lines = machine.run("provision", "--all", "--managed")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["managed_not_installed"]


def test_provision_managed_uses_the_installed_release(machine: Env) -> None:
    managed = write_exe(
        machine.envs.parent / "mcp-python" / machine.manifest.release / "python" / "bin" / "python3"
    )
    machine.versions[str(managed)] = ("3.12.7", "cpython")
    code, lines = machine.run("provision", "--fork", "kicad", "--managed")
    assert code == 0, lines
    stamp = read_stamp(machine.envs / "kicad" / STAMP_NAME)
    assert stamp is not None and stamp.base.managed is True


def test_provision_refuses_a_foreign_envs_root(machine: Env) -> None:
    machine.policy = PosixOwnerOnly(euid=lambda: os.geteuid() + 1)
    machine.envs.mkdir(parents=True)
    code, lines = machine.run("provision", "--all")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["not_owner_only"]


def test_provision_cancelled_exits_130_and_discards_the_build(machine: Env) -> None:
    def cancel(argv: list[str]) -> None:
        raise Cancelled()

    machine.script = ProvisionScript(on_pip=cancel)
    code, lines = machine.run("provision", "--fork", "kicad", "--fork", "code")
    assert code == 130
    results = [(r.fork, r.error_code) for r in _of(lines, ForkResultLine)]
    assert results == [("code", "cancelled")]  # sorted order; kicad never started
    assert _done(lines).outcome == "cancelled"
    assert list(machine.envs.iterdir()) == []


# ---------------------------------------------------------- install-managed


def test_install_managed_refuses_the_placeholder_manifest(machine: Env) -> None:
    code, lines = machine.run("install-managed")
    assert code == 2
    assert [e.error_code for e in _of(lines, ErrorLine)] == ["managed_hash_mismatch"]
    assert _done(lines).outcome == "failed"


def test_install_managed_happy_path(machine: Env) -> None:
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("python/bin/python3")
        info.size = 2
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(b"#!"))
    machine.fetch_data = buf.getvalue()
    url = "https://github.com/astral-sh/python-build-standalone/releases/download/r9/x.tar.gz"
    machine.manifest = ManagedManifest(
        schema_version=1,
        release="r9",
        python_version="3.12.7",
        verified=True,
        assets={
            "darwin-arm64": ManagedAsset(
                url=url, sha256=hashlib.sha256(machine.fetch_data).hexdigest(), max_bytes=10**6
            )
        },
    )
    code, lines = machine.run("install-managed")
    assert code == 0
    assert _done(lines).outcome == "ok"
    assert (machine.envs.parent / "mcp-python" / "r9" / "python" / "bin" / "python3").is_file()


# ------------------------------------------------------------------ signals


def test_signal_handlers_raise_cancelled_and_are_restored() -> None:
    before = signal.getsignal(signal.SIGTERM)
    with cli.cancel_on_signals():
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(Cancelled):
            handler(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == before


# ----------------------------------------------------------------- __main__


def test_main_dispatches_the_runtime_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_companion import __main__ as entry

    seen: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        seen.append(list(argv))
        return 7

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["solus-companion", "runtime", "status"])

    assert entry.main() == 7
    assert seen == [["status"]]


def test_runtime_cli_runs_as_a_real_process(tmp_path: Path) -> None:
    """End to end through `python -m solus_companion runtime status`."""
    import subprocess

    root = tmp_path / "mcp"
    make_fork(root, "kicad")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SOLUS_COMPANION_INTEGRATIONS_ROOT": str(root),
        "SOLUS_COMPANION_MCP_ENVS_ROOT": str(tmp_path / "envs"),
    }
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "solus_companion", "runtime", "status"],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [parse_line(line) for line in proc.stdout.splitlines(keepends=True)]
    assert isinstance(lines[0], StatusLine) and lines[0].detail == "needs_setup:no_env"
    assert isinstance(lines[-1], DoneLine)
