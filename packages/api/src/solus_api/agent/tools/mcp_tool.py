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
model reads — size-bounded here, not sanitized.

Credential DELIVERY (SOLUSDEV-252 P6) is `MCPServerSpec.secret_env`: a child env
var NAME → SecretStore REF, resolved by `_resolve_env` at spawn into the child
environment and nowhere else. Presence is still gated first (`required_secrets`),
so a keyless deployment refuses before any process starts.
"""

import asyncio
import enum
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final, Protocol, Self

import httpx
from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
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

#: Resolves the Authorization header for ONE customer, per call. A hosted
#: server's token is short-lived (fs-mcp issues 3599s), so it cannot be captured
#: at wiring time. Raising `ToolException` from here is the sanctioned way to
#: report "not connected / grant expired" — it passes through `invoke` untouched
#: and reaches the model as a typed failure, never as an exception.
HeadersProvider = Callable[[], Awaitable[Mapping[str, str]]]

#: Runs BEFORE any connection is opened, and raises `ToolException` to refuse.
#: The same shape `BridgeTool` already takes for the MCP-05 licence check —
#: registration itself meters nothing (`exec.run_tool` only logs), so a tool
#: that spends a real allowance has to bring its own admission.
Preflight = Callable[[], Awaitable[None]]

#: `[{label, before, after}]` — the diff a human approves. Duck-typed by
#: `confirmations._build_preview` via `getattr(tool, "preview", None)`.
PreviewBuilder = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class ToolPolicy(Protocol):
    """Solus's own answer to "may SOL call this, and what does a human approve?"

    Structural on purpose: `remote_mcp.RemoteMCPSpec` satisfies it without this
    module importing it, so `mcp_tool` stays vendor-agnostic and the reasoning
    import graph does not grow a registry dependency.
    """

    def exposes(self, remote_name: str) -> bool: ...
    def requires_confirmation(self, remote_name: str) -> bool: ...
    def consent_summary(self, remote_name: str) -> str: ...


#: Schema keys whose values are free PROSE written by the server.
#: `prompt.py` fences a descriptor's `description` in a nonce data-block when it
#: is untrusted, but `params` passes through VERBATIM — its own docstring says
#: so — which makes every prose leaf inside a server-authored JSON Schema
#: unfenced, instruction-position text the model reads. For a server running on
#: a vendor's cloud that is a direct prompt-injection channel, so the prose is
#: dropped for hosted specs. Structure (types, required, enums) is kept: it is
#: what the model actually needs to build a valid call.
_SCHEMA_PROSE_KEYS: Final = frozenset({"description", "title", "$comment", "examples"})
#: Untrusted input is not walked without a floor.
_MAX_SCHEMA_DEPTH: Final = 12
# Discovery runs OUTSIDE the registry (wiring time), so it carries its own bound.
DISCOVERY_TIMEOUT_SECONDS = 30.0
# Bounds for the streamable-http transport. The SDK's own defaults (30s connect,
# 300s read) outlive the registry's 30s call budget, which would make a hung
# hosted server look like a Solus hang rather than a TIMEOUT result.
_HTTP_TIMEOUT_SECONDS: Final = 15.0
_HTTP_READ_TIMEOUT_SECONDS: Final = 25.0
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
    #: SOLUSDEV-252 P6 — credential DELIVERY, declared by NAME: child env var
    #: name → SecretStore ref. `_resolve_env` reads the VALUES at spawn and puts
    #: them in the child environment dict and nowhere else; a value never lives
    #: in the spec, a descriptor, a result, or a log line. Every ref here must
    #: also be a `required_secret` (validator below), so the keyless gate refuses
    #: BEFORE any spawn rather than starting a server that can only error.
    secret_env: Mapping[str, str] = {}
    #: Names of API-process environment variables the launcher may see, forwarded
    #: verbatim from `os.environ` at spawn. NOT for credentials (that is
    #: `secret_env`): this is for pinning knobs like `SOLUS_NODE_BIN`, the
    #: absolute Node interpreter a vendored fork's `bin/launch` refuses to
    #: PATH-resolve. Absent from the environment → simply not forwarded.
    passthrough_env: tuple[str, ...] = ()
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
    #: Plain notice shown to the user when they connect this tool. Catalog DATA
    #: so any surface that offers a tool can render it without knowing which
    #: tool it is — the same generic treatment `access_modes` and `selection`
    #: get on connectors. Used for licence terms Solus must surface but must not
    #: enforce: Fusion Personal forbids commercial use, and Autodesk asks
    #: integrations to say so. It INFORMS; it never blocks a connection.
    connect_notice: str | None = None

    @model_validator(mode="after")
    def _transport_and_key_delivery(self) -> Self:
        if (self.command is None) == (self.url is None):
            raise ValueError("exactly one transport: set command (stdio) or url (streamable-http)")
        undeclared = sorted(set(self.secret_env.values()) - set(self.required_secrets))
        if undeclared:
            # Fail closed at import: a delivered-but-ungated ref would spawn a
            # server with an empty key instead of refusing with the typed
            # UNAUTHORIZED the caller can act on.
            raise ValueError(f"secret_env refs must also be required_secrets: {undeclared}")
        return self


@asynccontextmanager
async def _open_session(
    spec: MCPServerSpec,
    *,
    headers: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    """Fresh connect → initialize. `async with` throughout so a registry-level
    cancellation (its timeout) still runs transport cleanup. Note the bound is
    soft for stdio: the SDK's shutdown path may add ~2s of SIGTERM grace before
    the caller sees the TIMEOUT result."""
    if spec.command is not None:
        params = StdioServerParameters(
            command=spec.command,
            args=list(spec.args),
            # `env` is `_resolve_env`'s output when a caller has a SecretStore;
            # the spec's own static env is the fallback for callers that do not
            # (`call_remote`, whose specs are url-transport).
            env=dict(env)
            if env is not None
            else (dict(spec.env) if spec.env is not None else None),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return
    if spec.url is None:  # pragma: no cover — the spec validator forbids this
        raise ToolException(f"MCP server {spec.name!r} has no transport configured")
    # The deprecated one-shot client silently DISCARDS headers/auth:
    # `StreamableHTTPTransport.__init__` accepts them and assigns only
    # url/session_id/protocol_version (`streamable_http.py:125-146`). So a
    # caller-owned client is the only way to authenticate. We create it, so we
    # close it: `streamable_http_client` enters the client as a context manager
    # ONLY when it made the client itself (:638-654), so handing it one without
    # an `async with` here would leak a connection on every call.
    async with httpx.AsyncClient(
        headers=dict(headers) if headers else None,
        timeout=httpx.Timeout(_HTTP_TIMEOUT_SECONDS, read=_HTTP_READ_TIMEOUT_SECONDS),
    ) as client:
        async with streamable_http_client(spec.url, http_client=client) as (
            read,
            write,
            _get_session_id,
        ):
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


async def _resolve_env(spec: MCPServerSpec, store: SecretStore) -> dict[str, str] | None:
    """The child environment for ONE stdio spawn: the spec's static `env`, plus
    each `passthrough_env` name present in the API process, plus every
    `secret_env` ref resolved to its VALUE from the SecretStore.

    This is the only place a credential value exists outside the store, and it
    exists only inside the dict handed to `StdioServerParameters` — nothing here
    is logged, returned, or attached to the spec (CLAUDE.md §7: secrets by NAME
    in code, values only into a child env at spawn). A ref that vanished between
    the keyless gate and the spawn raises the same typed UNAUTHORIZED, naming
    the ref and never the value.
    """
    if spec.command is None:
        return None  # url transport: nothing is spawned
    env: dict[str, str] = dict(spec.env or {})
    for name in spec.passthrough_env:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    for var, ref in spec.secret_env.items():
        try:
            env[var] = await store.get(ref)
        except SecretNotFoundError as exc:
            raise _credentials_error(spec, [ref]) from exc
    return env or None


def _credentials_error(spec: MCPServerSpec, missing: list[str]) -> ToolException:
    # Mirrors ProviderCredentialsMissingError (MO-01): name the missing KEYS so
    # the fix is actionable; secret VALUES never appear in any message.
    return ToolException(
        f"MCP server {spec.name!r} requires credentials: configure "
        f"{', '.join(missing)} in the SecretStore",
        code=ToolErrorCode.UNAUTHORIZED,
        retryable=False,
    )


def _unavailable(spec: MCPServerSpec, exc: BaseException) -> ToolException:
    """The generic transport failure. The model only ever sees the server NAME;
    the traceback goes to the operator's log."""
    logger.warning("MCP server %r unreachable (%s)", spec.name, type(exc).__name__, exc_info=exc)
    return ToolException(
        f"MCP server {spec.name!r} is unavailable",
        code=ToolErrorCode.TOOL_ERROR,
        retryable=True,
    )


