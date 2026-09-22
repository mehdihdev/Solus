"""Owner-only hosted add-ons on an existing account grant (SOLUSDEV-261)."""

import uuid
from typing import Any

from fastapi import APIRouter

from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, RequireVerified, SecretStoreDep, SessionDep
from solus_api.routers.hosted import HostedExchange, _payload, _spec
from solus_api.services import hosted_accounts

router = APIRouter(prefix="/api/v1/users/me/connections/{connection_id}/hosted")


@router.get("/{server}")
async def status(
    connection_id: uuid.UUID, server: str, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    spec = _spec(server)
    account = await hosted_accounts.connected_account(
        session, connection_id, spec, owner_id=user.id
    )
    return envelope(_payload(account, spec))


@router.post("/{server}/oauth/start", status_code=201)
async def start(
    connection_id: uuid.UUID,
    server: str,
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    spec = _spec(server)
    account = await hosted_accounts.connected_account(
        session, connection_id, spec, owner_id=user.id
    )
    return envelope(await hosted_accounts.start(session, user, account, spec, secret_store))


@router.post("/{server}/oauth/exchange")
async def exchange(
    connection_id: uuid.UUID,
    server: str,
    body: HostedExchange,
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    spec = _spec(server)
    account = await hosted_accounts.connected_account(
        session, connection_id, spec, owner_id=user.id
    )
    return envelope(
        await hosted_accounts.exchange(
            session, user, account, spec, secret_store, state=body.state, code=body.code
        )
    )


@router.post("/{server}/probe")
async def probe(
    connection_id: uuid.UUID,
    server: str,
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    spec = _spec(server)
    account = await hosted_accounts.connected_account(
        session, connection_id, spec, owner_id=user.id
    )
    return envelope(await hosted_accounts.probe(session, user, account, spec, secret_store))
