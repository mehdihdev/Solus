"""MCP tools as a W0-04 `Tool` kind (SOLUSDEV-153 MCP-01).

The contract's anticipated `MCPTool` (docs/contracts/agent-tool.md §2): forwards a
call to an external MCP server via the official `mcp` SDK and maps every outcome
back into W0-04 error semantics, so the registry's never-raises invariant holds
across the wire. The `mcp` SDK is imported ONLY in this module — the registry,
runtime, and `tools/__init__` stay MCP-ignorant; consumers import
`solus_api.agent.tools.mcp_tool` directly.

Everything a server advertises is UNTRUSTED ingested content (CLAUDE.md §7):
names must match a safe pattern, description/error text is length-capped,
schemas are size-bounded and `$ref`-bearing input schemas rejected, and binary
result content is never inlined (W0-04 ArtifactRef rule).

Residual limits, flagged for follow-on tickets: SecretStore keys are a flat v1
namespace — per-TENANT credential scoping must bind where the SOL-loop wiring
constructs registries per request (mirror `get_entity`'s constructor-bound
scope); schema STRING LEAVES (titles, enum values) remain untrusted text the
model reads — size-bounded here, not sanitized; credential DELIVERY to servers
is deliberately unbuilt until MCP-03/MCP-05 (presence is checked, values never
leave the store).
"""

import asyncio
import enum
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final, Self

from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as RemoteTool
from pydantic import BaseModel, ConfigDict, model_validator

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import (
    SAFE_REMOTE_NAME as _SAFE_REMOTE_NAME,
)
from solus_api.agent.tools.untrusted import (
    UNTRUSTED_TEXT_CAP as _UNTRUSTED_TEXT_CAP,
)
from solus_api.agent.tools.untrusted import (
    schema_oversized,
)
from solus_api.agent.tools.untrusted import (
    unsafe_schema_reason as _unsafe_schema_reason,
)
from solus_api.bridge.allowlist import AllowedTool, load_allowlist
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore

logger = logging.getLogger("solus.tools.mcp")

_FALLBACK_RETURNS: dict[str, Any] = {"type": "object"}
# Discovery runs OUTSIDE the registry (wiring time), so it carries its own bound.
DISCOVERY_TIMEOUT_SECONDS = 30.0
# Phase 4 H4: the SAME repo-relative convention `Settings.bridge_allowlist_root`
# uses (one `allowlist.yaml` per vendored fork under `integrations/mcp/<server>/`).
DEFAULT_ALLOWLIST_ROOT: Final = "integrations/mcp"


class LicenseTier(enum.StrEnum):
    """How a server's underlying tool is licensed (SOLUSDEV-153 MCP-05).

    FREE: usable on any plan with no customer license (KiCad, Onshape free,
    Fusion personal). BYO_PAID: the CUSTOMER brings their own paid vendor
    license (Altium, SolidWorks, AutoCAD) — plan-entitled AND license-credential
    gated at invoke time; validated on customer machines, never on the in-house
    QA path."""

    FREE = "free"
    BYO_PAID = "byo_paid"


