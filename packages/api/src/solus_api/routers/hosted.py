"""Hosted MCP add-ons on a connected Source (SOLUSDEV-168).

FeatureScript is **not a separate tile**: it is an add-on to an Onshape
connection the customer already made. So these routes nest under the Source,
which is what makes tenancy structural — `ProjectCtx` resolves auth and team
scope before any handler runs, and `_scoped_source` reports a Source in another
project as 404 rather than 403 (no existence oracle).

**Completion is AUTHENTICATED, deliberately.** The connector flow offers two
paths: an unauthenticated `GET /{provider}/oauth/callback` verified only by the
`state` row, and an authenticated `POST /{provider}/oauth/exchange` that also
checks `record.user_id == user.id` (`integrations.py:251-280` vs `:345`). Only
the second is offered here. The first never compares the requesting user, and
`oauth/start` hands the raw `state` back to its caller — so an attacker can mint
a state on their own project, get a victim to complete the authorize leg, and
have the victim's token stored against the attacker's source. With
`OAuth2Write` that escalates from reading someone's CAD to writing FeatureScript
into their Feature Studios. The desktop already captures the code on its
loopback, so the authenticated exchange costs nothing.

**Subscription cannot be granted programmatically.** The Onshape public API has
no purchase-creating operation, and the Billing guide's only path is a browser
redirect scoped to the *calling app's own* products — Solus is not the
publisher. Onshape further warns not to trust the redirect's own success
signal. So enabling is: deep-link out, and DETECT completion by capability
probe. `probe` is that detection, and it is honest about what it cannot tell
apart.
"""

from __future__ import annotations

import logging
import secrets as pysecrets
import time
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from solus_api.agent.tools.hosted_tools import INVENTORY_KEY, STATE_KEY, _hosted_source_available
from solus_api.agent.tools.mcp_tool import MCPServerSpec, discover_mcp_tools
from solus_api.agent.tools.remote_mcp import HOSTED_SERVERS, RemoteAuthError, RemoteMCPSpec
from solus_api.agent.tools.tool import ToolException
from solus_api.connectors import hosted_oauth
from solus_api.connectors.hosted_oauth import HostedToken
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    ProjectCtx,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    require_role,
)
from solus_api.models import AccountConnection, OAuthState, Role, Source, utcnow
from solus_api.schemas import StrictModel
from solus_api.services import hosted_accounts
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.routers.hosted")

router = APIRouter(prefix="/api/v1/projects/{project_id}/sources/{source_id}/hosted")

#: Short, like the connector handshake it mirrors.
STATE_TTL_MINUTES = 10
#: `OAuthState.provider` is a plain 32-char string column, not the SourceType
#: enum — so a hosted grant can share the table without widening SourceType
#: (which would put FeatureScript in the connector catalog, i.e. give it a tile).
_STATE_PREFIX = "hosted:"

#: What the customer sees, and what the source card renders.
STATE_READY = "ready"
STATE_SUBSCRIPTION_REQUIRED = "subscription_required"
STATE_NOT_ENABLED = "not_enabled"


class HostedExchange(StrictModel):
    """The desktop posts back what its loopback captured."""

    state: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=2048)


def _spec(server: str) -> RemoteMCPSpec:
    spec = HOSTED_SERVERS.get(server)
    if spec is None:
        raise APIError(404, "unknown_hosted_server", f"No hosted server '{server}'")
    return spec


async def _scoped_source(session: SessionDep, ctx: ProjectCtx, source_id: uuid.UUID) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.project_id != ctx.project.id:
        raise APIError(404, "not_found", "Source not found")
    return source


def _matching_source(source: Source, spec: RemoteMCPSpec) -> None:
    if source.type is not spec.source_type:
        raise APIError(
            400,
            "wrong_source_type",
            f"{spec.name} attaches to a {spec.source_type.value} source",
        )
    if not source.secret_ref:
        raise APIError(400, "source_not_connected", "Connect this source before enabling add-ons")


def _state_of(source: Source | AccountConnection, server: str) -> dict[str, Any]:
    states = source.config.get(STATE_KEY) if isinstance(source.config, dict) else None
    entry = states.get(server) if isinstance(states, dict) else None
    return dict(entry) if isinstance(entry, dict) else {"state": STATE_NOT_ENABLED}


def _write_state(source: Source | AccountConnection, server: str, entry: dict[str, Any]) -> None:
    """Config is a JSON column — REASSIGN it, never mutate in place, or
    SQLAlchemy will not mark it dirty and the write is silently lost."""
    config = dict(source.config or {})
    states = dict(config.get(STATE_KEY) or {})
    states[server] = entry
    config[STATE_KEY] = states
    source.config = config


def _write_inventory(
    source: Source | AccountConnection, server: str, entry: dict[str, Any] | None
) -> None:
    config = dict(source.config or {})
    stored = dict(config.get(INVENTORY_KEY) or {})
    if entry is None:
        stored.pop(server, None)
    else:
        stored[server] = entry
    config[INVENTORY_KEY] = stored
    source.config = config


