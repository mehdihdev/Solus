"""The Onshape panel: pairing, and the guarantees around it — SOLUS-A7-01.

The property everything here defends: **an Onshape-supplied identifier must
never reach account provisioning, and must never authenticate anything.**

`deps.py:_provision_user` creates a User, a Team, an OWNER Membership, a
Subscription and a real credit balance on first sight of any valid Supabase
JWT. Onshape hands the panel a `{$userId}` query param — unsigned, from a third
party, and visible to anyone sharing a document. If a match on that string
granted the panel, a collaborator could read someone's whole Solus graph.

So the panel holds a SECRET, obtained through a pairing the user approved while
authenticated in Solus. `{$userId}` is at most a client-side hint about which
stored token to send; the server never accepts it as an authentication input.

The last three tests are the structural ones. Behavioural tests prove today's
routes are safe; those prove that a route added next year cannot quietly become
unsafe.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

import jwt
import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import (
    Domain,
    GraphEntity,
    PanelBinding,
    PanelPairing,
    Source,
    SourceStatus,
    SourceType,
    User,
    utcnow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

PANEL = "/api/v1/panel"


async def _pair(client: AsyncClient, onshape_user_id: str | None = None) -> dict[str, Any]:
    resp = await client.post(f"{PANEL}/pair/start", json={"onshape_user_id": onshape_user_id})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _approve(client: AsyncClient, headers: dict[str, str], user_code: str) -> None:
    resp = await client.post(
        "/api/v1/users/me/panel-links", json={"user_code": user_code}, headers=headers
    )
    assert resp.status_code in (200, 204), resp.text


async def _linked_token(
    client: AsyncClient, headers: dict[str, str], oid: str | None = None
) -> str:
    started = await _pair(client, oid)
    await _approve(client, headers, started["user_code"])
    resp = await client.post(
        f"{PANEL}/pair/poll", headers={"Authorization": f"Bearer {started['device_code']}"}
    )
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["data"]["token"]
    return token


def _panel_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- the handshake


async def test_starting_a_pairing_grants_nothing(client: AsyncClient, db: AsyncSession) -> None:
    before = await db.scalar(select(func.count()).select_from(User))

    started = await _pair(client)

    assert started["user_code"]
    assert len(started["device_code"]) > 32
    assert await db.scalar(select(func.count()).select_from(User)) == before
    assert await db.scalar(select(func.count()).select_from(PanelBinding)) == 0


async def test_polling_before_approval_returns_pending(client: AsyncClient) -> None:
    started = await _pair(client)

    resp = await client.post(
        f"{PANEL}/pair/poll", headers={"Authorization": f"Bearer {started['device_code']}"}
    )

    assert resp.json()["data"]["status"] == "pending"


async def test_approval_then_poll_yields_a_token_once(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Single use: the pairing row is deleted at redemption, so a replayed
    device code cannot mint a second credential."""
    await me(client, alice_headers)
    started = await _pair(client)
    await _approve(client, alice_headers, started["user_code"])
    auth = {"Authorization": f"Bearer {started['device_code']}"}

    first = await client.post(f"{PANEL}/pair/poll", headers=auth)
    second = await client.post(f"{PANEL}/pair/poll", headers=auth)

    assert first.json()["data"]["status"] == "linked"
    assert first.json()["data"]["token"]
    assert second.status_code == 404


async def test_the_panel_token_is_hashed_at_rest(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """A 90-day silent full-user credential must not be readable from a dump."""
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers)

    binding = (await db.scalars(select(PanelBinding))).one()

    assert binding.token_hash != token
    assert binding.token_hash == hashlib.sha256(token.encode()).hexdigest()


async def test_an_unknown_device_code_is_indistinguishable_from_an_expired_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """No oracle: both 404 with the same code."""
    started = await _pair(client)
    pairing = await db.get(
        PanelPairing, hashlib.sha256(started["device_code"].encode()).hexdigest()
    )
    assert pairing is not None
    pairing.expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()

    expired = await client.post(
        f"{PANEL}/pair/poll", headers={"Authorization": "Bearer " + started["device_code"]}
    )
    unknown = await client.post(f"{PANEL}/pair/poll", headers={"Authorization": "Bearer nope"})

    assert expired.status_code == unknown.status_code == 404
    assert expired.json()["error"]["code"] == unknown.json()["error"]["code"]


