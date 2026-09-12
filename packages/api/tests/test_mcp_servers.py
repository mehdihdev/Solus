"""The `brave` catalog spec (SOLUSDEV-252 P6): a vendored, cloud-launched fork.

`WEB_SEARCH` used to be the one knowingly-provisional `npx`-launched spec. It now
binds to `integrations/mcp/brave/bin/launch` and declares how its key reaches
the child: `secret_env` maps an env var NAME to a SecretStore REF — never a
value — and `passthrough_env` names the API-process variables the launcher may
see (the Node interpreter override). The keyless gate stays: every `secret_env`
ref is also a `required_secret`, so a missing key refuses BEFORE any spawn.
"""

import inspect
from pathlib import Path

from solus_api.agent.tools import mcp_servers
from solus_api.agent.tools.mcp_servers import MCP_SERVER_CATALOG, WEB_SEARCH
from solus_api.agent.tools.mcp_tool import LicenseTier

REPO_ROOT = Path(__file__).resolve().parents[3]
FORK = REPO_ROOT / "integrations" / "mcp" / "brave"


def test_web_search_is_the_vendored_brave_fork() -> None:
    assert WEB_SEARCH.name == "brave"
    assert WEB_SEARCH.command == str(FORK / "bin" / "launch")
    assert Path(WEB_SEARCH.command).is_absolute()
    assert WEB_SEARCH.args == ()
    assert WEB_SEARCH.url is None
    assert WEB_SEARCH.license_tier is LicenseTier.FREE
    assert MCP_SERVER_CATALOG["brave"] is WEB_SEARCH
    assert "web_search" not in MCP_SERVER_CATALOG


def test_key_delivery_is_declared_by_name_only() -> None:
    assert WEB_SEARCH.required_secrets == ("brave_api_key",)
    assert dict(WEB_SEARCH.secret_env) == {"BRAVE_API_KEY": "brave_api_key"}
    # Every delivered ref is also gated: no spawn can happen without the key.
    assert set(WEB_SEARCH.secret_env.values()) <= set(WEB_SEARCH.required_secrets)
    assert WEB_SEARCH.passthrough_env == ("SOLUS_NODE_BIN",)
    assert WEB_SEARCH.requires_confirmation is False  # reads; the allowlist agrees


def test_no_package_runner_launches_anything() -> None:
    source = inspect.getsource(mcp_servers)
    assert "npx" not in source and "uvx" not in source
    for spec in MCP_SERVER_CATALOG.values():
        if spec.command is not None:
            assert spec.command.endswith(f"integrations/mcp/{spec.name}/bin/launch")


def test_brave_fork_is_allowlist_gated_at_discovery() -> None:
    # `_stdio_server_allowlist` keys on this file: with it present, discovery
    # skips anything the server advertises that Solus has not allowlisted.
    assert (FORK / "allowlist.yaml").is_file()
    assert (FORK / "bin" / "launch").is_file()
