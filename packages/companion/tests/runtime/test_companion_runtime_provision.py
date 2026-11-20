"""Env building — mcp-fork-runtime.md §3 (fakes) plus one real `--copies` venv."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from companion_runtime_fakes import (
    FakeRunner,
    ProvisionScript,
    make_fork,
    trusted_env,
    write_exe,
)
from solus_companion.runtime.errors import Cancelled
from solus_companion.runtime.forks import ForkInfo, python_forks
from solus_companion.runtime.ownership import PosixOwnerOnly
from solus_companion.runtime.proc import ProcResult, run_capped
from solus_companion.runtime.protocol import ProgressLine, RuntimeLine
from solus_companion.runtime.provision import (
    PIP_TIMEOUT_SECONDS,
    PYPI_INDEX,
    VENV_TIMEOUT_SECONDS,
    BaseInterpreter,
    EnvBuilder,
    classify_pip_failure,
    count_requirements,
)
from solus_companion.runtime.stamp import STAMP_NAME, lock_sha256, read_stamp
from solus_companion.runtime.trust import evaluate_trust

POLICY = PosixOwnerOnly()
DIRTY_ENV = {
    "PATH": "/evil:/usr/bin",
    "HOME": "/Users/u",
    "PIP_INDEX_URL": "https://evil.example/simple",
    "PYTHONPATH": "/evil",
    "VIRTUAL_ENV": "/v",
    "CONDA_PREFIX": "/c",
    "__PYVENV_LAUNCHER__": "/x",
}


def _base(path: str | None = None, managed: bool = False) -> BaseInterpreter:
    return BaseInterpreter(path=path or sys.executable, version="3.12.7", managed=managed)


def _builder(
    envs: Path, runner: FakeRunner, emitted: list[RuntimeLine] | None = None
) -> EnvBuilder:
    POLICY.ensure(envs)
    sink = emitted if emitted is not None else []
    return EnvBuilder(
        envs_root=envs,
        runner=runner,
        policy=POLICY,
        emit=sink.append,
        platform="darwin",
        env_source=DIRTY_ENV,
    )


def _fork(root: Path, name: str = "kicad", **kw: object) -> ForkInfo:
    make_fork(root, name, **kw)  # type: ignore[arg-type]
    return next(f for f in python_forks(root, "darwin") if f.name == name)


def test_happy_path_builds_a_trusted_env(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    runner = FakeRunner(ProvisionScript())
    emitted: list[RuntimeLine] = []

    outcome = _builder(envs, runner, emitted).build(fork, _base())

    assert outcome.outcome == "ok" and outcome.error_code is None
    trust = evaluate_trust("kicad", fork.lock, envs, platform="darwin", policy=POLICY)
    assert trust.ready, trust.detail
    stamp = read_stamp(envs / "kicad" / STAMP_NAME)
    assert stamp is not None and stamp.lock_sha256 == lock_sha256(fork.lock)
    assert stamp.base.path == sys.executable and stamp.base.managed is False
    assert [p.name for p in envs.iterdir()] == ["kicad"]  # no temp left behind
    steps = [(e.step, e.done, e.total) for e in emitted if isinstance(e, ProgressLine)]
    assert steps == [
        ("venv", 0, None),
        ("check", 1, 1),
        ("install", 0, 2),
        ("install", 2, 2),
        ("stamp", 1, 1),
    ]


def test_exact_argv_and_timeouts(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    runner = FakeRunner(ProvisionScript())

    _builder(envs, runner).build(fork, _base())

    (venv_argv, _, venv_t), (check_argv, _, _), (pip_argv, _, pip_t) = runner.calls
    tmp = venv_argv[-1]
    assert venv_argv == [sys.executable, "-I", "-m", "venv", "--copies", tmp]
    assert Path(tmp).parent == envs and Path(tmp).name.startswith(".kicad.")
    assert check_argv[:3] == [f"{tmp}/bin/python", "-I", "-c"]
    assert pip_argv == [
        f"{tmp}/bin/python",
        "-I",
        "-m",
        "pip",
        "--isolated",
        "install",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-deps",
        "--no-input",
        "--disable-pip-version-check",
        "--retries",
        "5",
        "--timeout",
        "60",
        "--index-url",
        PYPI_INDEX,
        "-r",
        str(fork.lock),
    ]
    assert venv_t == VENV_TIMEOUT_SECONDS and pip_t == PIP_TIMEOUT_SECONDS


def test_every_child_env_is_scrubbed(tmp_path: Path) -> None:
    runner = FakeRunner(ProvisionScript())
    _builder(tmp_path / "envs", runner).build(_fork(tmp_path / "mcp"), _base())
    for _, env, _ in runner.calls:
        assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
        for key in env:
            assert not key.startswith(("PIP_", "PYTHON", "VIRTUAL_ENV", "CONDA_", "__PYVENV"))


def test_an_existing_env_is_replaced_whole_never_patched(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    trusted_env(envs, "kicad", fork.lock)
    marker = envs / "kicad" / "lib" / "stale-package"
    marker.parent.mkdir(parents=True)
    marker.write_text("old")

    outcome = _builder(envs, FakeRunner(ProvisionScript())).build(fork, _base())

    assert outcome.outcome == "ok"
    assert not marker.exists()
    assert sorted(p.name for p in envs.iterdir()) == ["kicad"]


def test_a_failed_rebuild_keeps_the_old_env(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    trusted_env(envs, "kicad", fork.lock)
    failing = ProvisionScript(pip={"kicad": ProcResult(1, "", "ERROR: something odd")})

    outcome = _builder(envs, FakeRunner(failing)).build(fork, _base())

    assert outcome.outcome == "failed" and outcome.error_code == "pip_failed"
    assert evaluate_trust("kicad", fork.lock, envs, platform="darwin", policy=POLICY).ready
    assert sorted(p.name for p in envs.iterdir()) == ["kicad"]


def test_stale_build_dirs_from_a_crash_are_swept(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    POLICY.ensure(envs)
    (envs / ".kicad.build-dead").mkdir()
    (envs / ".kicad.old-dead").mkdir()
    (envs / ".code.build-alive").mkdir()

    _builder(envs, FakeRunner(ProvisionScript())).build(_fork(tmp_path / "mcp"), _base())

    assert sorted(p.name for p in envs.iterdir()) == [".code.build-alive", "kicad"]


def test_an_interrupted_swap_restores_the_old_env(tmp_path: Path) -> None:
    """Killed between "old env aside" and "new env in": the next run puts the
    old env back before building, so a failed rebuild still leaves it usable."""
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    trusted_env(envs, "kicad", fork.lock)
    os.replace(envs / "kicad", envs / ".kicad.old-dead")
    failing = ProvisionScript(pip={"kicad": ProcResult(1, "", "ERROR: something odd")})

    outcome = _builder(envs, FakeRunner(failing)).build(fork, _base())

    assert outcome.outcome == "failed"
    assert sorted(p.name for p in envs.iterdir()) == ["kicad"]
    assert evaluate_trust("kicad", fork.lock, envs, platform="darwin", policy=POLICY).ready


def test_an_interrupted_swap_leftover_is_removed_when_the_env_exists(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    fork = _fork(tmp_path / "mcp")
    trusted_env(envs, "kicad", fork.lock)
    (envs / ".kicad.old-dead" / "marker").parent.mkdir()
    failing = ProvisionScript(pip={"kicad": ProcResult(1, "", "ERROR: something odd")})

    _builder(envs, FakeRunner(failing)).build(fork, _base())

    assert sorted(p.name for p in envs.iterdir()) == ["kicad"]
    assert evaluate_trust("kicad", fork.lock, envs, platform="darwin", policy=POLICY).ready


@pytest.mark.parametrize(
    ("stderr", "code"),
    [
        (
            "WARNING: Retrying ... NewConnectionError('Failed to establish a new connection')",
            "network_unreachable",
        ),
        (
            "Could not fetch URL https://pypi.org/simple/x/: Temporary failure in name resolution",
            "network_unreachable",
        ),
        ("ProxyError('Cannot connect to proxy.')", "network_unreachable"),
        (
            "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.",
            "hash_mismatch",
        ),
        (
            "ERROR: Could not find a version that satisfies the requirement x==1 "
            "(from versions: none)"
            "\nERROR: No matching distribution found for x==1",
            "wheel_unavailable",
        ),
        # SOLUSDEV-329: both seen live on the KiCad lock (large numpy/pandas wheels).
        (
            "WARNING: Connection timed out while downloading.\nerror: incomplete-download",
            "network_unreachable",
        ),
        (
            'pip._vendor.urllib3.exceptions.ProtocolError: ("Connection broken: '
            "BrokenPipeError(32, 'Broken pipe')\", BrokenPipeError(32, 'Broken pipe'))",
            "network_unreachable",
        ),
        ("OSError: [Errno 28] No space left on device", "disk_full"),
        ("ERROR: something else entirely", "pip_failed"),
    ],
)
def test_pip_stderr_maps_to_error_codes(stderr: str, code: str) -> None:
    assert classify_pip_failure(stderr) == code


def test_pip_failure_is_mapped_per_fork(tmp_path: Path) -> None:
    script = ProvisionScript(
        pip={"kicad": ProcResult(1, "", "THESE PACKAGES DO NOT MATCH THE HASHES")}
    )
    outcome = _builder(tmp_path / "envs", FakeRunner(script)).build(
        _fork(tmp_path / "mcp"), _base()
    )
    assert outcome.error_code == "hash_mismatch"
    assert "/" not in outcome.message  # no paths in the wire message


def test_pip_timeout_is_timeout(tmp_path: Path) -> None:
    script = ProvisionScript(pip={"kicad": ProcResult(None, "", "", timed_out=True)})
    outcome = _builder(tmp_path / "envs", FakeRunner(script)).build(
        _fork(tmp_path / "mcp"), _base()
    )
    assert outcome.error_code == "timeout"


@pytest.mark.parametrize(
    ("venv", "code"),
    [
        (ProcResult(1, "", "Error: Command ... returned non-zero exit status 1."), "venv_failed"),
        (ProcResult(1, "", "[Errno 28] No space left on device"), "disk_full"),
        (ProcResult(None, "", "", timed_out=True), "timeout"),
        (ProcResult(None, "", "", launch_error=True), "venv_failed"),
    ],
)
def test_venv_failures(tmp_path: Path, venv: ProcResult, code: str) -> None:
    envs = tmp_path / "envs"
    outcome = _builder(envs, FakeRunner(ProvisionScript(venv=venv))).build(
        _fork(tmp_path / "mcp"), _base()
    )
    assert outcome.error_code == code
    assert list(envs.iterdir()) == []


def test_unhealthy_copy_is_discarded_before_pip(tmp_path: Path) -> None:
    """The probe reports an interpreter outside the env: the copy is not self-contained."""
    envs = tmp_path / "envs"
    runner = FakeRunner(ProvisionScript(health_executable=sys.executable))

    outcome = _builder(envs, runner).build(_fork(tmp_path / "mcp"), _base())

    assert outcome.error_code == "venv_copies_unhealthy"
    assert not any("pip" in argv for argv, _, _ in runner.calls)
    assert list(envs.iterdir()) == []


def test_missing_venv_interpreter_is_unhealthy(tmp_path: Path) -> None:
    def handler(argv: list[str], env: object) -> ProcResult:
        return ProcResult(0, "", "")  # "venv" succeeds but creates nothing

    outcome = _builder(tmp_path / "envs", FakeRunner(handler)).build(
        _fork(tmp_path / "mcp"), _base()
    )
    assert outcome.error_code == "venv_copies_unhealthy"


def test_unsupported_platform_fork_is_skipped(tmp_path: Path) -> None:
    fork = _fork(tmp_path / "mcp", "altium", platforms=["win32"], display="Altium Designer")
    runner = FakeRunner(ProvisionScript())
    outcome = _builder(tmp_path / "envs", runner).build(fork, _base())
    assert outcome.outcome == "skipped" and runner.calls == []
    assert outcome.message == "Altium Designer is not available on macOS"


def test_failure_isolation_across_forks(tmp_path: Path) -> None:
    root = tmp_path / "mcp"
    forks = [_fork(root, "code"), _fork(root, "kicad"), _fork(root, "local")]
    script = ProvisionScript(
        pip={"kicad": ProcResult(1, "", "Failed to establish a new connection")}
    )
    builder = _builder(tmp_path / "envs", FakeRunner(script))

    outcomes = [builder.build(fork, _base()).outcome for fork in forks]

    assert outcomes == ["ok", "failed", "ok"]


def test_cancellation_cleans_the_temp_dir_and_propagates(tmp_path: Path) -> None:
    envs = tmp_path / "envs"

    def cancel(argv: list[str]) -> None:
        raise Cancelled()

    builder = _builder(envs, FakeRunner(ProvisionScript(on_pip=cancel)))
    with pytest.raises(Cancelled):
        builder.build(_fork(tmp_path / "mcp"), _base())
    assert list(envs.iterdir()) == []


def test_managed_base_is_stamped_managed(tmp_path: Path) -> None:
    envs = tmp_path / "envs"
    base = write_exe(tmp_path / "mcp-python" / "r1" / "python" / "bin" / "python3")
    _builder(envs, FakeRunner(ProvisionScript())).build(
        _fork(tmp_path / "mcp"), _base(str(base), managed=True)
    )
    stamp = read_stamp(envs / "kicad" / STAMP_NAME)
    assert stamp is not None and stamp.base.managed is True


def test_count_requirements_counts_pins_only(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("# c\n\na==1 \\\n    --hash=sha256:x\nb==2 ; python_version>'3'\n")
    assert count_requirements(lock) == 2
    assert count_requirements(tmp_path / "absent") == 0


# ----------------------------------------------------------- real venv


def test_real_copies_venv_is_built_and_trusted(tmp_path: Path) -> None:
    """No mocks: `python -m venv --copies` from this interpreter, the real
    health probe, and pip over an EMPTY lock (no network needed)."""
    envs = tmp_path / "envs"
    make_fork(tmp_path / "mcp", "empty", lock="")
    fork = python_forks(tmp_path / "mcp", sys.platform)[0]
    builder = EnvBuilder(
        envs_root=envs,
        runner=run_capped,
        policy=POLICY,
        emit=lambda line: None,
        platform=sys.platform,
        env_source=dict(os.environ),
    )
    POLICY.ensure(envs)

    outcome = builder.build(fork, _base())

    assert outcome.outcome == "ok", outcome
    trust = evaluate_trust("empty", fork.lock, envs, platform=sys.platform, policy=POLICY)
    assert trust.ready, trust.detail
    assert trust.interpreter is not None and not trust.interpreter.is_symlink()
    check = run_capped([str(trust.interpreter), "-I", "-c", "import json"], timeout=30, env={})
    assert check.ok