def _payload(source: Source | AccountConnection, spec: RemoteMCPSpec) -> dict[str, Any]:
    entry = _state_of(source, spec.name)
    return {
        "server": spec.name,
        "state": entry.get("state", STATE_NOT_ENABLED),
        "tool_count": entry.get("tool_count", 0),
        "checked_at": entry.get("checked_at"),
        # Copy is Solus-authored and lives with the spec, so a surface can render
        # it without knowing which server it is (the `access_modes` treatment).
        "notice": spec.connect_notice,
        "subscribe_url": spec.subscribe_url,
        "detail": entry.get("detail"),
    }


# ------------------------------------------------------------ capability probe


async def _probe(
    spec: RemoteMCPSpec, source: Source | AccountConnection, secret_store: Any
) -> tuple[str, list[dict[str, Any]], str | None]:
    """`(state, inventory_rows, detail)` — is this account actually usable?

    The ONLY detection mechanism available. There is no purchase API to query
    and no webhook: Onshape's 26 documented events carry none, and
    `GET /accounts/purchases` returns purchases for plans owned by *the calling
    application*, which Solus is not. So we attempt the handshake and read the
    outcome.

    **Honest about its resolution.** One signal cannot separate "not subscribed"
    from "your company admin has not permitted Onshape Labs" from a plan-tier
    refusal — and Onshape's own docs contradict each other on whether Labs
    access is admin-gated at all. So a post-authentication failure names BOTH
    remedies and carries the server's own words, rather than asserting a cause
    Solus cannot actually distinguish.
    """
    ref = hosted_oauth.token_secret_ref(source.secret_ref or "", spec.name)
    try:
        token = HostedToken.from_json(await secret_store.get(ref))
    except Exception:
        return STATE_NOT_ENABLED, [], None
    try:
        if token.expired(now=time.time()):
            client = await hosted_oauth.ensure_client(
                secret_store, spec, redirect_uri=hosted_oauth.registered_redirect_uri(spec)
            )
            token = await hosted_oauth.refresh_token(spec, client, token)
            await secret_store.put(ref, token.to_json())
    except RemoteAuthError as exc:
        return STATE_NOT_ENABLED, [], exc.message

    async def _headers() -> dict[str, str]:
        return {"Authorization": f"Bearer {token.access_token}"}

    try:
        tools = await discover_mcp_tools(
            MCPServerSpec(name=spec.name, url=spec.url),
            secret_store,
            policy=spec,
            headers_provider=_headers,
            # Server-authored prose inside a JSON Schema reaches the model
            # UNFENCED (`prompt.py` fences `description`, but passes `params`
            # through verbatim), so a hosted server's schemas are stripped to
            # structure before anything stores or shows them.
            strip_schema_prose=True,
        )
    except ToolException as exc:
        # Authenticated but unusable. This is the subscription/Labs bucket — and
        # the honest answer is both remedies plus what the server actually said.
        logger.info("hosted probe for %r failed: %s", spec.name, exc.code)
        return STATE_SUBSCRIPTION_REQUIRED, [], exc.message
    if not tools:
        return (
            STATE_SUBSCRIPTION_REQUIRED,
            [],
            "The FeatureScript service accepted the sign-in but offered no tools.",
        )
    rows = [
        {
            "name": tool.descriptor.name,
            "remote_name": tool.remote_name,
            "description": tool.descriptor.description,
            "params": tool.descriptor.params,
            "returns": tool.descriptor.returns,
            "requires_confirmation": tool.descriptor.requires_confirmation,
            "consent_summary": tool.descriptor.consent_summary,
        }
        for tool in tools
    ]
    return STATE_READY, rows, None


async def _record_probe(
    session: SessionDep, source: Source | AccountConnection, spec: RemoteMCPSpec, secret_store: Any
) -> dict[str, Any]:
    state, rows, detail = await _probe(spec, source, secret_store)
    _write_state(
        source,
        spec.name,
        {
            "state": state,
            "tool_count": len(rows),
            "checked_at": utcnow().isoformat(),
            # Upstream text, bounded (§7). It is shown to the customer because a
            # vendor's own refusal is more actionable than our paraphrase, and it
            # is NEVER shown to the model.
            "detail": (detail or "")[:500] or None,
        },
    )
    _write_inventory(
        source,
        spec.name,
        {"tools": rows, "account_ref": source.account_external_id or ""} if rows else None,
    )
    await session.commit()
    return _payload(source, spec)


# ------------------------------------------------------------------- routes


