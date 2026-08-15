# SOLUSDEV-203 (SOLX-04) — connecting a tool is a SOL action, not a settings
# chore. Three W0-04 tools over the connector registry:
#
#   solus.list_integrations   read: the roster + per-project connection state,
#                             so a missing-capability moment can offer the
#                             connect action inline.
#   solus.connect_integration DESTRUCTIVE (requires_confirmation, Solus-authored
#                             consent text): for committed-export connectors
#                             (AuthKind.NONE) it creates the live Source; for
#                             OAuth/PAT providers it returns a clear next step
#                             (finish in-app) — a chat turn cannot complete a
#                             browser OAuth round-trip, and credentials NEVER
#                             travel through model-visible arguments (§7: the
#                             params schema has no token field, on purpose).
#   solus.verify_integration  read: is the provider live for this project?
#
# Scope (project/team/user) is bound at construction by Solus code, like every
# registry tool — never from model arguments. Failures return the supported
# roster or the concrete next step, not a dead end.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.connectors.contracts import AuthKind, Connector, ConnectorError, Credentials
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError
from solus_api.core.errors import APIError
from solus_api.models import Source, SourceStatus, SourceType, User
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

logger = logging.getLogger("solus.agent.connect_integration")

_PROVIDER_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {"provider": {"type": "string"}},
    "required": ["provider"],
    "additionalProperties": False,
}

LIST_DESCRIPTOR = ToolDescriptor(
    name="solus.list_integrations",
    description=(
        "List the integrations Solus supports and whether each is connected to "
        "this project. When a capability is missing, offer solus.connect_integration."
    ),
    params={"type": "object", "properties": {}, "additionalProperties": False},
    returns={"type": "object"},
)

CONNECT_DESCRIPTOR = ToolDescriptor(
    name="solus.connect_integration",
    description=(
        "Connect a supported integration to this project. Committed-export "
        "connectors go live immediately; OAuth providers return the in-app "
        "step to finish. Never asks for or accepts credentials."
    ),
    params=_PROVIDER_PARAMS,
    returns={"type": "object"},
    requires_confirmation=True,
    consent_summary=(
        "Connect an external integration to this project so Solus can sync its data into the graph."
    ),
)

VERIFY_DESCRIPTOR = ToolDescriptor(
    name="solus.verify_integration",
    description="Check whether an integration is connected and live for this project.",
    params=_PROVIDER_PARAMS,
    returns={"type": "object"},
)


@dataclass(frozen=True)
class ConnectIntegrationDeps:
    """Request-scoped wiring, fixed by Solus code before any model runs."""

    session_factory: async_sessionmaker[AsyncSession]
    project_id: UUID
    team_id: UUID
    user_id: UUID
    connectors: ConnectorRegistry


def _source_type(provider: str) -> SourceType | None:
    """Registry→enum coercion, guarded: a connector registered before the
    SourceType member exists must degrade to "unsupported", never a bare
    ValueError that nukes the whole tool call (CR-M4)."""
    try:
        return SourceType(provider)
    except ValueError:
        logger.warning("connector %r has no SourceType member; treating as unsupported", provider)
        return None


async def _connected_source(
    session: AsyncSession, deps: ConnectIntegrationDeps, provider: str
) -> Source | None:
    source_type = _source_type(provider)
    if source_type is None:
        return None
    row: Source | None = await session.scalar(
        select(Source).where(
            Source.project_id == deps.project_id,
            Source.type == source_type,
            Source.status != SourceStatus.DISCONNECTED,
        )
    )
    return row


def _roster_error(deps: ConnectIntegrationDeps, provider: str) -> ToolException:
    supported = ", ".join(deps.connectors.providers())
    return ToolException(
        f"'{provider}' is not a supported integration; supported: {supported}",
        code=ToolErrorCode.NOT_FOUND,
    )


async def _list_integrations(deps: ConnectIntegrationDeps) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    async with deps.session_factory() as session:
        for entry in deps.connectors.catalog():
            if _source_type(entry["type"]) is None:
                continue  # registered ahead of its SourceType member (CR-M4)
            row = await _connected_source(session, deps, entry["type"])
            providers.append(
                {
                    "provider": entry["type"],
                    "auth": entry["auth_kind"],
                    "connected": row is not None and row.status is SourceStatus.CONNECTED,
                    "next_step": (
                        None
                        if row is not None
                        else f"solus.connect_integration with provider={entry['type']}"
                    ),
                }
            )
    return {"providers": providers}


