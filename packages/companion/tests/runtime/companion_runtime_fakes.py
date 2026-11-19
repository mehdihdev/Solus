"""Shared fakes for the fork-runtime tests (SOLUSDEV-329).

Imported by bare module name: pytest's default `prepend` import mode puts this
directory on sys.path for the test modules beside it."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from solus_companion.runtime.proc import ProcResult
from solus_companion.runtime.stamp import STAMP_NAME

OK = ProcResult(returncode=0, stdout="", stderr="")

LOCK_TEXT = (
    "anyio==4.4.0 \\\n"
    "    --hash=sha256:" + "a" * 64 + "\n"
    "# a comment\n"
    "idna==3.7 \\\n"
    "    --hash=sha256:" + "b" * 64 + "\n"
)


def probe_json(executable: str, version: str = "3.12.7", implementation: str = "cpython") -> str:
    return json.dumps(
        {"implementation": implementation, "version": version, "executable": executable}
    )


def make_fork(
    root: Path,
    name: str,
    *,
    lock: str | None = LOCK_TEXT,
    platforms: Sequence[str] | None = None,
    display: str = "Thing",
) -> Path:
    """A vendored fork: allowlist + launcher, optionally a lock and platform.json."""
    fork = root / name
    (fork / "bin").mkdir(parents=True)
    (fork / "allowlist.yaml").write_text(f"server: {name}\ntools: []\n", encoding="utf-8")
    launch = fork / "bin" / "launch"
    launch.write_text('#!/bin/sh\nexec "$SOLUS_MCP_PYTHON" -c pass\n', encoding="utf-8")
    launch.chmod(0o755)
    if lock is not None:
        (fork / "requirements.lock.txt").write_text(lock, encoding="utf-8")
    if platforms is not None:
        (fork / "platform.json").write_text(
            json.dumps({"display_name": display, "supported_platforms": list(platforms)}),
            encoding="utf-8",
        )
    return fork


def write_exe(path: Path, text: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def trusted_env(
    envs_root: Path,
    fork: str,
    lock: Path,
    *,
    base_path: str | None = None,
    stamp_fork: str | None = None,
) -> Path:
    """A provisioned env the trust rule accepts; returns its interpreter."""
    envs_root.mkdir(parents=True, exist_ok=True)
    os.chmod(envs_root, 0o700)
    env_dir = envs_root / fork
    env_dir.mkdir(exist_ok=True)
    os.chmod(env_dir, 0o700)
    interpreter = write_exe(env_dir / "bin" / "python")
    stamp = {
        "schema_version": 1,
        "fork": stamp_fork or fork,
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "base": {
            "path": base_path or sys.executable,
            "version": "3.12.7",
            "implementation": "cpython",
            "managed": False,
        },
        "created_at": "2026-11-19T18:04:00Z",
    }
    (env_dir / STAMP_NAME).write_text(json.dumps(stamp), encoding="utf-8")
    return interpreter


Handler = Callable[[list[str], Mapping[str, str]], ProcResult]


class FakeRunner:
    """Records every argv + env; answers through `handler`."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[tuple[list[str], dict[str, str], float]] = []

    def __call__(
        self, argv: Sequence[str], *, timeout: float, env: Mapping[str, str]
    ) -> ProcResult:
        self.calls.append((list(argv), dict(env), timeout))
        return self.handler(list(argv), env)


class ProvisionScript:
    """Simulates venv/probe/pip for the env builder.

    `venv` creates `<tmp>/bin/python`; the probe reports that interpreter
    (or `health_executable`); pip answers from `pip` (per fork name, matched
    against the lock path) or OK."""

    def __init__(
        self,
        *,
        pip: Mapping[str, ProcResult] | None = None,
        venv: ProcResult | None = None,
        health_executable: str | None = None,
        on_pip: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.pip = dict(pip or {})
        self.venv = venv
        self.health_executable = health_executable
        self.on_pip = on_pip

    def __call__(self, argv: list[str], env: Mapping[str, str]) -> ProcResult:
        if "venv" in argv:
            if self.venv is not None:
                return self.venv
            write_exe(Path(argv[-1]) / "bin" / "python")
            return OK
        if "-c" in argv:
            return ProcResult(
                returncode=0, stdout=probe_json(self.health_executable or argv[0]), stderr=""
            )
        if "pip" in argv:
            if self.on_pip is not None:
                self.on_pip(argv)
            lock = argv[-1]
            for fork, result in self.pip.items():
                if f"/{fork}/" in lock:
                    return result
            return OK
        raise AssertionError(f"unexpected argv {argv}")
