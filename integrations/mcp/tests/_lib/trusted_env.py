"""A provisioned app-data env that the companion's trust rule accepts, for fork
tests that run real-tree discovery (ADR-031 amendment 2026-11-19, SOLUSDEV-329).

Built with the companion's own stamp model and writer, so the format here can never
drift from what `solus_companion.runtime.trust` checks. POSIX only: the win32 trust
check needs the Windows ACL APIs.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from solus_companion.runtime.stamp import Stamp, StampBase, lock_sha256, write_stamp


def trusted_envs_root(tmp_path: Path, fork_dir: Path) -> Path:
    """`<tmp>/mcp-envs/<fork>` with a fake interpreter and a matching stamp."""
    envs = tmp_path / "mcp-envs"
    env_dir = envs / fork_dir.name
    (env_dir / "bin").mkdir(parents=True)
    for directory in (envs, env_dir):
        os.chmod(directory, 0o700)
    python = env_dir / "bin" / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(stat.S_IRWXU)
    write_stamp(
        env_dir,
        Stamp(
            schema_version=1,
            fork=fork_dir.name,
            lock_sha256=lock_sha256(fork_dir / "requirements.lock.txt"),
            base=StampBase(
                path=sys.executable, version="3.12.7", implementation="cpython", managed=False
            ),  # fmt: skip
            created_at="2026-11-19T00:00:00Z",
        ),
    )
    return envs
