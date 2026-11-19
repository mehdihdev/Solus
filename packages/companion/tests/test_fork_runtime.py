"""Per-fork runtime environment — CAD-00b.

Three gaps this closes, each of which makes a vendored fork non-functional in a
packaged build:

1. **No interpreter.** A fork's `bin/launch` cannot resolve `python3` off PATH
   (the README forbids PATH resolution and a customer machine may not have one),
   and PyInstaller makes `sys.executable` the COMPANION binary, so the obvious
   rewrite re-execs the companion. The companion therefore hands the fork the
   absolute path to its own private-env interpreter — since SOLUSDEV-329 an env
   in the OS app-data folder, accepted only by the mcp-fork-runtime.md §5 trust
   rule; a locked fork without one is `not_launched` with `needs_setup:<code>`.
2. **No cwd.** Without one the fork inherits the companion's working directory,
   contradicting the launch contract.
3. **No env.** `ServerLaunch.env` was declared and never populated, so every
   fork child got exactly `{PATH, HOME}` — a fork needing a license-server host
   or a tool path could not be told about it.

Plus the two silent footguns: an integrations root that is missing or empty is
indistinguishable from a correct-but-empty one, and the README's `allowlist.yaml`
example did not load.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import sys
from pathlib import Path

import pytest
from solus_companion.config import (
    default_integrations_root,
    discover_servers,
)
from solus_companion.supervisor import child_env

LOCK = "anyio==4.4.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"


def _server(root: Path, name: str = "mock", *, lock: bool = False) -> Path:
    """A minimal vendored server: allowlist + an executable bin/launch."""
    server = root / name
    (server / "bin").mkdir(parents=True)
    (server / "allowlist.yaml").write_text(f"server: {name}\ntools: []\n", encoding="utf-8")
    launch = server / "bin" / "launch"
    launch.write_text('#!/bin/sh\nexec "$SOLUS_MCP_PYTHON" ../solus/server.py\n', encoding="utf-8")
    launch.chmod(launch.stat().st_mode | stat.S_IXUSR)
    if lock:
        (server / "requirements.lock.txt").write_text(LOCK, encoding="utf-8")
    return server


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _trusted_env(envs: Path, server: Path, *, lock_sha: str | None = None) -> Path:
    """A provisioned app-data env the §5 trust rule accepts."""
    envs.mkdir(parents=True, exist_ok=True)
    os.chmod(envs, 0o700)
    env_dir = envs / server.name
    env_dir.mkdir()
    os.chmod(env_dir, 0o700)
    interpreter = _exe(env_dir / "bin" / "python")
    lock_bytes = (server / "requirements.lock.txt").read_bytes()
    stamp = {
        "schema_version": 1,
        "fork": server.name,
        "lock_sha256": lock_sha or hashlib.sha256(lock_bytes).hexdigest(),
        "base": {
            "path": sys.executable,
            "version": "3.12.7",
            "implementation": "cpython",
            "managed": False,
        },
        "created_at": "2026-11-19T18:04:00Z",
    }
    (env_dir / "solus-stamp.json").write_text(json.dumps(stamp), encoding="utf-8")
    return interpreter


# ------------------------------------------------------------- interpreter


def test_a_fork_is_told_where_its_trusted_env_interpreter_is(tmp_path: Path) -> None:
    """The whole point: an absolute path into the app-data env, so `bin/launch`
    never touches PATH or the read-only bundle."""
    server = _server(tmp_path / "mcp", lock=True)
    interpreter = _trusted_env(tmp_path / "envs", server)

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason is None
    assert launch.env["SOLUS_MCP_PYTHON"] == str(interpreter.resolve())
    assert Path(launch.env["SOLUS_MCP_PYTHON"]).is_absolute()


def test_a_fork_without_a_lock_needs_no_env(tmp_path: Path) -> None:
    """No lockfile, no Python deps: the fork launches and is told no interpreter."""
    _server(tmp_path / "mcp")

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason is None
    assert "SOLUS_MCP_PYTHON" not in launch.env


def test_a_locked_fork_without_an_env_is_not_launched_with_needs_setup(tmp_path: Path) -> None:
    _server(tmp_path / "mcp", lock=True)

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason == "needs_setup:no_env"
    assert launch.command is None and "SOLUS_MCP_PYTHON" not in launch.env


def test_an_in_tree_venv_is_ignored(tmp_path: Path) -> None:
    """ADR-031 amendment: `<fork>/.venv` is never an interpreter source again."""
    locked = _server(tmp_path / "mcp", "kicad", lock=True)
    _exe(locked / ".venv" / "bin" / "python")
    plain = _server(tmp_path / "mcp", "mock")
    _exe(plain / ".venv" / "bin" / "python")

    launches = {s.name: s for s in discover_servers(tmp_path / "mcp", envs_root=tmp_path / "e")}

    assert launches["kicad"].unavailable_reason == "needs_setup:no_env"
    assert "SOLUS_MCP_PYTHON" not in launches["mock"].env


def test_an_interpreter_escaping_its_env_is_refused(tmp_path: Path) -> None:
    """A symlinked interpreter must not become an arbitrary binary."""
    server = _server(tmp_path / "mcp", lock=True)
    interpreter = _trusted_env(tmp_path / "envs", server)
    outside = _exe(tmp_path / "outside" / "python")
    interpreter.unlink()
    interpreter.symlink_to(outside)

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason == "needs_setup:no_env"


def test_a_lock_change_is_a_stamp_mismatch(tmp_path: Path) -> None:
    server = _server(tmp_path / "mcp", lock=True)
    _trusted_env(tmp_path / "envs", server, lock_sha="f" * 64)

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason == "needs_setup:stamp_mismatch"


def test_a_group_readable_env_is_not_owner_only(tmp_path: Path) -> None:
    server = _server(tmp_path / "mcp", lock=True)
    _trusted_env(tmp_path / "envs", server)
    os.chmod(tmp_path / "envs", 0o750)

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason == "needs_setup:not_owner_only"


def test_the_envs_root_defaults_from_the_dev_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _server(tmp_path / "mcp", lock=True)
    interpreter = _trusted_env(tmp_path / "envs", server)
    monkeypatch.setenv("SOLUS_COMPANION_MCP_ENVS_ROOT", str(tmp_path / "envs"))

    (launch,) = discover_servers(tmp_path / "mcp")

    assert launch.env["SOLUS_MCP_PYTHON"] == str(interpreter.resolve())


def test_a_relative_envs_override_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _server(tmp_path / "mcp", lock=True)
    monkeypatch.setenv("SOLUS_COMPANION_MCP_ENVS_ROOT", "relative/envs")

    (launch,) = discover_servers(tmp_path / "mcp")

    assert launch.unavailable_reason == "needs_setup:no_env"


def test_platform_refusal_still_wins_over_needs_setup(tmp_path: Path) -> None:
    server = _server(tmp_path / "mcp", lock=True)
    (server / "platform.json").write_text(
        json.dumps({"display_name": "Altium Designer", "supported_platforms": ["win32"]})
    )

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")

    assert launch.unavailable_reason is not None
    assert not launch.unavailable_reason.startswith("needs_setup")


# --------------------------------------------------------------------- cwd


def test_a_fork_runs_in_its_own_directory(tmp_path: Path) -> None:
    server = _server(tmp_path)

    (launch,) = discover_servers(tmp_path)

    assert launch.cwd == server.resolve()


# --------------------------------------------------------------------- env


def test_a_fork_inherits_only_what_it_declared(tmp_path: Path) -> None:
    """`solus/env.allow` is Solus-authored, one variable name per line. Anything
    not listed stays out of the child — secret hygiene is the default."""
    server = _server(tmp_path)
    (server / "solus").mkdir()
    (server / "solus" / "env.allow").write_text(
        "# the fork's license server\nSW_LICENSE_HOST\n\nSW_LICENSE_PORT\n", encoding="utf-8"
    )

    (launch,) = discover_servers(tmp_path)
    env = child_env(
        dict(launch.env),
        launch.env_passthrough,
        source={"SW_LICENSE_HOST": "lic.example", "AWS_SECRET_ACCESS_KEY": "nope", "PATH": "/bin"},
    )

    assert env["SW_LICENSE_HOST"] == "lic.example"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # An allowlisted name that is not set simply does not appear.
    assert "SW_LICENSE_PORT" not in env


def test_a_fork_with_no_env_file_inherits_nothing_extra(tmp_path: Path) -> None:
    _server(tmp_path)

    (launch,) = discover_servers(tmp_path)
    env = child_env(dict(launch.env), launch.env_passthrough, source={"ANYTHING": "x"})

    assert "ANYTHING" not in env


def test_declared_env_cannot_be_overridden_by_the_ambient_environment(tmp_path: Path) -> None:
    """The interpreter path is ours to set. A hostile ambient value must not win."""
    server = _server(tmp_path / "mcp", lock=True)
    interpreter = _trusted_env(tmp_path / "envs", server)
    (server / "solus").mkdir()
    (server / "solus" / "env.allow").write_text("SOLUS_MCP_PYTHON\n", encoding="utf-8")

    (launch,) = discover_servers(tmp_path / "mcp", envs_root=tmp_path / "envs")
    env = child_env(
        dict(launch.env), launch.env_passthrough, source={"SOLUS_MCP_PYTHON": "/tmp/evil"}
    )

    assert env["SOLUS_MCP_PYTHON"] == str(interpreter.resolve())


def test_an_env_allow_entry_that_is_not_a_variable_name_is_ignored(tmp_path: Path) -> None:
    server = _server(tmp_path)
    (server / "solus").mkdir()
    (server / "solus" / "env.allow").write_text("PATH=/evil\nOK_NAME\n", encoding="utf-8")

    (launch,) = discover_servers(tmp_path)

    assert launch.env_passthrough == ("OK_NAME",)


# ------------------------------------------------------------- packaged root


def test_the_packaged_layout_gives_the_integrations_root_a_default(tmp_path: Path) -> None:
    """`SOLUS_COMPANION_INTEGRATIONS_ROOT` was required with no default and the
    desktop app never set it, so a packaged companion died at config validation
    while shipping the tree right next to itself."""
    binary = tmp_path / "solus-companion"
    binary.write_text("", encoding="utf-8")
    (tmp_path / "mcp").mkdir()

    assert default_integrations_root(str(binary)) == tmp_path / "mcp"


def test_the_macos_onedir_layout_finds_the_tree_beside_the_binary(tmp_path: Path) -> None:
    """macOS builds --onedir (sol-drive.md §5): the binary sits in its own folder,
    `<resources>/companion/solus-companion/solus-companion`, with `mcp/` beside
    it — never the onefile spot one level up."""
    bundle = tmp_path / "solus-companion"
    bundle.mkdir()
    binary = bundle / "solus-companion"
    binary.write_text("", encoding="utf-8")
    (bundle / "mcp").mkdir()
    (tmp_path / "mcp").mkdir()  # a stale onefile-era tree must not be picked up

    assert default_integrations_root(str(binary)) == bundle / "mcp"


def test_no_default_is_invented_when_the_tree_is_not_there(tmp_path: Path) -> None:
    """A wrong default is worse than none: it would turn a packaging mistake into
    a silent zero-server run."""
    assert default_integrations_root(str(tmp_path / "solus-companion")) is None


def test_discovery_warns_rather_than_silently_finding_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A wrong root and a correct-but-empty one produced identical silence: the
    glob simply yielded nothing. An operator has to be able to tell them apart."""
    with caplog.at_level(logging.WARNING, logger="solus.companion.config"):
        servers = discover_servers(tmp_path / "does-not-exist")

    assert servers == ()
    assert any("no MCP servers" in record.message for record in caplog.records)


def test_the_launch_script_never_resolves_the_interpreter_off_path() -> None:
    """The in-repo fixture is the worked example a fork copies; if IT does a PATH
    lookup, every fork will."""
    launch = (
        Path(__file__).parent / "fixtures" / "mcp_root" / "mock" / "bin" / "launch"
    ).read_text(encoding="utf-8")

    assert "/usr/bin/env" not in launch
    assert launch.startswith("#!/bin/sh")


def test_the_fixture_launcher_is_executable() -> None:
    launch = Path(__file__).parent / "fixtures" / "mcp_root" / "mock" / "bin" / "launch"

    assert os.access(launch, os.X_OK)
