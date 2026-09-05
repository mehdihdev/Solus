"""SOLUSDEV-242 (HOME H2) — connections move to account scope.

A source connected before I1 owns its token under a `source/…` ref and never
appears on Home. It is CLAIMED to account scope only where the caller has
PROVED the account — a connection of their own for the same provider account —
because `created_by` never proved whose token a legacy row holds (the pre-I1
"switch account" path let any teammate complete a handshake on someone else's
row). Until then it is listed as "sign in once to move it" and keeps working
on its own token. Nothing is copied; nothing is widened.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from conftest import BOB, FakeGitHub, add_member, bearer, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import AccountInfo, ConnectorError, Credentials
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import SecretNotFoundError
from solus_api.models import AccountConnection, Membership, Role, Source
from solus_api.services.connections import connection_secret_ref
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class _IdentityOnshape(FakeGitHub):  # type: ignore[misc]  # conftest follow_imports=skip
    """Onshape's shape on the fake, with IDENTITY carried by the token: a token
    `tok:<who>` or a code `<who>` proves provider account `<who>`. That is what
    lets a test hold a row created by Alice whose token is Bob's."""

    provider = "onshape"
    selection = {"mode": "multi", "config_key": "documents", "label": "document"}
    supports_token_connect = True
    listings: ClassVar[int] = 0

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        if code == "bad-code":
            raise ConnectorError("oauth_exchange_failed", "bad verification code")
        return Credentials(token=f"oauth:{code}")

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        who = creds.token.split(":", 1)[1] if ":" in creds.token else "42"
        return AccountInfo(external_id=who, login=f"{who}@onshape", name=who)

    def validate_selection(self, ids: list[str]) -> None:
        from solus_api.connectors.onshape import tracked_document_ids

        tracked_document_ids({"documents": ids})

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        type(self).listings += 1
        return [{"id": "dA", "name": "Rover chassis"}, {"id": "dB", "name": "Gripper"}]


