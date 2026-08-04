"""Config: ADR-031 discovery + launch guard, instance id, env parsing."""

import os
import stat
import sys
from pathlib import Path

import pytest
from solus_companion.config import (
    TokenBox,
    apply_token_line,
    config_from_env,
    discover_servers,
    load_instance_id,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mcp_root"


def _write_server(
    root: Path, dirname: str, server_field: str, launch_target: Path | None = None
) -> Path:
    """Create `<root>/<dirname>` with an allowlist and a bin/launch entry."""
    server_dir = root / dirname
    (server_dir / "bin").mkdir(parents=True)
    (server_dir / "allowlist.yaml").write_text(f"server: {server_field}\n")
    launch = server_dir / "bin" / "launch"
    if launch_target is not None:
        launch.symlink_to(launch_target)
    else:
        launch.write_text("#!/bin/sh\nexit 0\n")
        launch.chmod(0o755)
    return server_dir


def test_discover_servers_finds_mock_fixture() -> None:
    servers = discover_servers(FIXTURE_ROOT)
    assert [server.name for server in servers] == ["mock"]
    # SEC-L2: the RESOLVED path is returned — the validated target gets executed
    assert servers[0].command == (FIXTURE_ROOT / "mock" / "bin" / "launch").resolve()
    assert servers[0].command.is_absolute()
    assert servers[0].args == ()


# --- H3 (companion half): SOLUS_MCP_WORKSPACE propagation ------------------------


def test_discover_servers_omits_the_workspace_env_when_not_configured() -> None:
    """No `workspace=` given at all — every child's declared env stays
    empty, exactly as before this fix (fail closed: the fork's own
    `workspace_root()` then refuses rather than defaulting to its cwd)."""
    servers = discover_servers(FIXTURE_ROOT)
    assert servers[0].env == {}


def test_discover_servers_omits_the_workspace_env_when_explicitly_none() -> None:
    servers = discover_servers(FIXTURE_ROOT, workspace=None)
    assert servers[0].env == {}


def test_discover_servers_omits_the_workspace_env_when_empty_string() -> None:
    """An empty string is "not configured", not a workspace of the empty
    path — the same optionality `SOLUS_COMPANION_WORKSPACE` documents."""
    servers = discover_servers(FIXTURE_ROOT, workspace="")
    assert servers[0].env == {}


def test_discover_servers_sets_solus_mcp_workspace_on_every_server_when_configured() -> None:
    servers = discover_servers(FIXTURE_ROOT, workspace="/projects/robot")
    assert servers
    for server in servers:
        assert server.env == {"SOLUS_MCP_WORKSPACE": "/projects/robot"}


def test_symlink_escaping_root_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\nexit 0\n")
    outside.chmod(0o755)
    root = tmp_path / "root"
    root.mkdir()
    _write_server(root, "evil", "evil", launch_target=outside)
    assert discover_servers(root) == ()


def test_bin_dir_symlinked_outside_root_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    launch = elsewhere / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n")
    launch.chmod(0o755)
    root = tmp_path / "root"
    (root / "sneaky").mkdir(parents=True)
    (root / "sneaky" / "allowlist.yaml").write_text("server: sneaky\n")
    (root / "sneaky" / "bin").symlink_to(elsewhere, target_is_directory=True)
    assert discover_servers(root) == ()


def test_non_executable_launch_is_refused(tmp_path: Path) -> None:
    server_dir = _write_server(tmp_path, "meek", "meek")
    (server_dir / "bin" / "launch").chmod(0o644)
    assert discover_servers(tmp_path) == ()


def test_missing_launch_is_refused(tmp_path: Path) -> None:
    server_dir = _write_server(tmp_path, "ghost", "ghost")
    (server_dir / "bin" / "launch").unlink()
    assert discover_servers(tmp_path) == ()


def test_server_field_directory_mismatch_is_skipped(tmp_path: Path) -> None:
    _write_server(tmp_path, "foo", "bar")
    assert discover_servers(tmp_path) == ()


def test_unsafe_server_name_is_skipped(tmp_path: Path) -> None:
    _write_server(tmp_path, "Bad_Name", "Bad_Name")
    assert discover_servers(tmp_path) == ()


def test_instance_id_persists_across_loads(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "companion_id"
    first = load_instance_id(path)
    second = load_instance_id(path)
    assert first == second
    assert len(first) == 32
    int(first, 16)  # hex
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_instance_id_replaces_garbage(tmp_path: Path) -> None:
    path = tmp_path / "companion_id"
    path.write_text("not-a-uuid\n")
    fresh = load_instance_id(path)
    assert len(fresh) == 32
    assert load_instance_id(path) == fresh


def _env(tmp_path: Path, url: str, allowed_hosts: str | None = None) -> dict[str, str]:
    env = {
        "SOLUS_COMPANION_URL": url,
        "SOLUS_COMPANION_TOKEN": "tok-1",
        "SOLUS_COMPANION_INTEGRATIONS_ROOT": str(tmp_path / "integrations"),
        "SOLUS_COMPANION_INSTANCE_FILE": str(tmp_path / "companion_id"),
    }
    if allowed_hosts is not None:
        env["SOLUS_COMPANION_ALLOWED_HOSTS"] = allowed_hosts
    return env


def test_config_from_env_requires_wss_for_remote_hosts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="wss"):
        config_from_env(_env(tmp_path, "ws://bridge.solus.dev/api/v1/projects/p/bridge"))


def test_config_from_env_allows_ws_for_localhost(tmp_path: Path) -> None:
    config = config_from_env(_env(tmp_path, "ws://localhost:8000/bridge"))
    assert config.url == "ws://localhost:8000/bridge"
    assert config.token_source() == "tok-1"
    assert config.instance_id == load_instance_id(tmp_path / "companion_id")
    assert config.servers == ()
    assert config.ping_interval == 20.0


def test_config_from_env_workspace_defaults_to_none(tmp_path: Path) -> None:
    """H3 (companion half): `SOLUS_COMPANION_WORKSPACE` is optional — absent
    means the companion serves no fixed project directory, and every server's
    declared env stays empty (the fork then fails closed, per H3's fork half)."""
    config = config_from_env(_env(tmp_path, "ws://localhost:8000/bridge"))
    assert config.workspace is None


def test_config_from_env_reads_the_workspace_when_set(tmp_path: Path) -> None:
    env = _env(tmp_path, "ws://localhost:8000/bridge")
    env["SOLUS_COMPANION_WORKSPACE"] = "/projects/robot"
    config = config_from_env(env)
    assert config.workspace == "/projects/robot"


def test_config_from_env_accepts_wss_when_allowlisted(tmp_path: Path) -> None:
    config = config_from_env(
        _env(tmp_path, "wss://bridge.solus.dev/bridge", allowed_hosts="bridge.solus.dev")
    )
    assert config.url.startswith("wss://")


def test_config_from_env_rejects_remote_host_by_default(tmp_path: Path) -> None:
    # SEC-M2: without explicit consent the bearer never rides to a remote host
    with pytest.raises(ValueError, match="SOLUS_COMPANION_ALLOWED_HOSTS"):
        config_from_env(_env(tmp_path, "wss://evil.example.com/bridge"))


def test_config_from_env_rejects_host_missing_from_allowlist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SOLUS_COMPANION_ALLOWED_HOSTS"):
        config_from_env(
            _env(tmp_path, "wss://evil.example.com/bridge", allowed_hosts="bridge.solus.dev")
        )


def test_allowed_hosts_comma_separated_and_case_insensitive(tmp_path: Path) -> None:
    config = config_from_env(
        _env(
            tmp_path,
            "wss://Bridge.Solus.Dev/bridge",
            allowed_hosts=" staging.solus.dev , bridge.solus.dev ",
        )
    )
    assert config.url == "wss://Bridge.Solus.Dev/bridge"


def test_config_from_env_missing_token_requires_stdin_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No env token: fine when a stdin relay is attached (Electron spawn —
    empty box idles the channel until the first token line); an error on an
    interactive TTY, where no relay will ever arrive."""
    env = _env(tmp_path, "wss://bridge.solus.dev/bridge", allowed_hosts="bridge.solus.dev")
    del env["SOLUS_COMPANION_TOKEN"]
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    config = config_from_env(env)
    assert isinstance(config.token_source, TokenBox)
    assert config.token_source() == ""  # empty box → channel idles
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(ValueError, match="SOLUS_COMPANION_TOKEN"):
        config_from_env(env)


def test_config_from_env_preseeds_token_box(tmp_path: Path) -> None:
    config = config_from_env(
        _env(tmp_path, "wss://bridge.solus.dev/bridge", allowed_hosts="bridge.solus.dev")
    )
    assert isinstance(config.token_source, TokenBox)
    assert config.token_source() == "tok-1"
    assert config.token_source.available.is_set()


def test_token_box_set_get_clear_and_event() -> None:
    box = TokenBox()
    assert box.get() == ""
    assert box() == ""  # callable: slots into CompanionConfig.token_source
    assert not box.available.is_set()
    box.set("tok-a")
    assert box() == "tok-a"
    assert box.available.is_set()
    box.clear()
    assert box.get() == ""
    assert not box.available.is_set()


def test_apply_token_line_token_and_signout() -> None:
    box = TokenBox("old")
    apply_token_line(box, b'{"type":"token","access_token":"new"}')
    assert box() == "new"
    assert box.available.is_set()
    apply_token_line(box, '{"type":"signout"}')
    assert box() == ""
    assert not box.available.is_set()


@pytest.mark.parametrize(
    "line",
    [
        b"not json",
        b"[]",
        b'"a string"',
        b'{"type":"weird"}',
        b'{"type":"token"}',
        b'{"type":"token","access_token":123}',
        b'{"type":"token","access_token":""}',
        b"\xff\xfe",
    ],
)
def test_apply_token_line_garbage_ignored(line: bytes) -> None:
    box = TokenBox("keep")
    apply_token_line(box, line)  # must not raise
    assert box() == "keep"
    assert box.available.is_set()
