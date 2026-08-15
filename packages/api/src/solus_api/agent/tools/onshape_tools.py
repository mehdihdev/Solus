"""Onshape operations exposed to SOL as in-process tools — SOLUS-ONS-A1.

The bridge between two things that already existed and had never been joined:
`connectors/onshape_ops.py` (transport-free operations) and the W0-04
`ToolRegistry`. Wrapping them as `InProcessTool`s rather than an `MCPTool` is
deliberate — `MCPServerSpec` requires a stdio command or an HTTP url, so an
in-process server would mean editing a security-reviewed module's core contract
to gain nothing. Going through `InProcessTool` inherits JSON-Schema arg
validation, the registry timeout, the never-raises envelope and
`confirmation_refusal` for free.

**Tenant scope is bound HERE, by Solus code, before the model sees anything**
(the `get_entity` idiom). `project_id` is a closure variable, never an argument,
so no model output can reach another team's Onshape. A source in a different
project is reported as NOT_FOUND rather than a permission error — no existence
oracle.

**Credentials.** A tool call is not a sync, so the sync path's credential
resolution does not apply. Instead: project → the connected Onshape `Source` →
its `secret_ref` → `resolve_credentials` → `call_with_refresh`, the same
refresh-once-and-retry seam `/selectable` uses. Onshape access tokens live 60
minutes, so an expired token during a tool call is ordinary, not an error.
Resolution happens per CALL, not at build time — a token can rotate mid-request.

**The connect-time grant is enforced here, not just in the picker** (SOLUS-ONS-A3).
Onshape scopes are account-wide, so a customer who chose read-only has a token
that could technically write; the refusal is ours to make. It is re-read from the
source on every call, so revoking edit rights takes effect immediately, and an
absent grant (a source connected before the choice existed) reads as read-only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape_ops import OnshapeOperation, every_operation
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError
from solus_api.connectors.runtime import call_with_refresh, resolve_credentials
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.models import Source, SourceStatus, SourceType

if TYPE_CHECKING:
    from solus_api.connectors.onshape import OnshapeConnector

logger = logging.getLogger("solus.agent.tools.onshape")

#: One authenticated step against Onshape — an operation's `run` or its
#: `preview`. Both need identical credential resolution and the same grant check.
type _Step[T] = Callable[["OnshapeConnector", httpx.AsyncClient, dict[str, Any]], Awaitable[T]]

#: `ConnectorError.code` → the W0-04 error code a model can branch on. Anything
#: unlisted is a TOOL_ERROR, so a new connector code can never leak as a crash.
_ERROR_CODES: dict[str, ToolErrorCode] = {
    "config_invalid": ToolErrorCode.INVALID_ARGS,
    "invalid_credentials": ToolErrorCode.UNAUTHORIZED,
    "oauth_refresh_failed": ToolErrorCode.UNAUTHORIZED,
    "oauth_not_configured": ToolErrorCode.UNAUTHORIZED,
    "not_found": ToolErrorCode.NOT_FOUND,
}

#: Codes worth retrying: a transport blip, not a bad request.
_RETRYABLE = frozenset({"api_unreachable", "api_error"})


async def _connected_source(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> Source | None:
    """The project's connected Onshape source, or None.

    Scoped to `project_id` — the closure-bound one — so a source belonging to any
    other project is simply not visible.
    """
    async with session_factory() as session:
        source: Source | None = await session.scalar(
            select(Source).where(
                Source.project_id == project_id,
                Source.type == SourceType.ONSHAPE,
                Source.status == SourceStatus.CONNECTED,
            )
        )
        return source


def _tool_error(exc: ConnectorError) -> ToolException:
    """Map a connector failure to the model-facing envelope.

    The message is the connector's own — which never echoes upstream text or
    credential material (its `request` helper drops both deliberately).
    """
    return ToolException(
        exc.message,
        code=_ERROR_CODES.get(exc.code, ToolErrorCode.TOOL_ERROR),
        retryable=exc.code in _RETRYABLE,
    )


#: The value `Source.config["access"]` carries when the customer granted edit
#: rights. Anything else — including nothing — is read-only.
_WRITE_ACCESS = "write"


def _may_write(source: Source) -> bool:
    config = source.config if isinstance(source.config, dict) else {}
    return config.get("access") == _WRITE_ACCESS


async def _prepare(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    secret_store: SecretStore,
    connectors: ConnectorRegistry,
    *,
    is_write: bool,
) -> tuple[OnshapeConnector, Credentials, Source]:
    """The connected source and its live credentials, with the grant checked.

    Re-read per call rather than bound at build time: an access token rotates
    inside 60 minutes, and revoking edit rights must take effect immediately.
    """
    source = await _connected_source(session_factory, project_id)
    if source is None or not source.secret_ref:
        raise ToolException(
            "No Onshape source is connected to this project. Connect one in Sources first.",
            code=ToolErrorCode.NOT_FOUND,
            retryable=False,
        )
    if is_write and not _may_write(source):
        raise ToolException(
            "This Onshape source is connected read-only. Reconnect it and choose "
            "'Read and edit' to let Solus change your models.",
            code=ToolErrorCode.UNAUTHORIZED,
            retryable=False,
        )
    try:
        connector = connectors.create("onshape")
    except UnknownConnectorError as exc:  # pragma: no cover - registry always has it
        raise ToolException(
            "The Onshape connector is not available.",
            code=ToolErrorCode.TOOL_ERROR,
            retryable=False,
        ) from exc
    try:
        credentials = await resolve_credentials(secret_store, source.secret_ref)
    except SecretNotFoundError as exc:
        raise ToolException(
            "The stored Onshape credentials are missing; reconnect the source.",
            code=ToolErrorCode.UNAUTHORIZED,
            retryable=False,
        ) from exc
    onshape: OnshapeConnector = connector  # type: ignore[assignment]
    return onshape, credentials, source


def _build_tool(
    operation: OnshapeOperation,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    secret_store: SecretStore,
    connectors: ConnectorRegistry,
) -> Tool:
    is_write = "write" in operation.tags

    async def _call[T](args: dict[str, Any], step: _Step[T]) -> T:
        connector, credentials, source = await _prepare(
            session_factory, project_id, secret_store, connectors, is_write=is_write
        )

        async def run(creds: Credentials) -> T:
            async with connector.http(creds) as client:
                return await step(connector, client, args)

        try:
            return await call_with_refresh(
                connector=connector,
                credentials=credentials,
                secret_store=secret_store,
                secret_ref=source.secret_ref or "",
                run=run,
            )
        except ConnectorError as exc:
            logger.info("onshape tool %s failed: %s", operation.name, exc.code)
            raise _tool_error(exc) from exc

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        return await _call(args, operation.run)

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        assert operation.preview is not None
        return await _call(args, operation.preview)

    return InProcessTool(
        ToolDescriptor(
            name=operation.name,
            description=operation.description,
            params=operation.params,
            returns=operation.returns,
            requires_confirmation=operation.requires_confirmation,
        ),
        handler,
        preview if operation.preview is not None else None,
    )


def build_onshape_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    secret_store: SecretStore | None,
    connectors: ConnectorRegistry,
) -> list[Tool]:
    """Every Onshape operation, bound to ONE project.

    Returns `[]` without a secret store — there would be no way to authenticate,
    and offering tools that always fail is worse than not offering them (the same
    fail-closed rule MCP-05's license preflight follows).
    """
    if secret_store is None:
        return []
    return [
        _build_tool(operation, session_factory, project_id, secret_store, connectors)
        for operation in every_operation()
    ]


__all__ = ["build_onshape_tools"]
