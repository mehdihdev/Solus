"""§2.5 Integrations — connector catalog + OAuth handshake.

OAuth flow (SOLUSDEV-241 — account scope): `oauth/start` (authenticated)
creates a PENDING account connection — and, when a `project_id` is given, the
project's PENDING source — plus a short-lived, single-use `state` bound to the
user, the connection and the source, then returns the provider authorize URL.
The browser sends the user to the provider, which redirects to `oauth/callback`
(unauthenticated — verified by `state`); the callback exchanges the code, stores
the token under the CONNECTION's ref, marks it CONNECTED, binds the source (if
any) to it, and redirects back to the app.

State is the CSRF defence (CLAUDE.md §7): a callback whose state is unknown,
expired, or provider-mismatched is rejected. Tokens never touch a response.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
import uuid
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from solus_api.connectors.contracts import ConnectorError, OAuthConnector
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError
from solus_api.connectors.runtime import connector_error_payload
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    CurrentUser,
    RegistryDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    live_membership,
)
from solus_api.models import (
    AccountConnection,
    OAuthState,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    User,
    ensure_utc,
    utcnow,
)
from solus_api.schemas import OAuthExchange, OAuthStart, serialize_connection, serialize_source
from solus_api.services.connections import (
    StaleHandshakeError,
    bind_to_account,
    complete_connection,
    connection_projects,
    pending_connection,
    record_connection_failure,
    reusable_source,
    sweep_after_commit,
)
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

router = APIRouter(prefix="/api/v1/integrations")

OAUTH_STATE_TTL_MINUTES = 10


@router.get("")
async def list_integrations(registry: RegistryDep, _user: CurrentUser) -> dict[str, Any]:
    """Catalog of available connector types + their config/auth shape.

    SOLUSDEV-168: each entry also declares the vendor-hosted MCP add-on its
    connector carries, if any. Catalog DATA, exactly like `selection` and
    `access_modes` — so the app renders the disclosure and the enable affordance
    without knowing which connector it is, and the next hosted server is one
    entry in `HOSTED_SERVERS` with no frontend change at all.
    """
    # Function-local, the same idiom `list_local_tools` uses below: the router
    # should not grow an agent-package import at module scope.
    from solus_api.agent.tools.remote_mcp import HOSTED_SERVERS

    by_source_type = {spec.source_type.value: spec for spec in HOSTED_SERVERS.values()}
    items = registry.catalog()
    for item in items:
        spec = by_source_type.get(str(item.get("type")))
        item["hosted"] = (
            None
            if spec is None
            else {
                "server": spec.name,
                "display_name": spec.display_name,
                # Solus-authored consent copy, rendered VERBATIM by the app.
                "notice": spec.connect_notice,
                "subscribe_url": spec.subscribe_url,
            }
        )
    return envelope(items)


@router.get("/local-tools")
async def list_local_tools(_user: CurrentUser) -> dict[str, Any]:
    """Bridge-hosted desktop tools (SOLUSDEV-72): vendor-run loopback MCP servers
    from the ADR-031 catalog (Fusion today). These are not connectors — they run
    on the customer's machine, reached through the companion — so they surface as
    the generic `local-bridge` tile: the next tool is a catalog entry here, never
    a frontend edit."""
    from solus_api.agent.tools.mcp_servers import MCP_SERVER_CATALOG
    from solus_api.bridge.platforms import platform_fields

    tools = [
        {
            "type": spec.name,
            **platform_fields(spec.name),
            "hosting": "vendor-run",
            "url_host": urlsplit(spec.url).netloc,
            "connect_notice": spec.connect_notice,
            "requires": "companion",
        }
        for spec in MCP_SERVER_CATALOG.values()
        if spec.url is not None  # command-launched forks are companion-managed, not tiles
    ]
    return envelope(tools)


def _provider_type(provider: str) -> SourceType:
    try:
        return SourceType(provider)
    except ValueError as exc:
        raise APIError(404, "unknown_provider", f"No such provider '{provider}'") from exc


def _resolve_redirect_uri(provider: str, requested: str | None, settings: SettingsDep) -> str:
    """Pick + validate the OAuth redirect URI. Desktop supplies a 127.0.0.1
    loopback URL; web defaults to this API's callback. Anything else is
    rejected so a caller can't redirect the code to an arbitrary host."""
    default = f"{settings.public_api_base_url}/api/v1/integrations/{provider}/oauth/callback"
    if requested is None:
        return default
    parts = urlsplit(requested)
    allowed_hosts = {"127.0.0.1", "localhost", urlsplit(settings.public_api_base_url).hostname}
    allowed_hosts.discard(None)  # a misconfigured base must not whitelist hostless URLs
    if (
        parts.scheme not in ("http", "https")
        or parts.hostname is None
        or parts.hostname not in allowed_hosts
    ):
        raise APIError(400, "invalid_redirect_uri", "redirect_uri host is not allowed")
    return requested