async def _create_source(
    session: AsyncSession, deps: ConnectIntegrationDeps, provider: str, connector: Connector
) -> dict[str, Any]:
    user = await session.get(User, deps.user_id)
    if user is None:
        # Fail CLOSED: no resolvable user means no plan-limit check is possible,
        # so nothing may be created (the route always supplies a real user id).
        raise ToolException(
            "cannot add an integration for an unknown user",
            code=ToolErrorCode.UNAUTHORIZED,
        )
    try:
        await check_can_add_integration(session, user)
    except APIError as exc:
        # Plan/onboarding limits are a next step, not a dead end.
        raise ToolException(
            f"cannot add an integration yet: {exc.message}",
            code=ToolErrorCode.UNAUTHORIZED,
        ) from exc
    try:
        account = await connector.validate_credentials(Credentials(token=""))
    except ConnectorError as exc:
        raise ToolException(
            f"{provider} refused the connection: {exc.message}; fix the reported issue and retry",
            code=ToolErrorCode.TOOL_ERROR,
        ) from exc

    source_type = _source_type(provider)
    if source_type is None:
        raise _roster_error(deps, provider)
    source = Source(
        project_id=deps.project_id,
        team_id=deps.team_id,
        type=source_type,
        name=provider,
        config={},
        status=SourceStatus.CONNECTED,
        created_by=deps.user_id,
        account_login=account.login,
        account_external_id=account.external_id,
    )
    session.add(source)
    await session.flush()
    # §9 data-collection parity with the REST path (SEC-M1): chat-originated
    # connects must be visible to abuse detection. Consent-aware via emit_event.
    emit_event(
        session,
        user=user,
        event_type="source.connected",
        team_id=deps.team_id,
        project_id=deps.project_id,
        payload={"type": provider, "via": "sol"},
    )
    record_activity(
        session,
        team_id=deps.team_id,
        activity_type="source.connected",
        actor_id=deps.user_id,
        project_id=deps.project_id,
        domain="integrations",
        payload={"type": provider, "name": source.name, "via": "sol"},
    )
    await session.commit()
    logger.info(
        "sol connected integration provider=%s project=%s source=%s",
        provider,
        deps.project_id,
        source.id,
    )
    result: dict[str, Any] = {
        "connected": True,
        "provider": provider,
        "source_id": str(source.id),
    }
    if connector.config_fields:
        # Connected but not yet syncable without config — say what remains.
        result["next_step"] = (
            f"set {', '.join(connector.config_fields)} for {provider} in the app's "
            "Integrations screen so syncing can start"
        )
    return result


async def _connect_integration(deps: ConnectIntegrationDeps, provider: str) -> dict[str, Any]:
    try:
        connector = deps.connectors.create(provider)
    except UnknownConnectorError as exc:
        raise _roster_error(deps, provider) from exc

    async with deps.session_factory() as session:
        # CR-M2: serialize concurrent connects for the same (project, provider)
        # — two approvals racing past the existence check would otherwise both
        # insert (Source has no unique constraint). Advisory xact lock: released
        # at commit/rollback, no schema change.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"connect_integration:{deps.project_id}:{provider}"},
        )
        existing = await _connected_source(session, deps, provider)
        if existing is not None:
            if existing.status is SourceStatus.CONNECTED:
                return {
                    "connected": True,
                    "already_connected": True,
                    "status": existing.status.value,
                }
            # CR-M3: a PENDING/ERROR row is not a dead end — say what unblocks it.
            return {
                "connected": False,
                "already_connected": True,
                "status": existing.status.value,
                "next_step": (
                    f"finish connecting {provider} in the app's Integrations screen, "
                    "or disconnect it there and ask me to connect again"
                ),
            }
        if connector.auth_kind is not AuthKind.NONE:
            # A chat turn cannot finish a browser OAuth round-trip, and a
            # credential must never pass through model-visible args — the
            # clear next step is the in-app connect flow.
            return {
                "connected": False,
                "next_step": "complete_oauth_in_app",
                "provider": provider,
                "message": (
                    f"Open Integrations in Solus and connect {provider} there; "
                    "then ask me to verify it."
                ),
            }
        return await _create_source(session, deps, provider, connector)


async def _verify_integration(deps: ConnectIntegrationDeps, provider: str) -> dict[str, Any]:
    if provider not in deps.connectors.providers():
        raise _roster_error(deps, provider)
    async with deps.session_factory() as session:
        row = await _connected_source(session, deps, provider)
    if row is None:
        return {
            "connected": False,
            "next_step": f"solus.connect_integration with provider={provider}",
        }
    return {
        "connected": row.status is SourceStatus.CONNECTED,
        "status": row.status.value,
        "name": row.name,
    }


def build_integration_tools(deps: ConnectIntegrationDeps) -> list[InProcessTool]:
    async def list_handler(args: dict[str, Any]) -> dict[str, Any]:
        return await _list_integrations(deps)

    async def connect_handler(args: dict[str, Any]) -> dict[str, Any]:
        return await _connect_integration(deps, str(args["provider"]))

    async def verify_handler(args: dict[str, Any]) -> dict[str, Any]:
        return await _verify_integration(deps, str(args["provider"]))

    return [
        InProcessTool(LIST_DESCRIPTOR, list_handler),
        InProcessTool(CONNECT_DESCRIPTOR, connect_handler),
        InProcessTool(VERIFY_DESCRIPTOR, verify_handler),
    ]