@pytest.fixture(autouse=True)
def _install_fakes(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    fake_registry.register("onshape", _IdentityOnshape)
    app.state.connector_registry = fake_registry


async def _team_and_project(
    client: AsyncClient, headers: dict[str, str], name: str = "Rover"
) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"], name=name)
    return str(team["id"]), str(project["id"])


async def _legacy_source(
    client: AsyncClient, headers: dict[str, str], project_id: str, who: str = "alice"
) -> dict[str, Any]:
    """A pre-I1 grant: the project holds its own token for account `who`."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "token": f"tok:{who}"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    assert data["status"] == "connected"
    return data


async def _adopt(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = await client.post("/api/v1/users/me/connections/adopt", headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _connections(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.get("/api/v1/users/me/connections", headers=headers)
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


async def _legacy(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.get("/api/v1/users/me/connections/legacy", headers=headers)
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


async def _source_row(db: AsyncSession, source_id: str) -> tuple[str | None, str | None, dict]:
    row = (
        await db.execute(
            select(Source.secret_ref, Source.connection_id, Source.config).where(
                Source.id == source_id
            )
        )
    ).one()
    return row[0], (str(row[1]) if row[1] else None), dict(row[2] or {})


async def _connect_on_home(
    client: AsyncClient, headers: dict[str, str], who: str = "alice", access: str | None = None
) -> dict[str, Any]:
    """The Home handshake, proving provider account `who`."""
    start = await client.post(
        "/api/v1/integrations/onshape/oauth/start",
        json={} if access is None else {"access": access},
        headers=headers,
    )
    assert start.status_code == 201, start.text
    exchange = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": start.json()["data"]["state"], "code": who},
        headers=headers,
    )
    assert exchange.status_code == 200, exchange.text
    connection: dict[str, Any] = exchange.json()["data"]["connection"]
    return connection


# ----------------------------------------------------------- listing, not moving


async def test_a_legacy_grant_is_listed_for_its_creator_not_moved(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    assert await _connections(client, alice_headers) == []
    (legacy,) = await _legacy(client, alice_headers)
    assert legacy["provider"] == "onshape"
    assert legacy["account_login"] == "alice@onshape"
    assert [p["project_id"] for p in legacy["projects"]] == [project_id]
    assert legacy["source_ids"] == [source["id"]]
    assert "secret" not in str(legacy) and "tok:" not in str(legacy)
    # Nothing moved: no connection, the project still owns its token.
    assert await _adopt(client, alice_headers) == {"adopted": [], "skipped": []}
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None


# ----------------------------------------------------------- the claim


async def test_the_home_sign_in_claims_the_legacy_grant_for_the_proved_account(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """The acceptance: connect once on Home; the existing project connection
    keeps working — now on the account grant, its old token retired."""
    team, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    store = app.state.secret_store
    assert await store.get(old_ref) == "tok:alice"

    home = await _connect_on_home(client, alice_headers, who="alice", access="read")

    (row,) = await _connections(client, alice_headers)
    assert row["id"] == home["id"] and row["status"] == "connected"
    assert row["access"] == "read" and row["needs_reauth"] is None
    assert [p["project_id"] for p in row["projects"]] == [project_id]
    assert await _legacy(client, alice_headers) == []
    ref, connection_id, config = await _source_row(db, source["id"])
    assert connection_id == home["id"]
    assert ref == connection_secret_ref(home["id"], "onshape")
    assert config.get("access") == "read"
    assert "retired_secret_refs" not in config  # swept after the commit
    with pytest.raises(SecretNotFoundError):
        await store.get(old_ref)
    feed = await client.get(
        f"/api/v1/teams/{team}/activity?project_id={project_id}&type=connection.adopted",
        headers=alice_headers,
    )
    assert [a["payload"]["provider"] for a in feed.json()["data"]] == ["onshape"]


async def test_adopt_claims_for_an_account_already_connected_on_home(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Home connected first, the legacy source appears later (another device,
    an old wizard): the next Home load binds it — no sign-in."""
    home = await _connect_on_home(client, alice_headers, who="alice")
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    result = await _adopt(client, alice_headers)
    assert [a["source_id"] for a in result["adopted"]] == [source["id"]]
    assert result["adopted"][0]["connection_id"] == home["id"]
    assert await _adopt(client, alice_headers) == {"adopted": [], "skipped": []}
    (row,) = await _connections(client, alice_headers)
    assert [p["project_id"] for p in row["projects"]] == [project_id]


async def test_two_legacy_projects_on_one_account_bind_to_one_connection(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    await _legacy_source(client, alice_headers, rover)
    await _legacy_source(client, alice_headers, arm)
    await _connect_on_home(client, alice_headers, who="alice")
    (row,) = await _connections(client, alice_headers)
    assert sorted(p["name"] for p in row["projects"]) == ["Arm", "Rover"]


async def test_a_claimed_source_serves_a_second_project_with_no_oauth(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    await _legacy_source(client, alice_headers, rover)
    home = await _connect_on_home(client, alice_headers, who="alice")
    bound = await client.post(
        f"/api/v1/projects/{arm}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": home["id"]},
        headers=alice_headers,
    )
    assert bound.status_code == 201, bound.text
    for doc in ("dA", "dB"):
        added = await client.post(
            f"/api/v1/projects/{arm}/sources/{bound.json()['data']['id']}/documents",
            json={"id": doc},
            headers=alice_headers,
        )
        assert added.status_code in (200, 202), added.text
    (row,) = await _connections(client, alice_headers)
    assert sorted(p["name"] for p in row["projects"]) == ["Arm", "Rover"]


async def test_an_errored_legacy_source_is_healed_by_the_proved_grant(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await db.execute(
        update(Source)
        .where(Source.id == source["id"])
        .values(status="error", last_error={"code": "invalid_credentials", "message": "revoked"})
    )
    await db.commit()
    await _connect_on_home(client, alice_headers, who="alice")
    detail = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
    )
    assert detail.json()["data"]["status"] == "connected"
    assert detail.json()["data"]["last_error"] is None


# ----------------------------------------------------------- what is NEVER moved


async def test_created_by_is_not_proof_a_row_holding_a_teammates_token_is_never_claimed(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
) -> None:
    """Security review C1: Alice created the row, Bob completed the handshake
    (pre-I1 "switch account"), so the token is BOB's. Alice proving HER account
    must not take it; Bob proving his does."""
    team, project_id = await _team_and_project(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    # Created by Alice, token and identity Bob's.
    source = await _legacy_source(client, alice_headers, project_id, who="bob")
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref

    await _connect_on_home(client, alice_headers, who="alice")
    assert await _adopt(client, alice_headers) == {"adopted": [], "skipped": []}
    (alice_row,) = await _connections(client, alice_headers)
    assert alice_row["projects"] == []
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref == old_ref and connection_id is None
    assert await app.state.secret_store.get(old_ref) == "tok:bob"
    # Alice's Home still lists it as legacy (she created it), honestly unmoved.
    assert len(await _legacy(client, alice_headers)) == 1

    bob_home = await _connect_on_home(client, bob_headers, who="bob")
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id == bob_home["id"]
    (bob_row,) = await _connections(client, bob_headers)
    assert [p["project_id"] for p in bob_row["projects"]] == [project_id]
    assert await _legacy(client, alice_headers) == []


async def test_a_removed_member_cannot_claim_or_list_a_grant_in_that_team(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Security review C2: leaving the team ends every reach into its sources."""
    team, project_id = await _team_and_project(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    source = await _legacy_source(client, bob_headers, project_id, who="bob")
    removed = await client.delete(
        f"/api/v1/teams/{team}/members/{bob['id']}", headers=alice_headers
    )
    assert removed.status_code in (200, 204), removed.text

    assert await _legacy(client, bob_headers) == []
    await _connect_on_home(client, bob_headers, who="bob")
    assert await _adopt(client, bob_headers) == {"adopted": [], "skipped": []}
    (row,) = await _connections(client, bob_headers)
    assert row["projects"] == []
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None
    feed = await client.get(
        f"/api/v1/teams/{team}/activity?type=connection.adopted", headers=alice_headers
    )
    assert feed.json()["data"] == []


async def test_a_viewer_cannot_claim_a_grant(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team, project_id = await _team_and_project(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    source = await _legacy_source(client, bob_headers, project_id, who="bob")
    await db.execute(
        update(Membership)
        .where(Membership.team_id == team, Membership.user_id == bob["id"])
        .values(role=Role.VIEWER)
    )
    await db.commit()
    assert await _legacy(client, bob_headers) == []
    await _connect_on_home(client, bob_headers, who="bob")
    assert await _adopt(client, bob_headers) == {"adopted": [], "skipped": []}
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id is None


async def test_a_grant_in_a_deleted_project_is_neither_listed_nor_claimed(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    deleted = await client.delete(
        f"/api/v1/projects/{project_id}?confirm=true", headers=alice_headers
    )
    assert deleted.status_code in (200, 204), deleted.text
    assert await _legacy(client, alice_headers) == []
    await _connect_on_home(client, alice_headers, who="alice")
    assert await _adopt(client, alice_headers) == {"adopted": [], "skipped": []}
    # Project teardown swept the source with it; nothing was left to claim.
    gone = (await db.execute(select(Source.id).where(Source.id == source["id"]))).first()
    assert gone is None


async def test_a_recorded_access_mismatch_is_reported_never_widened(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Security review H1: a read-only project must not silently become
    read-and-edit because the account grant is wider, nor lose a write token
    to a narrower grant. The source keeps its own token; the mismatch is said."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await db.execute(
        update(Source).where(Source.id == source["id"]).values(config={"access": "read"})
    )
    await db.commit()
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref

    await _connect_on_home(client, alice_headers, who="alice", access="write")
    result = await _adopt(client, alice_headers)
    assert result["adopted"] == []
    assert [s["reason"] for s in result["skipped"]] == ["access_mismatch"]
    ref, connection_id, config = await _source_row(db, source["id"])
    assert ref == old_ref and connection_id is None and config["access"] == "read"
    assert await app.state.secret_store.get(old_ref) == "tok:alice"
    # Scope sets stay the connector's, fixed in code.
    modes = {m["id"]: tuple(m["scopes"]) for m in (OnshapeConnector.access_modes or {})["modes"]}
    assert modes == {"read": ("OAuth2Read",), "write": ("OAuth2Read", "OAuth2Write")}
    assert OnshapeConnector.scopes == ("OAuth2Read",)


async def test_a_grant_whose_access_was_never_recorded_takes_the_proved_grants_access(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await _connect_on_home(client, alice_headers, who="alice", access="read")
    _, connection_id, config = await _source_row(db, source["id"])
    assert connection_id is not None and config["access"] == "read"


async def test_non_oauth_and_already_bound_sources_are_left_alone(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    kicad = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "board", "config": {"export": "hw/board.xml"}},
        headers=alice_headers,
    )
    assert kicad.status_code == 201, kicad.text
    home = await _connect_on_home(client, alice_headers, who="alice")
    bound = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": home["id"]},
        headers=alice_headers,
    )
    assert bound.status_code == 201, bound.text
    assert await _legacy(client, alice_headers) == []
    assert await _adopt(client, alice_headers) == {"adopted": [], "skipped": []}


# ----------------------------------------------------------- robustness


async def test_concurrent_adopt_calls_claim_once_and_never_500(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    home = await _connect_on_home(client, alice_headers, who="alice")
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    responses = await asyncio.gather(
        *(
            client.post("/api/v1/users/me/connections/adopt", headers=alice_headers)
            for _ in range(3)
        )
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    claimed = [a for r in responses for a in r.json()["data"]["adopted"]]
    assert {a["source_id"] for a in claimed} == {source["id"]}
    assert len(await _connections(client, alice_headers)) == 1
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id == home["id"]


async def test_a_failed_retirement_is_retried_not_leaked(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review M2: the retired refs live on the source until deleted."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    store = app.state.secret_store
    real_delete = store.delete

    async def failing_delete(ref: str) -> None:
        raise RuntimeError("store outage")

    monkeypatch.setattr(store, "delete", failing_delete)
    await _connect_on_home(client, alice_headers, who="alice")
    _, connection_id, config = await _source_row(db, source["id"])
    assert connection_id is not None
    assert old_ref in config["retired_secret_refs"]  # remembered, not lost
    assert await store.get(old_ref) == "tok:alice"

    monkeypatch.setattr(store, "delete", real_delete)
    await _adopt(client, alice_headers)  # the sweep runs again
    _, _, config = await _source_row(db, source["id"])
    assert "retired_secret_refs" not in config
    with pytest.raises(SecretNotFoundError):
        await store.get(old_ref)


async def test_an_errored_connection_never_claims(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Security review M4: only a CONNECTED grant with a secret is proof."""
    home = await _connect_on_home(client, alice_headers, who="alice")
    await db.execute(
        update(AccountConnection).where(AccountConnection.id == home["id"]).values(status="error")
    )
    await db.commit()
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    assert (await _adopt(client, alice_headers))["adopted"] == []
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id is None
    (row,) = await _connections(client, alice_headers)
    assert row["needs_reauth"] == "token_error"


async def test_adopt_requires_a_verified_signed_in_user(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/users/me/connections/adopt")).status_code == 401
    unverified = bearer("unverified-sub-h2", "unverified-h2@example.com", email_verified=False)
    await me(client, unverified)
    resp = await client.post("/api/v1/users/me/connections/adopt", headers=unverified)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"
    assert (await client.get("/api/v1/users/me/connections/legacy")).status_code == 401
