"""Per-fork runtime environment — CAD-00b.

Three gaps this closes, each of which makes a vendored fork non-functional in a
packaged build:

1. **No interpreter.** A fork's `bin/launch` cannot resolve `python3` off PATH
   (the README forbids PATH resolution and a customer machine may not have one),
   and PyInstaller makes `sys.executable` the COMPANION binary, so the obvious
   rewrite re-execs the companion. The companion therefore hands the fork the
   absolute path to its own private-env interpreter.
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

import logging
import os
import stat
from pathlib import Path

import pytest
from solus_companion.config import (
    PRIVATE_ENV_INTERPRETER,
    default_integrations_root,
    discover_servers,
)
from solus_companion.supervisor import child_env


def _server(root: Path, name: str = "mock") -> Path:
    """A minimal vendored server: allowlist + an executable bin/launch."""
    server = root / name
    (server / "bin").mkdir(parents=True)
    (server / "allowlist.yaml").write_text(f"server: {name}\ntools: []\n", encoding="utf-8")
    launch = server / "bin" / "launch"
    launch.write_text('#!/bin/sh\nexec "$SOLUS_MCP_PYTHON" ../solus/server.py\n', encoding="utf-8")
    launch.chmod(launch.stat().st_mode | stat.S_IXUSR)
    return server


def _private_env(server: Path) -> Path:
    interpreter = server / PRIVATE_ENV_INTERPRETER
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("#!/bin/sh\n", encoding="utf-8")
    interpreter.chmod(interpreter.stat().st_mode | stat.S_IXUSR)
    return interpreter


# ------------------------------------------------------------- interpreter


def test_a_fork_is_told_where_its_own_interpreter_is(tmp_path: Path) -> None:
    """The whole point: an absolute path, so `bin/launch` never touches PATH."""
    server = _server(tmp_path)
    interpreter = _private_env(server)

    (launch,) = discover_servers(tmp_path)

    assert launch.env["SOLUS_MCP_PYTHON"] == str(interpreter.resolve())
    assert Path(launch.env["SOLUS_MCP_PYTHON"]).is_absolute()


def test_a_fork_without_a_private_env_is_simply_not_told_about_one(tmp_path: Path) -> None:
    """A server with no dependencies needs no private env; it must still launch
    rather than being refused for lacking one."""
    _server(tmp_path)

    (launch,) = discover_servers(tmp_path)

    assert "SOLUS_MCP_PYTHON" not in launch.env


def test_an_interpreter_escaping_the_root_is_refused(tmp_path: Path) -> None:
    """Same guard as the launch command: a symlinked interpreter must not become
    an arbitrary binary on the customer's machine."""
    outside = tmp_path / "outside" / "python"
    outside.parent.mkdir(parents=True)
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(outside.stat().st_mode | stat.S_IXUSR)
    root = tmp_path / "mcp"
    root.mkdir()
    server = _server(root)
    target = server / PRIVATE_ENV_INTERPRETER
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)

    (launch,) = discover_servers(root)

    assert "SOLUS_MCP_PYTHON" not in launch.env


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
    server = _server(tmp_path)
    interpreter = _private_env(server)
    (server / "solus").mkdir()
    (server / "solus" / "env.allow").write_text("SOLUS_MCP_PYTHON\n", encoding="utf-8")

    (launch,) = discover_servers(tmp_path)
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
