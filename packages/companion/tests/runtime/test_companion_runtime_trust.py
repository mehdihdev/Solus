"""Stamp v1 (§4) and the discovery-time trust rule (§5)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from companion_runtime_fakes import make_fork, trusted_env, write_exe
from solus_companion.runtime.forks import python_forks
from solus_companion.runtime.ownership import PosixOwnerOnly
from solus_companion.runtime.stamp import (
    STAMP_NAME,
    Stamp,
    StampBase,
    lock_sha256,
    read_stamp,
    write_stamp,
)
from solus_companion.runtime.trust import evaluate_trust

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mcp_runtime"
POLICY = PosixOwnerOnly()


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    fork = make_fork(tmp_path / "mcp", "kicad")
    lock = fork / "requirements.lock.txt"
    envs = tmp_path / "envs"
    interpreter = trusted_env(envs, "kicad", lock)
    return lock, envs, interpreter


def _trust(lock: Path, envs: Path, fork: str = "kicad"):  # type: ignore[no-untyped-def]
    return evaluate_trust(fork, lock, envs, platform="darwin", policy=POLICY)


# ------------------------------------------------------------------- stamp


def test_fixture_stamp_parses() -> None:
    stamp = read_stamp(FIXTURES / "stamp_v1.json")
    assert stamp is not None
    assert stamp.fork == "kicad" and stamp.base.version == "3.12.7"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(schema_version=2),
        lambda s: s.update(extra=1),
        lambda s: s["base"].update(version="3.11.2"),
        lambda s: s["base"].update(path="relative/python"),
        lambda s: s["base"].update(implementation="pypy"),
        lambda s: s.update(lock_sha256="ABC"),
        lambda s: s.update(fork="../x"),
        lambda s: s.pop("created_at"),
    ],
)
def test_invalid_stamps_are_rejected(tmp_path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    data = json.loads((FIXTURES / "stamp_v1.json").read_text())
    mutate(data)
    path = tmp_path / STAMP_NAME
    path.write_text(json.dumps(data))
    assert read_stamp(path) is None


def test_oversize_or_symlinked_stamp_is_rejected(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_text(" " * 5000 + (FIXTURES / "stamp_v1.json").read_text())
    assert read_stamp(big) is None
    link = tmp_path / "link.json"
    link.symlink_to(FIXTURES / "stamp_v1.json")
    assert read_stamp(link) is None
    assert read_stamp(tmp_path / "absent.json") is None


def test_write_stamp_is_atomic_and_round_trips(tmp_path: Path) -> None:
    stamp = Stamp(
        schema_version=1,
        fork="code",
        lock_sha256="c" * 64,
        base=StampBase(
            path=sys.executable, version="3.12.1", implementation="cpython", managed=True
        ),
        created_at="2026-11-19T18:04:00Z",
    )
    write_stamp(tmp_path, stamp)
    assert read_stamp(tmp_path / STAMP_NAME) == stamp
    assert [p.name for p in tmp_path.iterdir()] == [STAMP_NAME]


# ------------------------------------------------------------------- trust


def test_a_complete_private_env_is_trusted(tmp_path: Path) -> None:
    lock, envs, interpreter = _setup(tmp_path)
    result = _trust(lock, envs)
    assert result.ready and result.detail is None
    assert result.interpreter == interpreter.resolve()
    assert result.stamp is not None and result.stamp.base.version == "3.12.7"


def test_no_env_dir(tmp_path: Path) -> None:
    fork = make_fork(tmp_path / "mcp", "kicad")
    result = _trust(fork / "requirements.lock.txt", tmp_path / "envs")
    assert result.detail == "needs_setup:no_env" and result.interpreter is None


def test_missing_stamp_or_interpreter_is_no_env(tmp_path: Path) -> None:
    lock, envs, interpreter = _setup(tmp_path)
    (envs / "kicad" / STAMP_NAME).unlink()
    assert _trust(lock, envs).detail == "needs_setup:no_env"
    lock, envs, interpreter = _setup(tmp_path / "b")
    interpreter.unlink()
    assert _trust(lock, envs).detail == "needs_setup:no_env"


def test_group_writable_envs_root_is_not_owner_only(tmp_path: Path) -> None:
    lock, envs, _ = _setup(tmp_path)
    os.chmod(envs, 0o770)
    assert _trust(lock, envs).detail == "needs_setup:not_owner_only"


def test_group_readable_env_dir_is_not_owner_only(tmp_path: Path) -> None:
    lock, envs, _ = _setup(tmp_path)
    os.chmod(envs / "kicad", 0o750)
    assert _trust(lock, envs).detail == "needs_setup:not_owner_only"


def test_wrong_owner_is_not_owner_only(tmp_path: Path) -> None:
    lock, envs, _ = _setup(tmp_path)
    foreign = PosixOwnerOnly(euid=lambda: os.geteuid() + 1)
    result = evaluate_trust("kicad", lock, envs, platform="darwin", policy=foreign)
    assert result.detail == "needs_setup:not_owner_only"


def test_lock_change_is_a_stamp_mismatch(tmp_path: Path) -> None:
    lock, envs, _ = _setup(tmp_path)
    lock.write_text(lock.read_text() + "extra==1.0 --hash=sha256:" + "d" * 64 + "\n")
    assert _trust(lock, envs).detail == "needs_setup:stamp_mismatch"


def test_stamp_for_another_fork_is_a_mismatch(tmp_path: Path) -> None:
    fork = make_fork(tmp_path / "mcp", "kicad")
    lock = fork / "requirements.lock.txt"
    trusted_env(tmp_path / "envs", "kicad", lock, stamp_fork="code")
    assert _trust(lock, tmp_path / "envs").detail == "needs_setup:stamp_mismatch"


def test_corrupt_stamp_or_unreadable_lock_is_a_mismatch(tmp_path: Path) -> None:
    lock, envs, _ = _setup(tmp_path)
    (envs / "kicad" / STAMP_NAME).write_text("{not json")
    assert _trust(lock, envs).detail == "needs_setup:stamp_mismatch"
    lock2, envs2, _ = _setup(tmp_path / "b")
    lock2.unlink()
    assert _trust(lock2, envs2).detail == "needs_setup:stamp_mismatch"


def test_base_interpreter_gone_is_base_missing(tmp_path: Path) -> None:
    fork = make_fork(tmp_path / "mcp", "kicad")
    lock = fork / "requirements.lock.txt"
    trusted_env(tmp_path / "envs", "kicad", lock, base_path=str(tmp_path / "gone" / "python3"))
    assert _trust(lock, tmp_path / "envs").detail == "needs_setup:base_missing"


def test_symlink_escaping_interpreter_is_no_env(tmp_path: Path) -> None:
    lock, envs, interpreter = _setup(tmp_path)
    outside = write_exe(tmp_path / "outside" / "python")
    interpreter.unlink()
    interpreter.symlink_to(outside)
    assert _trust(lock, envs).detail == "needs_setup:no_env"


def test_non_executable_interpreter_is_no_env(tmp_path: Path) -> None:
    lock, envs, interpreter = _setup(tmp_path)
    interpreter.chmod(0o600)
    assert _trust(lock, envs).detail == "needs_setup:no_env"


def test_windows_layout_uses_scripts_python_exe(tmp_path: Path) -> None:
    lock, envs, interpreter = _setup(tmp_path)
    exe = write_exe(envs / "kicad" / "Scripts" / "python.exe")
    result = evaluate_trust("kicad", lock, envs, platform="win32", policy=POLICY)
    assert result.ready and result.interpreter == exe.resolve()


def test_lock_sha256_is_hex_of_bytes(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    path.write_bytes(b"abc")
    assert lock_sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ------------------------------------------------------------------- forks


def test_python_forks_are_those_with_a_lock(tmp_path: Path) -> None:
    root = tmp_path / "mcp"
    make_fork(root, "kicad")
    make_fork(root, "code")
    make_fork(root, "mock", lock=None)
    make_fork(root, "altium", platforms=["win32"], display="Altium Designer")
    make_fork(root, "Bad")

    forks = {f.name: f for f in python_forks(root, "darwin")}

    assert sorted(forks) == ["altium", "code", "kicad"]
    assert forks["altium"].unavailable == "Altium Designer is not available on macOS"
    assert forks["kicad"].unavailable is None
    assert forks["kicad"].lock == (root / "kicad" / "requirements.lock.txt").resolve()


def test_a_lock_escaping_the_root_is_ignored(tmp_path: Path) -> None:
    root = tmp_path / "mcp"
    fork = make_fork(root, "kicad", lock=None)
    outside = tmp_path / "outside.txt"
    outside.write_text("x==1\n")
    (fork / "requirements.lock.txt").symlink_to(outside)
    assert python_forks(root, "darwin") == []


def test_missing_root_has_no_forks(tmp_path: Path) -> None:
    assert python_forks(tmp_path / "nope", "darwin") == []