@router.post("/{provider}/oauth/start", status_code=201)
async def oauth_start(
    provider: str,
    body: OAuthStart,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    registry: RegistryDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    source_type = _provider_type(provider)
    # The plan's integration cap applies to an ACCOUNT-only start too — a grant
    # is an integration whether or not a project is attached yet.
    await check_can_add_integration(session, user)
    try:
        connector = registry.create(provider)
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", f"No connector for '{provider}'") from exc
    if not isinstance(connector, OAuthConnector):
        raise APIError(400, "not_oauth", f"'{provider}' does not use OAuth")

    # The ACCOUNT the grant lands on — always. The project is optional.
    connection = await pending_connection(session, user, source_type)
    project, source = await _project_source_for_start(
        session, user, body, source_type, connector, provider
    )

    state = pysecrets.token_urlsafe(32)
    redirect_uri = _resolve_redirect_uri(provider, body.redirect_uri, settings)
    session.add(
        OAuthState(
            state=state,
            provider=provider,
            source_id=source.id if source is not None else None,
            connection_id=connection.id,
            project_id=project.id if project is not None else None,
            user_id=user.id,
            redirect_uri=redirect_uri,
            expires_at=utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
        )
    )
    try:
        authorize_url = connector.authorize_url(
            state=state, redirect_uri=redirect_uri, access=body.access
        )
    except ConnectorError as exc:
        raise APIError(400, exc.code, exc.message) from exc
    except ValueError as exc:
        # An unknown access mode is a caller error, not a 500 — the connector
        # refuses rather than silently defaulting (SOLUS-ONS-A2).
        raise APIError(400, "invalid_access_mode", str(exc)) from exc
    if body.access:
        # What the user is about to grant, recorded on the connection so "can
        # Solus edit this?" is answerable without re-deriving it from the token.
        connection.config = {**connection.config, "access": body.access}

    emit_event(
        session,
        user=user,
        event_type="source.oauth_started",
        team_id=project.team_id if project is not None else None,
        project_id=project.id if project is not None else None,
        payload={"provider": provider, "scope": "project" if project else "account"},
    )
    await session.commit()
    return envelope(
        {
            "authorize_url": authorize_url,
            "state": state,
            "connection_id": str(connection.id),
            "source_id": str(source.id) if source is not None else None,
        }
    )


async def _project_source_for_start(
    session: SessionDep,
    user: Any,
    body: OAuthStart,
    source_type: SourceType,
    connector: OAuthConnector,
    provider: str,
) -> tuple[Project | None, Source | None]:
    """The project and its PENDING source when the handshake was started from
    the Workspace wizard; (None, None) for a Home-started, account-only one."""
    if body.project_id is None:
        return None, None
    try:
        project_uuid = uuid.UUID(body.project_id)
    except ValueError as exc:
        raise APIError(422, "validation_error", "project_id is not a valid id") from exc
    project = await session.get(Project, project_uuid)
    membership = await live_membership(session, project.team_id, user.id) if project else None
    if project is None or membership is None:
        raise APIError(404, "not_found", "Project not found")
    if membership.role == Role.VIEWER:
        raise APIError(403, "forbidden", "Requires member role on this team")

    config: dict[str, Any] = {"repo": body.repo} if body.repo else {}
    if body.access:
        config["access"] = body.access
    source = await reusable_source(
        session, project, source_type, connector, pending_user_id=user.id
    )
    if source is None:
        source = Source(
            project_id=project.id,
            team_id=project.team_id,
            type=source_type,
            name=body.name or body.repo or provider,
            status=SourceStatus.PENDING,
            config=config,
            created_by=user.id,
        )
        session.add(source)
    await session.flush()
    return project, source


def _app_redirect(base: str, **params: str) -> str:
    """Append params to the app deep link, before any URL fragment so a
    hash-router renderer can still read them from window.location.search."""
    parts = urlsplit(base)
    existing = dict(parse_qsl(parts.query))
    query = urlencode({**existing, **params})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


@router.get("/{provider}/oauth/callback")
async def oauth_callback(
    provider: str,
    session: SessionDep,
    settings: SettingsDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    app_url = settings.oauth_redirect_app
    if error or not code or not state:
        return RedirectResponse(_app_redirect(app_url, solus_connect="error"), status_code=302)

    record = await session.get(OAuthState, state)
    if record is None or record.provider != provider or ensure_utc(record.expires_at) < utcnow():
        return RedirectResponse(
            _app_redirect(app_url, solus_connect="invalid_state"), status_code=302
        )

    connection, source, err = await _complete_oauth(
        session, registry, secret_store, provider, record, code
    )
    if err is not None or connection is None:
        return RedirectResponse(
            _app_redirect(app_url, solus_connect=err or "error"), status_code=302
        )
    params = {"solus_connect": "connected", "connection_id": str(connection.id)}
    if source is not None:
        params["source_id"] = str(source.id)
    return RedirectResponse(_app_redirect(app_url, **params), status_code=302)


async def _complete_oauth(
    session: SessionDep,
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    provider: str,
    record: OAuthState,
    code: str,
) -> tuple[AccountConnection | None, Source | None, str | None]:
    """Exchange the code, land the token on the ACCOUNT connection, and bind the
    project source (if the handshake started from one). Shared by the web
    callback (redirect) and the desktop exchange endpoint (JSON).
    Returns (connection, source, None) on success or (…, error_code)."""
    connection = (
        await session.get(AccountConnection, record.connection_id)
        if record.connection_id is not None
        else None
    )
    source = await session.get(Source, record.source_id) if record.source_id is not None else None
    if connection is None:
        await session.delete(record)
        await session.commit()
        return None, source, "error"

    connector = registry.create(provider)
    if not isinstance(connector, OAuthConnector):
        return connection, source, "error"
    try:
        creds = await connector.exchange_code(code=code, redirect_uri=record.redirect_uri)
        account = await connector.validate_credentials(creds)
    except ConnectorError as exc:
        record_connection_failure(connection, exc)
        if source is not None:
            source.status = SourceStatus.ERROR
            # Bounded provider-supplied text (§7 — bound message sizes, SOLUSDEV-114).
            source.last_error = connector_error_payload(exc)
        await session.delete(record)
        await session.commit()
        return connection, source, "oauth_failed"

    owner_id = record.user_id  # read before the row is deleted
    # The state row is consumed FIRST: it cascades from the pending connection,
    # which `complete_connection` may discard in favour of an existing row for
    # the same account, and a delete racing that cascade matches nothing.
    await session.delete(record)
    await session.flush()
    access = connection.config.get("access") if isinstance(connection.config, dict) else None
    client_id = getattr(connector, "_client_id", None)
    try:
        connection = await complete_connection(
            session,
            secret_store,
            connection,
            provider=provider,
            creds=creds,
            account=account,
            access=access if isinstance(access, str) else None,
            onshape_application=(
                hashlib.sha256(client_id.encode()).hexdigest()
                if provider == "onshape" and isinstance(client_id, str) and client_id
                else None
            ),
        )
    except StaleHandshakeError:
        # A second state for a row that already completed: refused, so a
        # CONNECTED account can never be re-pointed at whichever account the
        # browser authorized second (security review C1).
        await session.commit()
        return connection, source, "stale_handshake"
    if source is not None:
        # A reused legacy/PAT row retires its own token family (SOLUSDEV-242).
        bind_to_account(source, connection)
        if not source.name or source.name == provider:
            source.name = account.login
    await session.commit()
    owner = await session.get(User, owner_id)
    if owner is not None:
        await sweep_after_commit(session, secret_store, owner)
        # The sweep's own rollback (a DB blip) expires what the callers are
        # about to serialize; the rows are committed, so re-read them.
        await session.refresh(connection)
        if source is not None:
            await session.refresh(source)
    return connection, source, None


@router.post("/{provider}/oauth/exchange")
async def oauth_exchange(
    provider: str,
    body: OAuthExchange,
    user: CurrentUser,
    session: SessionDep,
    registry: RegistryDep,
    secret_store: SecretStoreDep,
) -> dict[str, Any]:
    """Desktop loopback completion: the app captured the code; exchange it
    server-side. The state must belong to the requesting user."""
    _provider_type(provider)
    record = await session.get(OAuthState, body.state)
    if record is None or record.provider != provider or record.user_id != user.id:
        raise APIError(404, "invalid_state", "Unknown or expired OAuth state")
    if ensure_utc(record.expires_at) < utcnow():
        await session.delete(record)
        await session.commit()
        raise APIError(400, "expired_state", "OAuth state has expired")

    connection, source, err = await _complete_oauth(
        session, registry, secret_store, provider, record, body.code
    )
    if err is not None or connection is None:
        raise APIError(400, err or "oauth_failed", "OAuth exchange failed")
    projects = await connection_projects(session, [connection.id])
    return envelope(
        {
            "connection": serialize_connection(connection, projects.get(connection.id)),
            "source": serialize_source(source) if source is not None else None,
        }
    )