def _from_group(group: BaseExceptionGroup, spec: MCPServerSpec) -> ToolException:
    """Flatten an anyio task-group failure into ONE typed `ToolException`.

    Three cases, in order of what matters:
    * it carries a cancellation → re-raise the group untouched, so an external
      cancel keeps propagating instead of being reported as a tool failure;
    * it carries a `ToolException` we raised ourselves (an auth provider's
      "reconnect", a server-reported error) → surface THAT, not "unavailable",
      or a permanently dead grant would come back marked retryable;
    * anything else → the generic transport failure.
    """
    if group.subgroup(asyncio.CancelledError) is not None:
        raise group
    ours, _rest = group.split(ToolException)
    if ours is not None:
        leaves = [e for e in _leaves(ours) if isinstance(e, ToolException)]
        if leaves:
            return leaves[0]
    return _unavailable(spec, group)


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for member in exc.exceptions for leaf in _leaves(member)]
    return [exc]


def _strip_schema_prose(node: Any, *, depth: int = 0) -> Any:
    """Drop server-authored PROSE from a JSON Schema, keeping its structure.

    See `_SCHEMA_PROSE_KEYS`. Bounded depth because the input is untrusted and a
    deeply nested schema must not recurse without limit; `unsafe_schema_reason`
    has already rejected `$ref`, so there are no cycles to chase.
    """
    if depth > _MAX_SCHEMA_DEPTH:
        return {}
    if isinstance(node, dict):
        return {
            key: _strip_schema_prose(value, depth=depth + 1)
            for key, value in node.items()
            if key not in _SCHEMA_PROSE_KEYS
        }
    if isinstance(node, list):
        return [_strip_schema_prose(item, depth=depth + 1) for item in node]
    return node


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
        headers_provider: HeadersProvider | None = None,
        preflight: Preflight | None = None,
        preview: PreviewBuilder | None = None,
    ) -> None:
        self._spec = spec
        self._remote_name = remote_name
        self._descriptor = descriptor
        self._secret_store = secret_store
        self._headers_provider = headers_provider
        self._preflight = preflight
        if preview is not None:
            # Set on the INSTANCE, never declared on the class: the gate asks
            # `getattr(tool, "preview", None)` and treats a present attribute as
            # "this tool can describe its own change". A class-level stub would
            # make every MCP tool claim it could, and a preview that returns
            # nothing degrades the approval card to argument rows silently.
            self.preview = preview

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    @property
    def remote_name(self) -> str:
        """The tool's name ON THE SERVER, unqualified.

        The registry name is `{server}.{remote}`; the connect step persists this
        alongside it so a later registry build does not have to re-derive it by
        string-splitting a name that may itself contain a dot.
        """
        return self._remote_name

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        missing = await _missing_secrets(self._spec, self._secret_store)
        if missing:  # checked BEFORE any connection attempt
            raise _credentials_error(self._spec, missing)
        # Resolved per call, OUTSIDE the try: a `ToolException` raised by the
        # provider ("reconnect FeatureScript") must reach the model as itself,
        # not be reshaped into "the server is unavailable, retry".
        if self._preflight is not None:
            await self._preflight()
        headers = await self._headers_provider() if self._headers_provider is not None else None
        env = await _resolve_env(self._spec, self._secret_store)
        try:
            async with _open_session(self._spec, headers=headers, env=env) as session:
                result = await session.call_tool(self._remote_name, args)
        except ToolException:
            raise
        except McpError as exc:
            raise ToolException(
                f"MCP server {self._spec.name!r} protocol error: {str(exc)[:_UNTRUSTED_TEXT_CAP]}",
                code=ToolErrorCode.TOOL_ERROR,
            ) from exc
        except BaseExceptionGroup as group:
            # THE NEVER-RAISES HOLE. The transports run inside anyio task groups,
            # and `except Exception` does NOT catch a `BaseExceptionGroup`:
            # verified on CPython 3.12.3, `BaseExceptionGroup("g", [ValueError,
            # CancelledError])` stays a BaseExceptionGroup (only an all-Exception
            # group is downgraded to `ExceptionGroup`, which IS an Exception). So
            # a cancel racing a transport failure escaped both this handler and
            # `registry.invoke`'s.
            #
            # Cancellation must still propagate — `wait_for` converts its OWN
            # timeout upstream, so a CancelledError arriving here is an EXTERNAL
            # cancel (client gone, shutdown) and swallowing it would hang the turn.
            raise _from_group(group, self._spec) from group
        except Exception as exc:
            # Spawn/connect/transport failure — anyio surfaces these in several
            # shapes, so the catch stays broad and retryable=True is the transport
            # assumption. An internal bug lands here too: the traceback below is
            # the operator's signal; the model sees only the server NAME.
            raise _unavailable(self._spec, exc) from exc
        return _map_result(result)


