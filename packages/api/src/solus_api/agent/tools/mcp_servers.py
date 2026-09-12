"""Keyless-safe real MCP server specs + the BYO-license catalog (MCP-01/MCP-05).

Safe to ship without keys or licenses: `required_secrets` are checked against
the SecretStore BEFORE any connection attempt, and every stdio command is an
absolute path to a Solus-authored `bin/launch` inside a vendored fork — so a
spec whose fork is not vendored yet simply fails closed, and nothing here can
spawn or reach a network in tests. Credential DELIVERY is declared by NAME
(`secret_env`: child env var → SecretStore ref) and resolved at spawn by
`mcp_tool._resolve_env`; values never live in a spec, a log line, or a result.

ONSHAPE IS DELIBERATELY ABSENT (SOLUS-ONS-A1). It used to sit here as a
streamable-http spec against `mcp.onshape.com` with an API KEY PAIR
(`onshape_access_key`/`onshape_secret_key`) — a credential that authenticates the
DEVELOPER, not the customer, and so can only ever reach our own documents. Onshape
is reached through the customer's OAuth grant instead: `connectors/onshape_ops.py`
+ `agent/tools/onshape_tools.py`, registered as in-process tools. If Onshape's
announced hosted server ever ships, it slots in behind those same operations.

MCP-05 adds the license tier as catalog DATA: free-tier tools (KiCad, Onshape,
Fusion personal, web search) need no customer license; byo_paid tools (Altium,
SolidWorks, AutoCAD) require the CUSTOMER's own vendor license, captured in the
companion and stored per-team in the SecretStore under `license_secret_ref`.
BYO-paid tools are validated on customer machines via that flow — they are NOT
on the in-house QA path.
"""

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.mcp_tool import LicenseTier, MCPServerSpec
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.core.errors import APIError
from solus_api.models import User
from solus_api.services.limits import check_can_use_byo_tool

# Phase 4 H4 fix: the repo root, anchored from THIS FILE's fixed location —
# never the process's ambient CWD/PATH. `Settings.bridge_allowlist_root`
# resolves its own repo-relative path against the process CWD (trusted to be
# the repo root only at app-boot time, in main.py); a subprocess SPAWN
# happens much later, per tool invocation, so it must not depend on which
# directory happened to launch the API/worker process (CLAUDE.md §7: pinned
# binaries, never PATH/CWD-resolved).
_REPO_ROOT: Final = Path(__file__).resolve().parents[6]


def _fork_launcher(relative_path: str) -> str:
    """Resolve a vendored MCP fork's launcher script to an ABSOLUTE path
    anchored at `_REPO_ROOT`. Existence is intentionally NOT checked here:
    a fork may or may not be vendored yet (KICAD's `bin/launch` has landed;
    FUSION's has not, per MCP-03) — either way, spawning an absolute path
    fails closed on a missing file, and never silently falls back to
    resolving a same-named binary from PATH."""
    return str(_REPO_ROOT / relative_path)


# SOLUSDEV-252 P6: the vendored Brave Search fork (ADR-031 Pattern 1), launched
# CLOUD-SIDE by the API — the companion ships no Node. The constant name is kept
# (`core/startup_checks.py` and `scripts/seed-provider-keys.py` import it); the
# SERVER name is `brave`, matching the fork directory and its allowlist.yaml, so
# the discovery filter and the launcher's own roster trimming agree.
#
# `secret_env` declares key delivery by NAME: the value is read from the
# SecretStore at spawn and put only into the child environment. `passthrough_env`
# forwards the absolute Node path when one is not at a fixed location (nvm boxes);
# `bin/launch` refuses a relative or PATH-shaped value.
WEB_SEARCH = MCPServerSpec(
    name="brave",
    command=_fork_launcher("integrations/mcp/brave/bin/launch"),
    required_secrets=("brave_api_key",),
    secret_env={"BRAVE_API_KEY": "brave_api_key"},
    passthrough_env=("SOLUS_NODE_BIN",),
)

# MCP-05 free tier — usable on any plan, no customer license. Phase 4 H4:
# pinned to an ABSOLUTE path (`_fork_launcher`) rather than a bare repo-relative
# string, so a spawn can never depend on the process's ambient working directory.
KICAD = MCPServerSpec(name="kicad", command=_fork_launcher("integrations/mcp/kicad/bin/launch"))