async def test_poll_attempts_are_bounded_on_the_row(client: AsyncClient, db: AsyncSession) -> None:
    """Durable on the row, because the in-process rate limiter cannot see the
    client IP behind the ALB and so shares one bucket across all callers."""
    from solus_api.routers.panel import MAX_POLLS

    started = await _pair(client)
    digest = hashlib.sha256(started["device_code"].encode()).hexdigest()
    pairing = await db.get(PanelPairing, digest)
    assert pairing is not None
    pairing.poll_count = MAX_POLLS
    await db.commit()

    resp = await client.post(
        f"{PANEL}/pair/poll", headers={"Authorization": "Bearer " + started["device_code"]}
    )

    assert resp.status_code == 404
    # A count, not `db.get` — this session already has the row in its identity
    # map, so `get` would answer from memory and never see the delete.
    remaining = await db.scalar(
        select(func.count())
        .select_from(PanelPairing)
        .where(PanelPairing.device_code_hash == digest)
    )
    assert remaining == 0


async def test_an_onshape_id_hint_that_is_not_an_id_is_refused(client: AsyncClient) -> None:
    """It reaches a human's approval screen, so it passes the connector's own
    charset first — an unauthenticated third party must not put markup there."""
    resp = await client.post(
        f"{PANEL}/pair/start", json={"onshape_user_id": "<img src=x onerror=alert(1)>"}
    )

    assert resp.status_code == 422


# ------------------------------------------------ {$userId} is not a credential


async def test_an_onshape_user_id_matching_a_real_binding_is_still_unauthenticated(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """THE test for this decision.

    A real binding exists carrying this Onshape user id. Presenting that id
    without the panel token must still be unauthenticated — otherwise anyone who
    shares an Onshape document could read the owner's Solus graph."""
    await me(client, alice_headers)
    await _linked_token(client, alice_headers, oid="abc123")

    resp = await client.get(f"{PANEL}/context?document_id=docA&userId=abc123")

    assert resp.status_code == 401


async def test_an_unpaired_id_can_neither_provision_nor_read(
    client: AsyncClient, db: AsyncSession
) -> None:
    before = await db.scalar(select(func.count()).select_from(User))

    resp = await client.get(f"{PANEL}/context?document_id=docA&userId=whoever")

    assert resp.status_code == 401
    assert await db.scalar(select(func.count()).select_from(User)) == before


async def test_a_supabase_jwt_is_not_a_panel_token(
    client: AsyncClient, db: AsyncSession, settings: Any
) -> None:
    """The two credential namespaces are disjoint. This is the exact credential
    that WOULD provision on any normal route — here it must 401 and create
    nothing."""
    before = await db.scalar(select(func.count()).select_from(User))
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "ghost@example.dev",
            "aud": settings.supabase_jwt_audience,
            "exp": int((utcnow() + timedelta(hours=1)).timestamp()),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    resp = await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))

    assert resp.status_code == 401
    assert await db.scalar(select(func.count()).select_from(User)) == before


async def test_a_forged_panel_token_is_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get(
        f"{PANEL}/context?document_id=docA", headers=_panel_headers("not-a-real-token")
    )

    assert resp.status_code == 401


# ------------------------------------------------------------- revocation


async def test_revocation_takes_effect_on_the_next_request(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers)
    assert (
        await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))
    ).status_code == 200

    binding = (await db.scalars(select(PanelBinding))).one()
    binding.revoked_at = utcnow()
    await db.commit()

    after = await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))

    assert after.status_code == 401


async def test_an_expired_binding_is_unauthenticated(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers)
    binding = (await db.scalars(select(PanelBinding))).one()
    binding.expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()

    resp = await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))

    assert resp.status_code == 401


# --------------------------------------------------------------- context


async def _seed_onshape_source(
    db: AsyncSession, project_id: uuid.UUID, team_id: uuid.UUID, documents: list[str]
) -> None:
    db.add(
        Source(
            project_id=project_id,
            team_id=team_id,
            type=SourceType.ONSHAPE,
            name="Onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": documents},
        )
    )
    await db.commit()


async def test_context_lists_only_projects_tracking_that_document(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    tracked = await create_project(client, alice_headers, team["id"])
    other = await create_project(client, alice_headers, team["id"])
    await _seed_onshape_source(db, uuid.UUID(tracked["id"]), uuid.UUID(team["id"]), ["docA"])
    await _seed_onshape_source(db, uuid.UUID(other["id"]), uuid.UUID(team["id"]), ["docZ"])
    token = await _linked_token(client, alice_headers)

    resp = await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))

    assert [p["id"] for p in resp.json()["data"]["projects"]] == [tracked["id"]]


