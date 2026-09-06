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


async def _adopt(
    client: AsyncClient,
    headers: dict[str, str],
    source_ids: list[str] | None = None,
    *,
    confirm_access: bool = False,
) -> dict[str, Any]:
    """The confirmed move: names the sources. With no ids given, every legacy
    source the caller is shown is named (what Home's confirmation would send
    for one row after another)."""
    if source_ids is None:
        source_ids = [sid for row in await _legacy(client, headers) for sid in row["source_ids"]]
    if not source_ids:
        return {"adopted": [], "skipped": []}
    resp = await client.post(
        "/api/v1/users/me/connections/adopt",
        json={"source_ids": source_ids, "confirm_access": confirm_access},
        headers=headers,
    )
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
    db.expire_all()
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
    """The Home handshake, proving provider account `who`. Proof only — nothing
    moves until the user confirms the move (`_adopt`)."""
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
    assert legacy["claimable_connection_id"] is None  # no proof yet
    assert "secret" not in str(legacy) and "tok:" not in str(legacy)
    # Naming it without proof moves nothing.
    result = await _adopt(client, alice_headers, [source["id"]])
    assert result["adopted"] == []
    assert [x["reason"] for x in result["skipped"]] == ["not_claimable"]
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None


async def test_a_handshake_proves_the_account_but_moves_nothing_by_itself(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Security review H-NEW-1: the move is the user's explicit, confirmed
    request — never a side effect of a handshake or of loading Home."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    home = await _connect_on_home(client, alice_headers, who="alice", access="read")
    (legacy,) = await _legacy(client, alice_headers)
    assert legacy["claimable_connection_id"] == home["id"]
    (row,) = await _connections(client, alice_headers)
    assert row["projects"] == []
    ref, connection_id, config = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None
    assert "_legacy_secrets_retire" not in config


# ----------------------------------------------------------- the confirmed move


async def test_the_confirmed_move_binds_the_source_to_the_proved_grant(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """The acceptance: connect once on Home, confirm the move; the existing
    project connection keeps working — now on the account grant, its own
    token retired."""
    team, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    store = app.state.secret_store
    assert await store.get(old_ref) == "tok:alice"
    home = await _connect_on_home(client, alice_headers, who="alice", access="read")

    result = await _adopt(client, alice_headers, [source["id"]])
    assert [a["source_id"] for a in result["adopted"]] == [source["id"]]
    assert result["adopted"][0]["connection_id"] == home["id"]
    assert result["skipped"] == []

    (row,) = await _connections(client, alice_headers)
    assert row["id"] == home["id"] and row["access"] == "read"
    assert [p["project_id"] for p in row["projects"]] == [project_id]
    assert await _legacy(client, alice_headers) == []
    ref, connection_id, config = await _source_row(db, source["id"])
    assert connection_id == home["id"]
    assert ref == connection_secret_ref(home["id"], "onshape")
    assert config.get("access") == "read"
    assert "_legacy_secrets_retire" not in config  # swept after the commit
    with pytest.raises(SecretNotFoundError):
        await store.get(old_ref)
    # Idempotent: a second move of the same ids names nothing claimable.
    again = await _adopt(client, alice_headers, [source["id"]])
    assert again["adopted"] == [] and [x["reason"] for x in again["skipped"]] == ["not_claimable"]
    feed = await client.get(
        f"/api/v1/teams/{team}/activity?project_id={project_id}&type=connection.adopted",
        headers=alice_headers,
    )
    assert [a["payload"]["provider"] for a in feed.json()["data"]] == ["onshape"]


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
    (legacy,) = await _legacy(client, alice_headers)
    assert len(legacy["source_ids"]) == 2
    result = await _adopt(client, alice_headers, legacy["source_ids"])
    assert len(result["adopted"]) == 2 and len({a["connection_id"] for a in result["adopted"]}) == 1
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
    await _adopt(client, alice_headers)
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
    await _adopt(client, alice_headers)
    detail = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
    )
    assert detail.json()["data"]["status"] == "connected"
    assert detail.json()["data"]["last_error"] is None


async def test_a_syncing_source_is_not_a_candidate(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Security review M-NEW-5: a worker holds that token right now."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await db.execute(update(Source).where(Source.id == source["id"]).values(status="syncing"))
    await db.commit()
    await _connect_on_home(client, alice_headers, who="alice")
    assert await _legacy(client, alice_headers) == []
    result = await _adopt(client, alice_headers, [source["id"]])
    assert result["adopted"] == []
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id is None


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
    must not take it; Bob proving his, and confirming, does."""
    team, project_id = await _team_and_project(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    source = await _legacy_source(client, alice_headers, project_id, who="bob")
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref

    await _connect_on_home(client, alice_headers, who="alice")
    (legacy,) = await _legacy(client, alice_headers)
    assert legacy["claimable_connection_id"] is None  # her account is not this account
    result = await _adopt(client, alice_headers, [source["id"]])
    assert result["adopted"] == [] and result["skipped"][0]["reason"] == "not_claimable"
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref == old_ref and connection_id is None
    assert await app.state.secret_store.get(old_ref) == "tok:bob"

    bob_home = await _connect_on_home(client, bob_headers, who="bob")
    # Bob is not the creator, so it is not on Bob's Home list — but naming it with
    # proof of the account and a live membership is the legitimate move.
    result = await _adopt(client, bob_headers, [source["id"]])
    assert [a["connection_id"] for a in result["adopted"]] == [bob_home["id"]]
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id == bob_home["id"]
    assert await _legacy(client, alice_headers) == []


async def test_a_user_who_was_never_a_member_cannot_list_or_claim(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Security review M-NEW-3: the membership join keys on the source's OWN
    team — an owner of some other team is a stranger here."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id, who="bob")
    await me(client, bob_headers)
    await create_team(client, bob_headers)  # Bob owns a team of his own
    bob_home = await _connect_on_home(client, bob_headers, who="bob")
    assert bob_home["status"] == "connected"
    assert await _legacy(client, bob_headers) == []
    result = await _adopt(client, bob_headers, [source["id"]])
    assert result["adopted"] == [] and result["skipped"][0]["reason"] == "not_claimable"
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None


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
    result = await _adopt(client, bob_headers, [source["id"]])
    assert result["adopted"] == []
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
    assert (await _adopt(client, bob_headers, [source["id"]]))["adopted"] == []
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
    assert (await _adopt(client, alice_headers, [source["id"]]))["adopted"] == []
    db.expire_all()
    gone = (await db.execute(select(Source.id).where(Source.id == source["id"]))).first()
    assert gone is None


async def test_a_recorded_access_mismatch_is_refused_never_widened(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Security review H1: a read-only project must not become read-and-edit
    because the account grant is wider, nor lose a write token to a narrower
    grant — even when the user confirms."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await db.execute(
        update(Source).where(Source.id == source["id"]).values(config={"access": "read"})
    )
    await db.commit()
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    await _connect_on_home(client, alice_headers, who="alice", access="write")
    result = await _adopt(client, alice_headers, [source["id"]], confirm_access=True)
    assert result["adopted"] == []
    assert [x["reason"] for x in result["skipped"]] == ["access_mismatch"]
    ref, connection_id, config = await _source_row(db, source["id"])
    assert ref == old_ref and connection_id is None and config["access"] == "read"
    assert await app.state.secret_store.get(old_ref) == "tok:alice"
    modes = {m["id"]: tuple(m["scopes"]) for m in (OnshapeConnector.access_modes or {})["modes"]}
    assert modes == {"read": ("OAuth2Read",), "write": ("OAuth2Read", "OAuth2Write")}
    assert OnshapeConnector.scopes == ("OAuth2Read",)


async def test_an_unrecorded_access_needs_explicit_acceptance_of_a_write_grant(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Security review H-NEW-2: a source that never recorded its grant must not
    ride a write grant unless the user accepted exactly that."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    await _connect_on_home(client, alice_headers, who="alice", access="write")
    refused = await _adopt(client, alice_headers, [source["id"]])
    assert refused["adopted"] == [] and refused["skipped"][0]["reason"] == "access_unknown"
    assert await app.state.secret_store.get(old_ref) == "tok:alice"
    accepted = await _adopt(client, alice_headers, [source["id"]], confirm_access=True)
    assert len(accepted["adopted"]) == 1
    _, connection_id, config = await _source_row(db, source["id"])
    assert connection_id is not None and config["access"] == "write"


async def test_a_read_grant_needs_no_extra_acceptance_for_an_unrecorded_source(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await _connect_on_home(client, alice_headers, who="alice", access="read")
    assert len((await _adopt(client, alice_headers, [source["id"]]))["adopted"]) == 1
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
    result = await _adopt(
        client, alice_headers, [kicad.json()["data"]["id"], bound.json()["data"]["id"]]
    )
    assert result["adopted"] == [] and {x["reason"] for x in result["skipped"]} == {"not_claimable"}


# ----------------------------------------------------------- robustness


async def test_concurrent_moves_claim_once_and_never_500(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    home = await _connect_on_home(client, alice_headers, who="alice")
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    body = {"source_ids": [source["id"]], "confirm_access": False}
    responses = await asyncio.gather(
        *(
            client.post("/api/v1/users/me/connections/adopt", json=body, headers=alice_headers)
            for _ in range(3)
        )
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    claimed = [a for r in responses for a in r.json()["data"]["adopted"]]
    assert {a["source_id"] for a in claimed} == {source["id"]}
    assert len(claimed) == 1
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id == home["id"]


async def test_a_failed_retirement_is_retried_not_leaked_and_survives_a_revoke(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review M2 / M-NEW-1: the marker (not a ref) stays on the source
    until the derived family is deleted — even after the grant is revoked."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    store = app.state.secret_store
    real_delete = store.delete

    async def failing_delete(ref: str) -> None:
        raise RuntimeError("store outage")

    monkeypatch.setattr(store, "delete", failing_delete)
    home = await _connect_on_home(client, alice_headers, who="alice")
    result = await _adopt(client, alice_headers, [source["id"]])
    assert len(result["adopted"]) == 1  # the claim committed; the sweep is deferred, no 500
    _, connection_id, config = await _source_row(db, source["id"])
    assert connection_id is not None and config.get("_legacy_secrets_retire") is True
    assert await store.get(old_ref) == "tok:alice"
    # The marker is never echoed to project members.
    listing = await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    assert "_legacy_secrets_retire" not in listing.text and "retired" not in listing.text

    # The store recovers; the grant is revoked (which does not touch the marker,
    # so the family is still owed); any later call sweeps it.
    monkeypatch.setattr(store, "delete", real_delete)
    revoked = await client.delete(
        f"/api/v1/users/me/connections/{home['id']}", headers=alice_headers
    )
    assert revoked.status_code == 200, revoked.text
    _, _, config = await _source_row(db, source["id"])
    assert config.get("_legacy_secrets_retire") is True
    await _adopt(client, alice_headers, [source["id"]])  # any later call sweeps
    _, _, config = await _source_row(db, source["id"])
    assert "_legacy_secrets_retire" not in config
    with pytest.raises(SecretNotFoundError):
        await store.get(old_ref)


async def test_a_member_cannot_aim_the_sweep_at_another_secret(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str], app: FastAPI
) -> None:
    """Security review C-NEW-1: nothing a member writes into a source's config
    can name a ref for the sweep — the family is derived from the source id."""
    bob_home = await _connect_on_home(client, bob_headers, who="bob")
    victim_ref = connection_secret_ref(bob_home["id"], "onshape")
    store = app.state.secret_store
    await store.put("stripe_api_key", "sk_live_platform")
    _, project_id = await _team_and_project(client, alice_headers)
    home = await _connect_on_home(client, alice_headers, who="alice")
    mine = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": home["id"]},
        headers=alice_headers,
    )
    assert mine.status_code == 201, mine.text
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/sources/{mine.json()['data']['id']}",
        json={
            "config": {
                "retired_secret_refs": [victim_ref, "stripe_api_key"],
                "_legacy_secrets_retire": True,
            }
        },
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    assert "retired_secret_refs" in patched.json()["data"]["config"]  # inert data, echoed as such
    assert "_legacy_secrets_retire" not in patched.json()["data"]["config"]  # never stored
    legacy = await _legacy_source(client, alice_headers, project_id)
    await _adopt(client, alice_headers, [legacy["id"]])  # runs the sweep
    assert await store.get(victim_ref)  # Bob's grant survives
    assert await store.get("stripe_api_key") == "sk_live_platform"


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
    (legacy,) = await _legacy(client, alice_headers)
    assert legacy["claimable_connection_id"] is None
    assert (await _adopt(client, alice_headers, [source["id"]]))["adopted"] == []
    _, connection_id, _ = await _source_row(db, source["id"])
    assert connection_id is None
    (row,) = await _connections(client, alice_headers)
    assert row["needs_reauth"] == "token_error"


async def test_a_revoke_racing_the_move_leaves_the_project_on_its_own_token(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Security review M-NEW-2: the grant is re-read under lock inside the claim."""
    from solus_api.models import User
    from solus_api.services.connections import claim_legacy_sources

    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    home = await _connect_on_home(client, alice_headers, who="alice")
    db.expire_all()
    stale = await db.get(AccountConnection, home["id"])  # the snapshot a request would hold
    user = await db.get(User, stale.user_id)
    revoked = await client.delete(
        f"/api/v1/users/me/connections/{home['id']}", headers=alice_headers
    )
    assert revoked.status_code == 200, revoked.text
    claimed, skipped = await claim_legacy_sources(
        db, app.state.connector_registry, user, stale, {uuid_of(source["id"])}
    )
    assert claimed == [] and skipped == []
    await db.rollback()
    ref, connection_id, _ = await _source_row(db, source["id"])
    assert ref and ref.startswith("source/") and connection_id is None


def uuid_of(value: str) -> Any:
    import uuid

    return uuid.UUID(value)


async def test_adopt_requires_a_verified_signed_in_user_and_named_sources(
    client: AsyncClient,
) -> None:
    body = {"source_ids": ["01a00000-0000-7000-8000-000000000001"]}
    assert (await client.post("/api/v1/users/me/connections/adopt", json=body)).status_code == 401
    unverified = bearer("unverified-sub-h2", "unverified-h2@example.com", email_verified=False)
    await me(client, unverified)
    resp = await client.post("/api/v1/users/me/connections/adopt", json=body, headers=unverified)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"
    assert (await client.get("/api/v1/users/me/connections/legacy")).status_code == 401
    verified = bearer("verified-sub-h2", "verified-h2@example.com", email_verified=True)
    await me(client, verified)
    for bad in (
        {},
        {"source_ids": []},
        {"source_ids": ["x"]},
        {"source_ids": [body["source_ids"][0]], "extra": 1},
    ):
        resp = await client.post("/api/v1/users/me/connections/adopt", json=bad, headers=verified)
        assert resp.status_code == 422, (bad, resp.text)


async def test_every_named_source_is_accounted_for_even_when_the_grant_dies_mid_request(
    client: AsyncClient, alice_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code review: a revoke racing the locked claim must not make a named id
    vanish from the response — the caller can still see it did not move."""
    import solus_api.routers.connections as route

    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await _connect_on_home(client, alice_headers, who="alice")

    async def grant_died(*_args: Any, **_kwargs: Any) -> tuple[list[Source], list[dict[str, Any]]]:
        return [], []

    monkeypatch.setattr(route, "claim_legacy_sources", grant_died)
    result = await _adopt(client, alice_headers, [source["id"]])
    assert result["adopted"] == []
    assert [(x["source_id"], x["reason"]) for x in result["skipped"]] == [
        (source["id"], "not_claimable")
    ]


async def test_the_retire_marker_is_stripped_on_create_too(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _team_and_project(client, alice_headers)
    home = await _connect_on_home(client, alice_headers, who="alice")
    created = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={
            "type": "onshape",
            "name": "cad",
            "connection_id": home["id"],
            "config": {"_legacy_secrets_retire": True, "documents": []},
        },
        headers=alice_headers,
    )
    assert created.status_code == 201, created.text
    assert "_legacy_secrets_retire" not in created.text


async def test_reusing_a_legacy_source_through_the_wizard_retires_its_own_token(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Security review MEDIUM-1: the Sources-page reuse path re-points a legacy
    row at the account grant; its own token family must not stay live."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    old_ref, _, _ = await _source_row(db, source["id"])
    assert old_ref
    home = await _connect_on_home(client, alice_headers, who="alice")
    reused = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": home["id"]},
        headers=alice_headers,
    )
    assert reused.status_code == 201, reused.text
    assert reused.json()["data"]["id"] == source["id"]
    ref, connection_id, config = await _source_row(db, source["id"])
    assert connection_id == home["id"] and ref == connection_secret_ref(home["id"], "onshape")
    assert "_legacy_secrets_retire" not in config  # swept after the commit
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(old_ref)


async def test_an_owed_family_is_deleted_when_the_source_or_project_is_torn_down(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review MEDIUM-2: a deferred retirement must not be lost with the row."""
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    a = await _legacy_source(client, alice_headers, rover)
    b = await _legacy_source(client, alice_headers, arm)
    ref_a, _, _ = await _source_row(db, a["id"])
    ref_b, _, _ = await _source_row(db, b["id"])
    assert ref_a and ref_b
    store = app.state.secret_store
    real_delete = store.delete

    async def failing_delete(ref: str) -> None:
        raise RuntimeError("store outage")

    monkeypatch.setattr(store, "delete", failing_delete)
    await _connect_on_home(client, alice_headers, who="alice")
    result = await _adopt(client, alice_headers, [a["id"], b["id"]])
    assert len(result["adopted"]) == 2
    monkeypatch.setattr(store, "delete", real_delete)
    # Teardown paths, not a sweep: disconnect one, delete the other's project.
    gone = await client.request(
        "DELETE",
        f"/api/v1/projects/{rover}/sources/{a['id']}",
        json={"retain_entities": False},
        headers=alice_headers,
    )
    assert gone.status_code in (200, 204), gone.text
    deleted = await client.delete(f"/api/v1/projects/{arm}?confirm=true", headers=alice_headers)
    assert deleted.status_code in (200, 204), deleted.text
    for ref in (ref_a, ref_b):
        with pytest.raises(SecretNotFoundError):
            await store.get(ref)


async def test_the_sweep_is_bounded_and_the_remainder_is_the_next_calls_work(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review MEDIUM-3."""
    import solus_api.services.connections as svc

    monkeypatch.setattr(svc, "SWEEP_BATCH", 1)
    await me(client, alice_headers)
    team = (await create_team(client, alice_headers))["id"]
    rover = (await create_project(client, alice_headers, team, name="Rover"))["id"]
    arm = (await create_project(client, alice_headers, team, name="Arm"))["id"]
    a = await _legacy_source(client, alice_headers, rover)
    b = await _legacy_source(client, alice_headers, arm)
    store = app.state.secret_store
    real_delete = store.delete

    async def failing_delete(ref: str) -> None:
        raise RuntimeError("store outage")

    monkeypatch.setattr(store, "delete", failing_delete)
    await _connect_on_home(client, alice_headers, who="alice")
    await _adopt(client, alice_headers, [a["id"], b["id"]])
    monkeypatch.setattr(store, "delete", real_delete)
    await _adopt(client, alice_headers, [a["id"]])  # one sweep of one
    _, _, ca = await _source_row(db, a["id"])
    _, _, cb = await _source_row(db, b["id"])
    assert [ca.get("_legacy_secrets_retire"), cb.get("_legacy_secrets_retire")].count(True) == 1
    await _adopt(client, alice_headers, [a["id"]])  # the remainder
    _, _, ca = await _source_row(db, a["id"])
    _, _, cb = await _source_row(db, b["id"])
    assert "_legacy_secrets_retire" not in ca and "_legacy_secrets_retire" not in cb


async def test_a_move_drops_the_hosted_add_on_state_that_rode_the_old_token(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Security review LOW-1: the agent must not advertise tools that no longer authenticate."""
    _, project_id = await _team_and_project(client, alice_headers)
    source = await _legacy_source(client, alice_headers, project_id)
    await db.execute(
        update(Source)
        .where(Source.id == source["id"])
        .values(
            config={
                "hosted": {"featurescript": {"state": "ready"}},
                "_hosted": {"featurescript": ["x"]},
            }
        )
    )
    await db.commit()
    await _connect_on_home(client, alice_headers, who="alice")
    await _adopt(client, alice_headers, [source["id"]])
    _, _, config = await _source_row(db, source["id"])
    assert "hosted" not in config and "_hosted" not in config
