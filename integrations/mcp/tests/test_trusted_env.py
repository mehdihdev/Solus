"""The `_lib.trusted_env` fixture builds exactly what the companion's trust rule
accepts — checked against the real `evaluate_trust`, not a copy of it (SOLUSDEV-329)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from solus_companion.runtime.ownership import PosixOwnerOnly
from solus_companion.runtime.trust import evaluate_trust

MCP_ROOT = Path(__file__).resolve().parents[1]
_LIB = str(MCP_ROOT / "tests" / "_lib")  # the repo's shared-helper convention (altium_paths)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
from trusted_env import trusted_envs_root  # noqa: E402  # isort: skip

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX fixture")


@pytest.mark.parametrize("fork", ["code", "kicad", "local"])
def test_the_fixture_env_passes_the_companion_trust_rule(tmp_path: Path, fork: str) -> None:
    fork_dir = MCP_ROOT / fork
    envs = trusted_envs_root(tmp_path, fork_dir)

    result = evaluate_trust(
        fork, fork_dir / "requirements.lock.txt", envs, platform=sys.platform,
        policy=PosixOwnerOnly(),
    )  # fmt: skip

    assert result.ready, result.detail


def test_a_lock_change_after_the_fixture_is_built_is_refused(tmp_path: Path) -> None:
    fork_dir = tmp_path / "code"
    fork_dir.mkdir()
    lock = fork_dir / "requirements.lock.txt"
    lock.write_text("mcp==1.0 --hash=sha256:" + "a" * 64 + "\n")
    envs = trusted_envs_root(tmp_path, fork_dir)
    lock.write_text("mcp==2.0 --hash=sha256:" + "b" * 64 + "\n")

    result = evaluate_trust("code", lock, envs, platform=sys.platform, policy=PosixOwnerOnly())

    assert not result.ready
    assert result.detail == "needs_setup:stamp_mismatch"
