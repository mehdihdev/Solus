"""SOLUSDEV-242 (HOME H2) — connections move to account scope.

A source connected before I1 owns its token under a `source/…` ref and never
appears on Home. Adoption moves it to an ACCOUNT connection without a sign-in:
the token is copied, the source mirrors the connection, the project keeps
syncing, and nothing is widened — a grant whose access mode was never recorded
is flagged for re-consent rather than assumed.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import BOB, FakeGitHub, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import refresh_secret_ref
from solus_api.connectors.secrets import SecretNotFoundError
from solus_api.models import AccountConnection, Source
from solus_api.services.connections import connection_secret_ref
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class _AccountLevelOnshape(FakeGitHub):  # type: ignore[misc]  # conftest follow_imports=skip
    """Onshape's shape on the fake: OAuth, account-level selection, and — like
    every pre-I1 wizard path — token-connectable, which is how a LEGACY
    project-scoped grant is minted through the real route."""

    provider = "onshape"
    selection = {"mode": "multi", "config_key": "documents", "label": "document"}
    supports_token_connect = True


@pytest.fixture(autouse=True)
def _install_fakes(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    fake_registry.register("onshape", _AccountLevelOnshape)
    app.state.connector_registry = fake_registry


async def _project(client: AsyncClient, headers: dict[str, str], name: str = "Rover") -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"], name=name)
    project_id: str = project["id"]
    return project_id


async def _legacy_source(
    client: AsyncClient, headers: dict[str, str], project_id: str, token: str = "legacy-token"
) -> dict[str, Any]:
    """A pre-I1 grant: the project holds its own token, no connection row."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "token": token},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    assert data["status"] == "connected"
    return data


async def _adopt(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.post("/api/v1/users/me/connections/adopt", headers=headers)
    assert resp.status_code == 200, resp.text
    adopted: list[dict[str, Any]] = resp.json()["data"]["adopted"]
    return adopted


async def _connections(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.get("/api/v1/users/me/connections", headers=headers)
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


async def _source_row(db: AsyncSession, source_id: str) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(Source.secret_ref, Source.connection_id).where(Source.id == source_id)
        )
    ).one()
    return row[0], (str(row[1]) if row[1] else None)


async def _connect_on_home(
    client: AsyncClient, headers: dict[str, str], access: str | None = None
) -> dict[str, Any]:
    start = await client.post(
        "/api/v1/integrations/onshape/oauth/start",
        json={} if access is None else {"access": access},
        headers=headers,
    )
    assert start.status_code == 201, start.text
    started = start.json()["data"]
    exchange = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": started["state"], "code": "good"},
        headers=headers,
    )
    assert exchange.status_code == 200, exchange.text
    connection: dict[str, Any] = exchange.json()["data"]["connection"]
    return connection


# ----------------------------------------------------------- adoption