# FUSION IS NOT A FORK (CAD-02). Autodesk ships its own MCP server, and it runs
# on the CUSTOMER's machine — Preferences → General → API → "Fusion MCP Server
# (Runs locally on this device)", default port 27182, available on the free
# Personal tier. There is nothing to vendor: no bin/launch, no private env, no
# PROVENANCE, no fork security review.
#
# It is reached through the COMPANION, never from the cloud, and that is a
# LICENSING REQUIREMENT rather than a networking detail: Autodesk prohibits
# hosting or multiplexing a licensed seat, so running Fusion server-side and
# exposing it to several users through Solus would breach the EULA. Solus acts
# as a local client of the individual user's own authorized seat. (The legal
# route for any future cloud-side automation is the Fusion Automation API via
# APS, pay-per-use — not this server.)
#
# This spec therefore documents the endpoint for the catalog; the companion owns
# the connection and pins it to loopback. Tool names come from `tools/list` at
# connect and are never hardcoded — the server is closed source and its tooling
# is dynamic.
FUSION_LOOPBACK_URL = "http://127.0.0.1:27182/mcp"
FUSION = MCPServerSpec(
    name="fusion",
    url=FUSION_LOOPBACK_URL,
    connect_notice=(
        "Fusion Personal is licensed for non-commercial use only, and for generating "
        "under $1,000 per year. Commercial work needs a paid Fusion subscription. "
        "Solus drives the Fusion running on this machine under your own licence."
    ),
)

# MCP-05 BYO-paid tier — the customer brings their own vendor license.
# `license_secrets` are per-team credential KEY NAMES (values only ever live in
# the SecretStore); validated customer-side, never on the in-house QA path.
ALTIUM = MCPServerSpec(
    name="altium",
    command=_fork_launcher("integrations/mcp/altium/bin/launch"),
    license_tier=LicenseTier.BYO_PAID,
    license_secrets=("altium_license",),
)
SOLIDWORKS = MCPServerSpec(
    name="solidworks",
    command=_fork_launcher("integrations/mcp/solidworks/bin/launch"),
    license_tier=LicenseTier.BYO_PAID,
    license_secrets=("solidworks_serial",),
)
AUTOCAD = MCPServerSpec(
    name="autocad",
    command=_fork_launcher("integrations/mcp/autocad/bin/launch"),
    license_tier=LicenseTier.BYO_PAID,
    license_secrets=("autocad_license",),
)

MCP_SERVER_CATALOG: dict[str, MCPServerSpec] = {
    spec.name: spec for spec in (WEB_SEARCH, KICAD, FUSION, ALTIUM, SOLIDWORKS, AUTOCAD)
}


def license_secret_ref(team_id: uuid.UUID, server: str, key: str) -> str:
    """The MCP-05 tenant-scoped SecretStore ref for one BYO license credential:
    `mcp-license/<team_id>/<server_name>/<key_name>`. The ONE definition — used
    by the invoke-time gate, the bridge capture handler, and the status surface,
    so the write ref and the read ref can never drift."""
    return f"mcp-license/{team_id}/{server}/{key}"


def build_license_preflight(
    spec: MCPServerSpec,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    secret_store: SecretStore | None,
) -> Callable[[], Awaitable[None]]:
    """The MCP-05 invoke-time gate for a byo_paid server (runs BEFORE any
    transport work): (a) plan entitlement for the ACTING user — an `APIError`
    becomes a ToolException carrying the upgrade message, never the raw repr;
    (b) every `license_secrets` key present under the tenant-scoped ref —
    missing keys are NAMED (names only, never values). No secret_store wired
    means every key is missing: a paid feature fails closed, never open."""

    async def _preflight() -> None:
        async with session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:  # defensive: the request authenticated this id
                raise ToolException(
                    f"unknown user for {spec.name!r}",
                    code=ToolErrorCode.UNAUTHORIZED,
                    retryable=False,
                )
            try:
                await check_can_use_byo_tool(session, user, spec.name)
            except APIError as exc:
                raise ToolException(
                    exc.message, code=ToolErrorCode.UNAUTHORIZED, retryable=False
                ) from exc
        missing: list[str] = []
        for key in spec.license_secrets:
            if secret_store is None:
                missing.append(key)
                continue
            try:
                await secret_store.get(license_secret_ref(team_id, spec.name, key))
            except SecretNotFoundError:
                missing.append(key)
        if missing:
            raise ToolException(
                f"Bring your license: configure your {spec.name} license in the "
                f"Solus companion (missing: {', '.join(missing)})",
                code=ToolErrorCode.UNAUTHORIZED,
                retryable=False,
            )

    return _preflight
