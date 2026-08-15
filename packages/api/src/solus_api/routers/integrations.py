"""§2.5 Integrations — connector catalog + OAuth handshake.

OAuth flow: `oauth/start` (authenticated) creates a PENDING source and a
short-lived, single-use `state` bound to the user+source, then returns the
provider authorize URL. The browser sends the user to the provider, which
redirects to `oauth/callback` (unauthenticated — verified by `state`); the
callback exchanges the code, stores the token in the secret store, marks the
source CONNECTED, and redirects back to the app.

State is the CSRF defence (CLAUDE.md §7): a callback whose state is unknown,
expired, or provider-mismatched is rejected. Tokens never touch a response.
"""

from __future__ import annotations

import secrets as pysecrets
import uuid
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from solus_api.connectors.contracts import Connector, ConnectorError, OAuthConnector
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError
from solus_api.connectors.runtime import connector_error_payload, refresh_secret_ref
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    CurrentUser,
    RegistryDep,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    live_membership,
)
from solus_api.models import (
    OAuthState,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    ensure_utc,
    utcnow,
)
from solus_api.schemas import OAuthExchange, OAuthStart, serialize_source
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

router = APIRouter(prefix="/api/v1/integrations")

OAUTH_STATE_TTL_MINUTES = 10


@router.get("")
async def list_integrations(registry: RegistryDep, _user: CurrentUser) -> dict[str, Any]:
    """Catalog of available connector types + their config/auth shape."""
    return envelope(registry.catalog())


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


async def _reusable_source(
    session: SessionDep,
    project: Project,
    source_type: SourceType,
    connector: Connector,
) -> Source | None:
    """The source a re-connect should REUSE, or None to create a new one.

    Retrying a connect used to mint a fresh `Source` every time, so each attempt
    that reached the provider left another row behind and the project filled up
    with duplicates of one account.

    Whether a second source is meaningful is the CONNECTOR's business, read from
    the `selection` it declares:

    * **account-level** (`mode: "multi"` — Onshape and every CAD tool after it):
      one grant covers the whole account and the tracked set lives in that one
      source's config, so a second row for the same provider is never anything
      but a duplicate. Reuse it — which doubles as "switch account".
    * **item-level** (`mode: "single"` — GitHub, GitLab): a source names ONE
      repository, so several per project is a legitimate, wanted setup. Never
      collapse those.

    A connector that declares no selection keeps the old create-every-time
    behaviour rather than having a rule guessed for it.
    """
    selection = getattr(connector, "selection", None)
    if not isinstance(selection, dict) or selection.get("mode") != "multi":
        return None
    return (
        await session.scalars(
            select(Source)
            .where(
                Source.project_id == project.id,
                Source.type == source_type,
                Source.status != SourceStatus.DISCONNECTED,
            )
            .order_by(Source.created_at)
            .limit(1)
        )
    ).first()


@router.post("/{provider}/oauth/start", status_code=201)
async def oauth_start(
    provider: str,
    body: OAuthStart,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    source_type = _provider_type(provider)
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
    await check_can_add_integration(session, user)

    try:
        connector = registry.create(provider)
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", f"No connector for '{provider}'") from exc
    if not isinstance(connector, OAuthConnector):
        raise APIError(400, "not_oauth", f"'{provider}' does not use OAuth")

    config: dict[str, Any] = {"repo": body.repo} if body.repo else {}
    if body.access:
        # What the user actually granted, so "can Solus edit this?" is
        # answerable without re-deriving it from the token.
        config["access"] = body.access
    source = await _reusable_source(session, project, source_type, connector)
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

    state = pysecrets.token_urlsafe(32)
    redirect_uri = _resolve_redirect_uri(provider, body.redirect_uri, settings)
    session.add(
        OAuthState(
            state=state,
            provider=provider,
            source_id=source.id,
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

    emit_event(
        session,
        user=user,
        event_type="source.oauth_started",
        team_id=project.team_id,
        project_id=project.id,
        payload={"provider": provider},
    )
    await session.commit()
    return envelope({"authorize_url": authorize_url, "state": state, "source_id": str(source.id)})


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

    source, err = await _complete_oauth(session, registry, secret_store, provider, record, code)
    if err is not None or source is None:
        return RedirectResponse(
            _app_redirect(app_url, solus_connect=err or "error"), status_code=302
        )
    return RedirectResponse(
        _app_redirect(app_url, solus_connect="connected", source_id=str(source.id)),
        status_code=302,
    )


async def _complete_oauth(
    session: SessionDep,
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    provider: str,
    record: OAuthState,
    code: str,
) -> tuple[Source | None, str | None]:
    """Exchange the code, store the token, mark the source CONNECTED. Shared by
    the web callback (redirect) and the desktop exchange endpoint (JSON).
    Returns (source, None) on success or (source?, error_code)."""
    source = await session.get(Source, record.source_id)
    if source is None:
        await session.delete(record)
        await session.commit()
        return None, "error"

    connector = registry.create(provider)
    if not isinstance(connector, OAuthConnector):
        return source, "error"
    try:
        creds = await connector.exchange_code(code=code, redirect_uri=record.redirect_uri)
        account = await connector.validate_credentials(creds)
    except ConnectorError as exc:
        source.status = SourceStatus.ERROR
        # Bounded provider-supplied text (§7 — bound message sizes, SOLUSDEV-114).
        source.last_error = connector_error_payload(exc)
        await session.delete(record)
        await session.commit()
        return source, "oauth_failed"

    secret_ref = f"source/{source.id}/{provider}"
    await secret_store.put(secret_ref, creds.token)
    if creds.refresh_token:
        # SOLUS-CAD-01: providers with short-lived access tokens (Onshape: 60
        # minutes) need the refresh token at sync time. Stored under its own ref
        # so the access-token read path is unchanged for every existing source.
        await secret_store.put(refresh_secret_ref(secret_ref), creds.refresh_token)
    source.secret_ref = secret_ref
    source.status = SourceStatus.CONNECTED
    source.account_login = account.login
    source.account_external_id = account.external_id
    if not source.name or source.name == provider:
        source.name = account.login
    await session.delete(record)
    await session.commit()
    return source, None


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

    source, err = await _complete_oauth(
        session, registry, secret_store, provider, record, body.code
    )
    if err is not None or source is None:
        raise APIError(400, err or "oauth_failed", "OAuth exchange failed")
    return envelope(serialize_source(source))