async def test_a_legacy_project_grant_becomes_an_account_connection_without_a_sign_in(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _ = await _source_row(db, source["id"])
    assert old_ref and old_ref.startswith("source/")
    assert await _connections(client, alice_headers) == []  # invisible on Home before H2

    adopted = await _adopt(client, alice_headers)
    assert [a["source_id"] for a in adopted] == [source["id"]]

    listed = await _connections(client, alice_headers)
    assert len(listed) == 1
    row = listed[0]
    assert row["provider"] == "onshape"
    assert row["status"] == "connected"
    assert row["origin"] == "migrated"
    assert row["account_login"] == source["account_login"]
    assert [p["project_id"] for p in row["projects"]] == [project_id]
    # Never recorded which grant the token carries → say so, do not assume.
    assert row["access"] is None
    assert row["needs_reauth"] == "access_unknown"
    assert "secret" not in str(row)

    # The source now MIRRORS the connection and the very same token moved with it.
    new_ref, connection_id = await _source_row(db, source["id"])
    assert connection_id == row["id"]
    assert new_ref == connection_secret_ref(row["id"], "onshape")
    store = app.state.secret_store
    assert await store.get(new_ref) == "legacy-token"
    with pytest.raises(SecretNotFoundError):
        await store.get(old_ref)  # the project-owned copy is retired after commit


async def test_adoption_is_idempotent(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id = await _project(client, alice_headers)
    await _legacy_source(client, alice_headers, project_id)
    assert len(await _adopt(client, alice_headers)) == 1
    assert await _adopt(client, alice_headers) == []
    assert len(await _connections(client, alice_headers)) == 1


async def test_a_recorded_access_mode_is_kept_and_never_widened(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    # A SOLUS-ONS-A2-era source recorded the grant it was authorized with.
    await db.execute(
        update(Source).where(Source.id == source["id"]).values(config={"access": "read"})
    )
    await db.commit()

    await _adopt(client, alice_headers)
    (row,) = await _connections(client, alice_headers)
    assert row["access"] == "read"
    assert row["needs_reauth"] is None
    # The scopes a re-consent would request are the connector's, fixed in code:
    # read stays read, and nothing here asks for more than the source had.
    modes = {m["id"]: tuple(m["scopes"]) for m in (OnshapeConnector.access_modes or {})["modes"]}
    assert modes == {"read": ("OAuth2Read",), "write": ("OAuth2Read", "OAuth2Write")}
    assert OnshapeConnector.scopes == ("OAuth2Read",)


async def test_two_legacy_projects_on_one_account_share_one_connection(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    await _legacy_source(client, alice_headers, rover)
    await _legacy_source(client, alice_headers, arm)

    adopted = await _adopt(client, alice_headers)
    assert len(adopted) == 2
    assert len({a["connection_id"] for a in adopted}) == 1
    (row,) = await _connections(client, alice_headers)
    assert sorted(p["name"] for p in row["projects"]) == ["Arm", "Rover"]


async def test_a_legacy_grant_lands_on_the_account_already_connected_on_home(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """The account's CURRENT grant wins; the project's own copy is retired and
    no second row appears for the same account."""
    project_id = await _project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id, token="stale-project-token")
    old_ref, _ = await _source_row(db, source["id"])
    home = await _connect_on_home(client, alice_headers, access="read")

    adopted = await _adopt(client, alice_headers)
    assert [a["connection_id"] for a in adopted] == [home["id"]]
    listed = await _connections(client, alice_headers)
    assert [c["id"] for c in listed] == [home["id"]]
    assert listed[0]["origin"] == "home"
    assert listed[0]["access"] == "read"
    assert listed[0]["needs_reauth"] is None
    new_ref, connection_id = await _source_row(db, source["id"])
    assert connection_id == home["id"]
    assert new_ref == connection_secret_ref(home["id"], "onshape")
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(old_ref)


async def test_only_the_authorizing_user_adopts_a_grant(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """A teammate's project-scoped token is THEIR account, not the caller's."""
    await me(client, alice_headers)
    bob = await me(client, bob_headers)
    team = (await create_team(client, alice_headers))["id"]
    await add_member(client, alice_headers, bob_headers, BOB, team)
    project = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    await _legacy_source(client, bob_headers, project)

    assert await _adopt(client, alice_headers) == []
    assert await _connections(client, alice_headers) == []
    adopted = await _adopt(client, bob_headers)
    assert len(adopted) == 1
    (row,) = await _connections(client, bob_headers)
    assert row["provider"] == "onshape"
    assert bob["id"]  # Bob is the owner; Alice never sees it.
    assert await _connections(client, alice_headers) == []


async def test_non_oauth_and_already_bound_sources_are_left_alone(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    # A committed-export connector carries no tool credential.
    kicad = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "board", "config": {"export": "hw/board.xml"}},
        headers=alice_headers,
    )
    assert kicad.status_code == 201, kicad.text
    # A source bound on Home is already at account scope.
    home = await _connect_on_home(client, alice_headers)
    bound = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": home["id"]},
        headers=alice_headers,
    )
    assert bound.status_code == 201, bound.text

    assert await _adopt(client, alice_headers) == []
    assert len(await _connections(client, alice_headers)) == 1


async def test_a_source_whose_token_is_gone_is_skipped_not_invented(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _ = await _source_row(db, source["id"])
    await app.state.secret_store.delete(old_ref)

    assert await _adopt(client, alice_headers) == []
    assert await _connections(client, alice_headers) == []
    ref, connection_id = await _source_row(db, source["id"])
    assert ref == old_ref and connection_id is None


# ----------------------------------------------------------- after adoption


async def test_a_second_project_reuses_the_adopted_account_with_no_oauth(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The acceptance: an existing project connection still works, and a second
    project picks documents from that account with no second OAuth prompt."""
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    await _legacy_source(client, alice_headers, rover)
    (adopted,) = await _adopt(client, alice_headers)

    bound = await client.post(
        f"/api/v1/projects/{arm}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": adopted["connection_id"]},
        headers=alice_headers,
    )
    assert bound.status_code == 201, bound.text
    assert bound.json()["data"]["status"] == "connected"
    for doc in ("dA", "dB"):
        added = await client.post(
            f"/api/v1/projects/{arm}/sources/{bound.json()['data']['id']}/documents",
            json={"id": doc},
            headers=alice_headers,
        )
        assert added.status_code in (200, 202), added.text
    (row,) = await _connections(client, alice_headers)
    assert sorted(p["name"] for p in row["projects"]) == ["Arm", "Rover"]


async def test_re_consent_lands_on_the_migrated_row_and_keeps_the_old_token_until_then(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    (adopted,) = await _adopt(client, alice_headers)
    ref = connection_secret_ref(adopted["connection_id"], "onshape")
    store = app.state.secret_store
    assert await store.get(ref) == "legacy-token"

    # The user re-authorizes from Home, choosing the grant this time.
    start = await client.post(
        "/api/v1/integrations/onshape/oauth/start", json={"access": "read"}, headers=alice_headers
    )
    assert start.status_code == 201, start.text
    # Until the handshake completes, the migrated token is untouched and listed.
    assert await store.get(ref) == "legacy-token"
    (before,) = await _connections(client, alice_headers)
    assert before["needs_reauth"] == "access_unknown"

    exchange = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": start.json()["data"]["state"], "code": "good"},
        headers=alice_headers,
    )
    assert exchange.status_code == 200, exchange.text
    assert exchange.json()["data"]["connection"]["id"] == adopted["connection_id"]

    (after,) = await _connections(client, alice_headers)
    assert after["id"] == adopted["connection_id"]
    assert after["needs_reauth"] is None
    assert after["access"] == "read"
    assert after["origin"] == "migrated"
    assert await store.get(ref) != "legacy-token"  # rotated in place
    new_ref, connection_id = await _source_row(db, source["id"])
    assert connection_id == adopted["connection_id"] and new_ref == ref
    with pytest.raises(SecretNotFoundError):
        await store.get(refresh_secret_ref("source/never"))  # sanity: unrelated refs untouched


async def test_adoption_records_activity_for_the_project(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    project = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    await _legacy_source(client, alice_headers, project)
    await _adopt(client, alice_headers)
    feed = await client.get(
        f"/api/v1/teams/{team}/activity?project_id={project}&type=connection.adopted",
        headers=alice_headers,
    )
    assert feed.status_code == 200
    assert [a["payload"]["provider"] for a in feed.json()["data"]] == ["onshape"]


async def test_an_adopted_connection_row_is_a_live_row(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _project(client, alice_headers)
    await _legacy_source(client, alice_headers, project_id)
    (adopted,) = await _adopt(client, alice_headers)
    row = (
        await db.execute(
            select(AccountConnection.status, AccountConnection.config).where(
                AccountConnection.id == adopted["connection_id"]
            )
        )
    ).one()
    assert row[0].value == "connected"
    assert row[1]["origin"] == "migrated"