async def test_another_tenants_document_yields_an_empty_list_not_a_403(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Cross-tenant isolation, and no existence oracle: bob learns nothing about
    whether alice's document exists."""
    await me(client, alice_headers)
    await me(client, bob_headers)
    alice_team = await create_team(client, alice_headers)
    alice_project = await create_project(client, alice_headers, alice_team["id"])
    await _seed_onshape_source(
        db, uuid.UUID(alice_project["id"]), uuid.UUID(alice_team["id"]), ["secretdoc"]
    )
    bob_token = await _linked_token(client, bob_headers)

    resp = await client.get(
        f"{PANEL}/context?document_id=secretdoc", headers=_panel_headers(bob_token)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["projects"] == []


async def test_parts_404_for_a_project_the_binding_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """The project id the panel names carries no authority."""
    await me(client, alice_headers)
    await me(client, bob_headers)
    alice_team = await create_team(client, alice_headers)
    alice_project = await create_project(client, alice_headers, alice_team["id"])
    db.add(
        GraphEntity(
            project_id=uuid.UUID(alice_project["id"]),
            kind="part",
            domain=Domain.MECHANICAL,
            name="Secret Bracket",
            external_ref="docA:elem1:Rover/Bracket",
            origin="connector",
        )
    )
    await db.commit()
    bob_token = await _linked_token(client, bob_headers)

    resp = await client.get(
        f"{PANEL}/projects/{alice_project['id']}/parts?document_id=docA&element_id=elem1",
        headers=_panel_headers(bob_token),
    )

    assert resp.status_code == 404


async def test_parts_returns_the_documents_entities_for_a_permitted_project(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    for ref in ("docA:elem1:Rover/Bracket", "docA:elem2:Other/Thing"):
        db.add(
            GraphEntity(
                project_id=uuid.UUID(project["id"]),
                kind="part",
                domain=Domain.MECHANICAL,
                name=ref.rsplit("/", 1)[-1],
                external_ref=ref,
                origin="connector",
            )
        )
    await db.commit()
    token = await _linked_token(client, alice_headers)

    resp = await client.get(
        f"{PANEL}/projects/{project['id']}/parts?document_id=docA&element_id=elem1",
        headers=_panel_headers(token),
    )

    assert resp.status_code == 200
    assert [e["source_key"] for e in resp.json()["data"]] == ["docA:elem1:Rover/Bracket"]


async def test_a_document_id_must_look_like_an_onshape_id(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers)

    resp = await client.get(
        f"{PANEL}/context?document_id=../../etc/passwd", headers=_panel_headers(token)
    )

    assert resp.status_code == 422


# ---------------------------------------------------- the structural guarantee


def test_no_panel_route_depends_on_provisioning(app: FastAPI) -> None:
    """Behavioural tests prove today's routes are safe; this proves a route
    added next year cannot quietly become unsafe.

    Walks each panel route's dependant tree and asserts it never reaches the
    functions that provision."""
    from fastapi.routing import APIRoute
    from solus_api.deps import _provision_user, get_current_claims, get_current_user

    forbidden = {get_current_user, get_current_claims, _provision_user}

    def calls(dep: Any) -> list[Any]:
        found = [dep.call] if dep.call is not None else []
        for sub in dep.dependencies:
            found.extend(calls(sub))
        return found

    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(("/panel", PANEL)):
            continue
        checked += 1
        reached = set(calls(route.dependant))
        assert not (reached & forbidden), f"{route.path} can reach provisioning"
    assert checked > 0, "no panel routes found — did the prefix change?"


def test_the_panel_router_never_names_current_user() -> None:
    """Backstop for what a dependant-tree walk cannot see: a direct call inside
    a handler body."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "solus_api" / "routers" / "panel.py"
    ).read_text(encoding="utf-8")

    assert "CurrentUser" not in source
    assert "get_current_user" not in source


@pytest.mark.parametrize("bearer", ["", "garbage"])
async def test_hostile_credentials_never_provision_on_any_panel_route(
    client: AsyncClient, db: AsyncSession, app: FastAPI, bearer: str
) -> None:
    """Route-enumerating, so it covers panel routes that do not exist yet."""
    from fastapi.routing import APIRoute

    before = await db.scalar(select(func.count()).select_from(User))
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(PANEL):
            continue
        path = route.path.replace("{project_id}", str(uuid.uuid4()))
        url = f"{path}?document_id=docA&element_id=elem1&userId=anything"
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            resp = await client.request(method, url, headers=headers, json={})
            assert resp.status_code != 500, f"{method} {path} -> {resp.text}"

    assert await db.scalar(select(func.count()).select_from(User)) == before


# ------------------------------------------- approve / list / revoke (users.py)


async def test_approving_the_same_code_twice_is_refused(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Otherwise a second approval would silently re-point a live pairing."""
    await me(client, alice_headers)
    started = await _pair(client)
    await _approve(client, alice_headers, started["user_code"])

    again = await client.post(
        "/api/v1/users/me/panel-links",
        json={"user_code": started["user_code"]},
        headers=alice_headers,
    )

    assert again.status_code == 409


async def test_approving_requires_a_solus_session(client: AsyncClient) -> None:
    """Holding a live session IS the proof of who is approving — the user code
    proves only that someone is looking at the panel."""
    started = await _pair(client)

    resp = await client.post(
        "/api/v1/users/me/panel-links", json={"user_code": started["user_code"]}
    )

    assert resp.status_code == 401


async def test_an_unknown_user_code_is_refused(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)

    resp = await client.post(
        "/api/v1/users/me/panel-links", json={"user_code": "ZZZZ-ZZZZ"}, headers=alice_headers
    )

    assert resp.status_code == 404


async def test_listing_shows_the_link_and_revoking_kills_it(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers, oid="abc123")

    listed = await client.get("/api/v1/users/me/panel-links", headers=alice_headers)
    binding_id = listed.json()["data"][0]["id"]
    revoked = await client.delete(
        f"/api/v1/users/me/panel-links/{binding_id}", headers=alice_headers
    )
    after = await client.get(f"{PANEL}/context?document_id=docA", headers=_panel_headers(token))
    still_listed = await client.get("/api/v1/users/me/panel-links", headers=alice_headers)

    assert listed.json()["data"][0]["onshape_user_id"] == "abc123"
    assert revoked.status_code == 204
    assert after.status_code == 401
    assert still_listed.json()["data"] == []


async def test_one_user_cannot_revoke_anothers_panel_link(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    await me(client, bob_headers)
    token = await _linked_token(client, alice_headers)
    listed = await client.get("/api/v1/users/me/panel-links", headers=alice_headers)
    binding_id = listed.json()["data"][0]["id"]

    resp = await client.delete(f"/api/v1/users/me/panel-links/{binding_id}", headers=bob_headers)
    alice_still_works = await client.get(
        f"{PANEL}/context?document_id=docA", headers=_panel_headers(token)
    )

    assert resp.status_code == 404
    assert alice_still_works.status_code == 200


async def test_approval_rejects_unknown_fields(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """A 90-day credential's entry point: extra="forbid" (CLAUDE.md §7)."""
    await me(client, alice_headers)
    started = await _pair(client)

    resp = await client.post(
        "/api/v1/users/me/panel-links",
        json={"user_code": started["user_code"], "user_id": str(uuid.uuid4())},
        headers=alice_headers,
    )

    assert resp.status_code == 422


# ----------------------------------------------------------------- framing


async def test_the_panel_page_may_be_framed_by_onshape_and_nobody_else(
    client: AsyncClient,
) -> None:
    resp = await client.get("/panel")

    csp = resp.headers["content-security-policy"]
    assert resp.status_code == 200
    assert "frame-ancestors https://*.onshape.com https://onshape.com" in csp
    assert "default-src 'none'" in csp
    # X-Frame-Options has no allowlist form, so setting it could only ever
    # forbid the framing this feature exists to permit.
    assert "x-frame-options" not in {k.lower() for k in resp.headers}


async def test_the_script_is_served_separately_so_the_csp_needs_no_inline_hash(
    client: AsyncClient,
) -> None:
    resp = await client.get("/panel/app.js")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert "script-src 'self'" in resp.headers["content-security-policy"]


async def test_a_json_route_carries_no_framing_headers(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The CSP is per-response on purpose: `frame-ancestors` is a no-op on JSON,
    and a global policy would break the CDN-loaded docs page."""
    resp = await client.get("/api/v1/users/me", headers=alice_headers)

    lowered = {k.lower() for k in resp.headers}
    assert "content-security-policy" not in lowered
    assert "x-frame-options" not in lowered


async def test_an_empty_document_id_is_refused_rather_than_reported_as_no_match(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """It previously fell through as "absent" and matched no tracked selection,
    surfacing to the user as "this document isn't in a project you can see" —
    an answer to a question they never asked."""
    await me(client, alice_headers)
    token = await _linked_token(client, alice_headers)

    resp = await client.get(f"{PANEL}/context?document_id=", headers=_panel_headers(token))

    assert resp.status_code == 422


async def test_the_panel_says_so_when_it_was_not_opened_from_a_document() -> None:
    """The client-side half of the same fix: with no documentId there is nothing
    to look up, so it must not render the no-match message."""
    from solus_api.routers.panel_assets import PANEL_JS

    assert "if (!documentId)" in PANEL_JS
    assert "Open this panel from an Onshape document." in PANEL_JS