@router.get("/{server}")
async def hosted_status(
    server: str,
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    """The stored state. Cheap: no network, so a source list can render it."""
    require_role(ctx, Role.VIEWER)
    spec = _spec(server)
    source = await _scoped_source(session, ctx, source_id)
    account = await hosted_accounts.source_account(session, source, spec)
    return envelope(_payload(account or source, spec))


@router.post("/{server}/probe")
async def hosted_probe(
    server: str,
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    _verified: RequireVerified,
    session: SessionDep,
    secret_store: SecretStoreDep,
) -> dict[str, Any]:
    """Re-check after the customer says they have subscribed.

    Onshape warns explicitly that a redirect back with `success=true` does NOT
    mean a purchase happened, so this is the only trustworthy completion signal
    — and it is user-triggered rather than a poll, because the purchase can wait
    on a company administrator and no timer we own would outlive that.
    """
    require_role(ctx, Role.MEMBER)
    spec = _spec(server)
    source = await _scoped_source(session, ctx, source_id)
    _matching_source(source, spec)
    account = await hosted_accounts.source_account(session, source, spec, owner_id=ctx.user.id)
    if account is not None:
        return envelope(await hosted_accounts.probe(session, ctx.user, account, spec, secret_store))
    return envelope(await _record_probe(session, source, spec, secret_store))


@router.post("/{server}/oauth/start", status_code=201)
async def hosted_oauth_start(
    server: str,
    source_id: uuid.UUID,
    ctx: ProjectCtx,
    _verified: RequireVerified,
    session: SessionDep,
    secret_store: SecretStoreDep,
) -> dict[str, Any]:
    """Begin the customer's own grant to the hosted server.

    A SECOND handshake, not a widening of the Onshape one: the hosted server is
    its own authorization server with its own token, which is also why enabling
    this costs an existing Onshape user no re-consent on their original grant.
    """
    require_role(ctx, Role.MEMBER)
    spec = _spec(server)
    source = await _scoped_source(session, ctx, source_id)
    _matching_source(source, spec)
    account = await hosted_accounts.source_account(session, source, spec, owner_id=ctx.user.id)
    if account is not None:
        return envelope(await hosted_accounts.start(session, ctx.user, account, spec, secret_store))

    redirect_uri = hosted_oauth.registered_redirect_uri(spec)
    try:
        client = await hosted_oauth.ensure_client(secret_store, spec, redirect_uri=redirect_uri)
    except RemoteAuthError as exc:
        raise APIError(502, exc.code, exc.message) from exc

    state = pysecrets.token_urlsafe(32)
    verifier, challenge = hosted_oauth.new_pkce()
    session.add(
        OAuthState(
            state=state,
            provider=f"{_STATE_PREFIX}{spec.name}",
            source_id=source.id,
            user_id=ctx.user.id,
            redirect_uri=redirect_uri,
            # The verifier CANNOT live on a coroutine: authorize and callback are
            # two requests, possibly two workers. It dies with this row.
            code_verifier=verifier,
            expires_at=utcnow() + timedelta(minutes=STATE_TTL_MINUTES),
        )
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="source.hosted_oauth_started",
        team_id=ctx.project.team_id,
        project_id=ctx.project.id,
        payload={"server": spec.name},
    )
    await session.commit()
    return envelope(
        {
            "authorize_url": hosted_oauth.authorize_url(
                spec, client, state=state, code_challenge=challenge, redirect_uri=redirect_uri
            ),
            "state": state,
            "redirect_uri": redirect_uri,
            "notice": spec.connect_notice,
        }
    )


@router.post("/{server}/oauth/exchange")
async def hosted_oauth_exchange(
    server: str,
    source_id: uuid.UUID,
    body: HostedExchange,
    ctx: ProjectCtx,
    _verified: RequireVerified,
    session: SessionDep,
    secret_store: SecretStoreDep,
) -> dict[str, Any]:
    """Complete the grant, then immediately probe what it can actually do."""
    require_role(ctx, Role.MEMBER)
    spec = _spec(server)
    source = await _scoped_source(session, ctx, source_id)
    _matching_source(source, spec)

    account = await hosted_accounts.source_account(session, source, spec, owner_id=ctx.user.id)
    if account is not None:
        return envelope(
            await hosted_accounts.exchange(
                session, ctx.user, account, spec, secret_store, state=body.state, code=body.code
            )
        )
    original_ref = source.secret_ref
    verifier, redirect_uri = await hosted_accounts.consume_state(
        session, state=body.state, user_id=ctx.user.id, server=spec.name, source_id=source.id
    )

    try:
        client = await hosted_oauth.ensure_client(secret_store, spec, redirect_uri=redirect_uri)
        token = await hosted_oauth.exchange_code(
            spec, client, code=body.code, code_verifier=verifier, redirect_uri=redirect_uri
        )
    except RemoteAuthError as exc:
        await session.commit()
        raise APIError(400, exc.code, exc.message) from exc

    current = await session.scalar(
        select(Source)
        .where(
            Source.id == source_id,
            Source.project_id == ctx.project.id,
            _hosted_source_available(),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        current is None
        or current.connection_id is not None
        or current.secret_ref != original_ref
    ):
        raise APIError(404, "not_found", "Connected source not found")
    source = current
    await secret_store.put(
        hosted_oauth.token_secret_ref(source.secret_ref or "", spec.name), token.to_json()
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="source.hosted_connected",
        team_id=ctx.project.team_id,
        project_id=ctx.project.id,
        payload={"server": spec.name},
    )
    return envelope(await _record_probe(session, source, spec, secret_store))