class MCPServerSpec(BaseModel):
    """Where an MCP server lives and which SecretStore KEYS it needs (never
    values). Exactly one transport: stdio (`command`) or streamable-http (`url`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    command: str | None = None  # stdio: executable to spawn
    args: tuple[str, ...] = ()  # stdio: argv after the command
    env: Mapping[str, str] | None = None  # stdio: extra environment for the child
    url: str | None = None  # streamable-http endpoint
    required_secrets: tuple[str, ...] = ()  # SecretStore key names
    # MCP-05 BYO-license tiering. `license_secrets` are the per-TEAM license
    # credential KEY NAMES a byo_paid tool needs — distinct from
    # `required_secrets` (cloud-key semantics, MCP-01, unchanged). Values live
    # only in the SecretStore under `license_secret_ref(...)`.
    license_tier: LicenseTier = LicenseTier.FREE
    license_secrets: tuple[str, ...] = ()
    # Solus-authored blanket flag: every tool discovered from this server gets the
    # W0-04 confirmation gate. The server's own destructiveHint is untrusted and
    # deliberately ignored (per the MCP SDK's own warning about annotations).
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def _exactly_one_transport(self) -> Self:
        if (self.command is None) == (self.url is None):
            raise ValueError("exactly one transport: set command (stdio) or url (streamable-http)")
        return self


@asynccontextmanager
async def _open_session(spec: MCPServerSpec) -> AsyncIterator[ClientSession]:
    """Fresh connect → initialize. `async with` throughout so a registry-level
    cancellation (its timeout) still runs transport cleanup. Note the bound is
    soft for stdio: the SDK's shutdown path may add ~2s of SIGTERM grace before
    the caller sees the TIMEOUT result."""
    if spec.command is not None:
        params = StdioServerParameters(
            command=spec.command,
            args=list(spec.args),
            env=dict(spec.env) if spec.env is not None else None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return
    if spec.url is None:  # pragma: no cover — the spec validator forbids this
        raise ToolException(f"MCP server {spec.name!r} has no transport configured")
    async with streamablehttp_client(spec.url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _missing_secrets(spec: MCPServerSpec, store: SecretStore) -> list[str]:
    missing: list[str] = []
    for key in spec.required_secrets:
        try:
            await store.get(key)
        except SecretNotFoundError:
            missing.append(key)
    return missing


def _credentials_error(spec: MCPServerSpec, missing: list[str]) -> ToolException:
    # Mirrors ProviderCredentialsMissingError (MO-01): name the missing KEYS so
    # the fix is actionable; secret VALUES never appear in any message.
    return ToolException(
        f"MCP server {spec.name!r} requires credentials: configure "
        f"{', '.join(missing)} in the SecretStore",
        code=ToolErrorCode.UNAUTHORIZED,
        retryable=False,
    )


def _map_result(result: CallToolResult) -> dict[str, Any]:
    """CallToolResult → the W0-04 `value` dict; a server-reported error becomes
    a typed ToolException (its text is untrusted → capped)."""
    if result.isError:
        text = " ".join(block.text for block in result.content if isinstance(block, TextContent))
        raise ToolException(
            (text or "MCP tool reported an error")[:_UNTRUSTED_TEXT_CAP],
            code=ToolErrorCode.TOOL_ERROR,
        )
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    blocks: list[dict[str, Any]] = []
    for block in result.content:
        if isinstance(block, TextContent):
            blocks.append(block.model_dump(mode="json"))
        else:
            # W0-04: large/binary payloads travel as ArtifactRefs, NEVER inlined —
            # an image/audio/resource block is summarized and its data dropped.
            # ponytail: real ArtifactRef persistence lands with the artifacts wiring.
            blocks.append(
                {
                    "type": block.type,
                    "inlined": False,
                    "note": "non-text content omitted (ArtifactRef plumbing pending)",
                }
            )
    return {"content": blocks}


class MCPTool:
    """W0-04 `Tool` kind: one remote tool on an external MCP server.

    `invoke` raises only `ToolException`; transport failures, protocol errors,
    server-reported errors, and missing credentials all become typed failures the
    registry turns into `ToolResult(ok=False)`. Timeouts belong to the registry.
    """

    # ponytail: per-call session (connect → initialize → call → close); pool/reuse
    # when latency matters.

    def __init__(
        self,
        *,
        spec: MCPServerSpec,
        remote_name: str,
        descriptor: ToolDescriptor,
        secret_store: SecretStore,
    ) -> None:
        self._spec = spec
        self._remote_name = remote_name
        self._descriptor = descriptor
        self._secret_store = secret_store

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        missing = await _missing_secrets(self._spec, self._secret_store)
        if missing:  # checked BEFORE any connection attempt
            raise _credentials_error(self._spec, missing)
        try:
            async with _open_session(self._spec) as session:
                result = await session.call_tool(self._remote_name, args)
        except ToolException:
            raise
        except McpError as exc:
            raise ToolException(
                f"MCP server {self._spec.name!r} protocol error: {str(exc)[:_UNTRUSTED_TEXT_CAP]}",
                code=ToolErrorCode.TOOL_ERROR,
            ) from exc
        except Exception as exc:
            # Spawn/connect/transport failure — anyio surfaces these in several
            # shapes, so the catch stays broad and retryable=True is the transport
            # assumption. An internal bug lands here too: the traceback below is
            # the operator's signal; the model sees only the server NAME.
            logger.warning(
                "MCP server %r unreachable (%s)",
                self._spec.name,
                type(exc).__name__,
                exc_info=exc,
            )
            raise ToolException(
                f"MCP server {self._spec.name!r} is unavailable",
                code=ToolErrorCode.TOOL_ERROR,
                retryable=True,
            ) from exc
        return _map_result(result)


def _skip(spec: MCPServerSpec, remote_name: str, reason: str) -> None:
    # %.64r bounds the server-authored name inside our own log lines.
    logger.warning("MCP server %r tool %.64r %s; skipping", spec.name, remote_name, reason)


def _descriptor_safe(spec: MCPServerSpec, remote: RemoteTool) -> bool:
    """Gate one server-advertised tool through the shared untrusted-input checks."""
    if _SAFE_REMOTE_NAME.fullmatch(remote.name) is None:
        _skip(spec, remote.name, "has an unsafe name")
        return False
    if remote.outputSchema is not None and schema_oversized(remote.outputSchema):
        _skip(spec, remote.name, "advertises an oversized schema")
        return False
    reason = _unsafe_schema_reason(remote.inputSchema)
    if reason is not None:
        _skip(spec, remote.name, reason)
        return False
    return True


def _stdio_server_allowlist(
    spec: MCPServerSpec, allowlist_root: str | Path
) -> dict[str, AllowedTool] | None:
    """Phase 4 H4: the per-tool allowlist gate for a STDIO spec, or `None` if
    no `allowlist.yaml` exists for this server (no fork dir vendored/ratified
    yet) — in which case discovery falls back to the spec's own blanket
    `requires_confirmation` flag, unchanged. Only `command`-transport specs
    are gated this way; a `url` (streamable-http) spec (e.g. Onshape) has no
    vendored fork and is out of scope for this allowlist mechanism.

    Reuses the SAME loader the bridge path uses (`bridge/allowlist.py`,
    ADR-031) so the two enforcement points — this direct-connect discovery
    path and the bridge's `validate_inventory` — can never drift on what
    "allowlisted" means."""
    if spec.command is None:
        return None
    root = Path(allowlist_root)
    if not (root / spec.name / "allowlist.yaml").is_file():
        return None
    return load_allowlist(root).servers.get(spec.name)


async def discover_mcp_tools(
    spec: MCPServerSpec,
    secret_store: SecretStore,
    *,
    timeout_seconds: float = DISCOVERY_TIMEOUT_SECONDS,
    allowlist_root: str | Path = DEFAULT_ALLOWLIST_ROOT,
) -> list[MCPTool]:
    """Connect once, `list_tools()`, and build one `MCPTool` per remote tool.

    Discovery runs OUTSIDE the registry (wiring time), so it carries its own
    timeout and maps failures into the same `ToolException` vocabulary as
    `invoke`. Descriptor mapping: names are `{spec.name}.{remote_name}` (registry
    names must be unique across servers); descriptions are untrusted → capped;
    params are the remote inputSchema verbatim — gated by `_descriptor_safe`, and
    a tool failing any guard is SKIPPED (warning) so one bad remote tool can
    never break discovery or a later `ToolRegistry.register`.

    Phase 4 H4: a STDIO spec whose fork dir HAS an `allowlist.yaml`
    (`_stdio_server_allowlist`) is gated per-tool exactly like the bridge path
    (ADR-031) — a remote tool not listed there is skipped, and
    `requires_confirmation` comes ONLY from the allowlist entry, never the
    spec's own blanket flag. Without an allowlist.yaml for the server (no
    fork vendored yet, or a `url`-transport spec), the spec's blanket flag is
    the fallback, unchanged from before this fix.
    """
    missing = await _missing_secrets(spec, secret_store)
    if missing:  # fail fast — no connection without credentials
        raise _credentials_error(spec, missing)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with _open_session(spec) as session:
                listing = await session.list_tools()
    except TimeoutError as exc:
        raise ToolException(
            f"MCP server {spec.name!r} timed out during discovery",
            code=ToolErrorCode.TIMEOUT,
            retryable=True,
        ) from exc
    except McpError as exc:
        raise ToolException(
            f"MCP server {spec.name!r} protocol error: {str(exc)[:_UNTRUSTED_TEXT_CAP]}",
            code=ToolErrorCode.TOOL_ERROR,
        ) from exc
    except Exception as exc:
        logger.warning(
            "MCP server %r unreachable (%s)", spec.name, type(exc).__name__, exc_info=exc
        )
        raise ToolException(
            f"MCP server {spec.name!r} is unavailable",
            code=ToolErrorCode.TOOL_ERROR,
            retryable=True,
        ) from exc
    server_allowlist = _stdio_server_allowlist(spec, allowlist_root)
    tools: list[MCPTool] = []
    for remote in listing.tools:
        if not _descriptor_safe(spec, remote):
            continue
        if server_allowlist is not None:
            allowed = server_allowlist.get(remote.name)
            if allowed is None:
                _skip(spec, remote.name, "is not allowlisted")
                continue
            requires_confirmation = allowed.requires_confirmation
        else:
            requires_confirmation = spec.requires_confirmation
        descriptor = ToolDescriptor(
            name=f"{spec.name}.{remote.name}",
            description=(remote.description or "")[:_UNTRUSTED_TEXT_CAP],
            params=remote.inputSchema,
            returns=remote.outputSchema if remote.outputSchema is not None else _FALLBACK_RETURNS,
            timeout_seconds=None,  # the registry default owns the bound
            requires_confirmation=requires_confirmation,
        )
        tools.append(
            MCPTool(
                spec=spec,
                remote_name=remote.name,
                descriptor=descriptor,
                secret_store=secret_store,
            )
        )
    return tools