async def call_remote(
    spec: MCPServerSpec,
    remote_name: str,
    args: dict[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One authenticated tool call, outside the registry.

    For Solus code that needs a remote READ in order to build something the
    registry path depends on — chiefly the confirmation gate's `preview`, which
    must fetch the current FeatureScript before it can show what an overwrite
    replaces. Deliberately NOT named `invoke`: `test_sol_runtime`'s ratchet fails
    any dispatch-shaped call site under `agent/` outside the three files
    that own the gated path, and a preview is not a dispatch.

    Same failure vocabulary as the tool path, so a caller handles one shape.
    """
    try:
        async with _open_session(spec, headers=headers, env=env) as session:
            result = await session.call_tool(remote_name, args)
    except ToolException:
        raise
    except McpError as exc:
        raise ToolException(
            f"MCP server {spec.name!r} protocol error: {str(exc)[:_UNTRUSTED_TEXT_CAP]}",
            code=ToolErrorCode.TOOL_ERROR,
        ) from exc
    except BaseExceptionGroup as group:
        raise _from_group(group, spec) from group
    except Exception as exc:
        raise _unavailable(spec, exc) from exc
    return _map_result(result)


async def call_discovered(tool: "MCPTool", args: dict[str, Any]) -> dict[str, Any]:
    """One call to a tool DISCOVERY already built and allowlisted, made by SOLUS
    CODE rather than by SOL — today `agent/research.py`'s loop over the brave
    tools, whose sub-calls are fixed by Solus before any model sees anything.

    Deliberately a function rather than the tool's own dispatch method, for the
    same reason `call_remote` is not named `invoke`: `test_sol_runtime`'s ratchet
    fails any dispatch-shaped call site under `agent/` outside the three files
    that own the gated path, and a Solus-internal read is not a dispatch. The
    guarantees are identical because it runs the same code — keyless gate,
    preflight, resolved child env, one typed failure vocabulary.
    """
    missing = await _missing_secrets(tool._spec, tool._secret_store)
    if missing:  # checked BEFORE any connection attempt
        raise _credentials_error(tool._spec, missing)
    if tool._preflight is not None:
        await tool._preflight()
    env = await _resolve_env(tool._spec, tool._secret_store)
    return await call_remote(tool._spec, tool._remote_name, args, env=env)


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


def _classify(
    spec: MCPServerSpec,
    remote_name: str,
    policy: "ToolPolicy | None",
    server_allowlist: dict[str, AllowedTool] | None,
) -> tuple[bool, str | None] | None:
    """`(requires_confirmation, consent_summary)`, or None to SKIP the tool.

    Three enforcement sources, never blended: a hosted spec's cloud-side
    `policy`, a vendored fork's `allowlist.yaml`, or the spec's own blanket
    flag. Each answers "may SOL call this at all?" before it answers "does a
    human approve it?", because ADR-031 fixes the NAMESPACE first.
    """
    if policy is not None:
        # SOLUSDEV-168, hosted: exposure IS the Solus-owned allowlist. A tool the
        # vendor adds between releases is not registered at all — gating it as
        # mutating would still put a Solus-authored consent sentence behind a
        # tool Solus has never seen.
        if not policy.exposes(remote_name):
            _skip(spec, remote_name, "is not classified by Solus")
            return None
        return policy.requires_confirmation(remote_name), policy.consent_summary(remote_name)
    if server_allowlist is not None:
        allowed = server_allowlist.get(remote_name)
        if allowed is None:
            _skip(spec, remote_name, "is not allowlisted")
            return None
        return allowed.requires_confirmation, None
    if spec.requires_confirmation:
        # SEC-C1: a destructive tool with no allowlist entry has no
        # Solus-authored consent text — it must not be dispatchable at all, or
        # the approval sentence would be phrased by the fork.
        _skip(spec, remote_name, "declares a destructive default with no consent text")
        return None
    return False, None


async def discover_mcp_tools(
    spec: MCPServerSpec,
    secret_store: SecretStore,
    *,
    timeout_seconds: float = DISCOVERY_TIMEOUT_SECONDS,
    allowlist_root: str | Path = DEFAULT_ALLOWLIST_ROOT,
    policy: ToolPolicy | None = None,
    headers_provider: HeadersProvider | None = None,
    strip_schema_prose: bool = False,
    preflight: Preflight | None = None,
    previews: Mapping[str, PreviewBuilder] | None = None,
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

    SOLUSDEV-168: a HOSTED spec passes a `policy` instead — the same ADR-031
    rule enforced from the cloud-side registry rather than a vendored
    `allowlist.yaml`. A tool the policy does not expose is SKIPPED, so a server
    that grows a tool between releases cannot enter SOL's namespace at all; the
    ones that survive carry the policy's Solus-authored `consent_summary`,
    without which the approval card degrades to a bare tool name
    (`confirmations.py:101-108` fails closed when `description_trusted` is
    False and no consent text was supplied).
    """
    missing = await _missing_secrets(spec, secret_store)
    if missing:  # fail fast — no connection without credentials
        raise _credentials_error(spec, missing)
    headers = await headers_provider() if headers_provider is not None else None
    env = await _resolve_env(spec, secret_store)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with _open_session(spec, headers=headers, env=env) as session:
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
    except BaseExceptionGroup as group:
        raise _from_group(group, spec) from group
    except Exception as exc:
        raise _unavailable(spec, exc) from exc
    server_allowlist = _stdio_server_allowlist(spec, allowlist_root)
    tools: list[MCPTool] = []
    seen: set[str] = set()
    for remote in listing.tools:
        if not _descriptor_safe(spec, remote):
            continue
        if remote.name in seen:
            # A duplicate advertised name would raise out of
            # `ToolRegistry.register` (`registry.py:51-52`) at WIRING time,
            # 500ing every SOL request for the project — including the one that
            # would REJECT an already-parked destructive action. That is a
            # kill switch held by the server, so it is dropped here, exactly as
            # the bridge path does (`bridge/allowlist.py:163-167`).
            _skip(spec, remote.name, "is advertised more than once")
            continue
        verdict = _classify(spec, remote.name, policy, server_allowlist)
        if verdict is None:
            continue
        requires_confirmation, consent = verdict
        seen.add(remote.name)
        descriptor = ToolDescriptor(
            name=f"{spec.name}.{remote.name}",
            description=(remote.description or "")[:_UNTRUSTED_TEXT_CAP],
            # SEC-C1/H1: introspected from the fork — never Solus-authored. The
            # prompt layer fences it and the consent card refuses to render it.
            description_trusted=False,
            params=_strip_schema_prose(remote.inputSchema)
            if strip_schema_prose
            else remote.inputSchema,
            returns=remote.outputSchema if remote.outputSchema is not None else _FALLBACK_RETURNS,
            timeout_seconds=None,  # the registry default owns the bound
            requires_confirmation=requires_confirmation,
            # Without this a gated tool's approval sentence degrades to the bare
            # tool NAME (`confirmations.py:101-108`), which is consent to nothing.
            consent_summary=consent,
        )
        tools.append(
            MCPTool(
                spec=spec,
                remote_name=remote.name,
                descriptor=descriptor,
                secret_store=secret_store,
                headers_provider=headers_provider,
                preflight=preflight,
                preview=(previews or {}).get(remote.name),
            )
        )
    return tools
