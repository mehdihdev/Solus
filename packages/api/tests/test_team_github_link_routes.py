"""SOLUSDEV-216 S216-T4: GitHub App install start/complete and unlink routes (ADR-039).

GitHub is the respx fake from `fixtures/github_app_fake.py`; users are seeded straight into
the database so each role is exercised through the real auth path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from conftest import bearer
from fixtures.github_app_fake import (
    CLIENT_SECRET,
    FakeGitHubApp,
    app_settings,
    generate_key_pair,
)
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_installation_source,
    seed_team,
    seed_user,
)
from httpx import AsyncClient
from solus_api.connectors.github_app import clear_installation_tokens, installation_secret_ref
from solus_api.core.config import Settings
from solus_api.models import (
    Activity,
    DataEvent,
    Membership,
    OAuthState,
    Role,
    SourceStatus,
    Subscription,
    TeamInstallation,
    TeamKind,
    User,
    utcnow,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

PURPOSE = "github_app_install"
INSTALL_ID = 5150
USER_TOKEN = "ghu_usertoken"


@pytest.fixture
def settings(settings: Settings) -> Settings:  # type: ignore[override]
    return app_settings(settings, generate_key_pair()[0])


@pytest.fixture
async def gh(app: Any) -> AsyncIterator[FakeGitHubApp]:
    clear_installation_tokens()
    with respx.mock(assert_all_called=False) as router:
        fake = FakeGitHubApp(router)
        fake.add_installation(INSTALL_ID, login="acme-robotics")
        fake.user_pages = [[INSTALL_ID]]
        yield fake
    clear_installation_tokens()


class World:
    """A seeded collaborative team with one user per role, plus an outsider."""

    def __init__(self, seeded: SeededTeam, extra: dict[str, User]) -> None:
        self.seeded = seeded
        self.team_id = str(seeded.team.id)
        self.users: dict[str, User] = {
            "owner": seeded.users[Role.OWNER],
            "member": seeded.users[Role.MEMBER],
            **extra,
        }

    def headers(self, who: str, **kwargs: Any) -> dict[str, str]:
        user = self.users[who]
        return bearer(user.supabase_user_id, user.email, **kwargs)

    def url(self, suffix: str) -> str:
        return f"/api/v1/teams/{self.team_id}/github/{suffix}"


async def make_world(db: AsyncSession, *, kind: TeamKind = TeamKind.COLLABORATIVE) -> World:
    seeded = await seed_team(db, kind=kind)
    extra: dict[str, User] = {}
    for name, role in (("admin", Role.ADMIN), ("viewer", Role.VIEWER)):
        user = await seed_user(db, name)
        db.add(Membership(team_id=seeded.team.id, user_id=user.id, role=role))
        extra[name] = user
    extra["outsider"] = await seed_user(db, "outsider")
    await db.commit()
    return World(seeded, extra)


@pytest.fixture
async def world(db: AsyncSession) -> World:
    return await make_world(db)


async def start(client: AsyncClient, world: World, who: str = "admin", **body: Any) -> Any:
    return await client.post(world.url("install/start"), json=body, headers=world.headers(who))


async def started_state(client: AsyncClient, world: World, who: str = "admin") -> str:
    resp = await start(client, world, who)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["state"])


def complete_body(state: str, **overrides: Any) -> dict[str, Any]:
    body = {"state": state, "code": "abc", "installation_id": INSTALL_ID, "setup_action": "install"}
    return {**body, **overrides}


async def complete(
    client: AsyncClient, world: World, body: dict[str, Any], who: str = "admin"
) -> Any:
    return await client.post(world.url("install/complete"), json=body, headers=world.headers(who))


async def installations(db: AsyncSession) -> list[TeamInstallation]:
    result = await db.scalars(select(TeamInstallation).execution_options(populate_existing=True))
    return list(result.all())


# ------------------------------------------------------------------ install/start


async def test_start_returns_install_url_and_single_use_state(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    resp = await start(client, world)

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    parts = urlsplit(data["install_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://github.com/apps/solus-test/installations/new"
    )
    assert parse_qs(parts.query)["state"] == [data["state"]]
    assert data["redirect_uri"].startswith("http://testserver")
    row = await db.get(OAuthState, data["state"])
    assert row is not None
    assert (row.provider, row.user_id, row.team_id) == (
        PURPOSE,
        world.users["admin"].id,
        world.seeded.team.id,
    )
    ttl = row.expires_at - row.created_at
    assert timedelta(minutes=9) < ttl <= timedelta(minutes=10, seconds=5)


async def test_start_accepts_loopback_redirect_uri(client: AsyncClient, world: World) -> None:
    resp = await start(client, world, redirect_uri="http://127.0.0.1:53682/cb")
    assert resp.status_code == 201
    assert resp.json()["data"]["redirect_uri"] == "http://127.0.0.1:53682/cb"


async def test_start_rejects_foreign_redirect_uri(client: AsyncClient, world: World) -> None:
    resp = await start(client, world, redirect_uri="https://evil.example/cb")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_redirect_uri"


@pytest.mark.parametrize(("who", "status"), [("owner", 201), ("admin", 201), ("member", 403)])
async def test_start_role_gate(client: AsyncClient, world: World, who: str, status: int) -> None:
    assert (await start(client, world, who)).status_code == status


async def test_start_viewer_forbidden_and_outsider_gets_404(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    assert (await start(client, world, "viewer")).status_code == 403
    assert (await start(client, world, "outsider")).status_code == 404
    assert (await db.scalars(select(OAuthState))).all() == []


async def test_start_requires_verified_email(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    resp = await client.post(
        world.url("install/start"), json={}, headers=world.headers("admin", email_verified=False)
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_start_requires_authentication(client: AsyncClient, world: World) -> None:
    assert (await client.post(world.url("install/start"), json={})).status_code == 401


async def test_start_personal_team_is_unsupported(client: AsyncClient, db: AsyncSession) -> None:
    personal = await make_world(db, kind=TeamKind.PERSONAL)
    resp = await start(client, personal, "owner")
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "personal_team_unsupported")


async def test_start_unconfigured_app_is_503(
    client: AsyncClient, world: World, app: Any, settings: Settings
) -> None:
    app.state.settings = settings.model_copy(update={"github_app_slug": None})
    resp = await start(client, world)
    assert (resp.status_code, resp.json()["error"]["code"]) == (503, "github_app_unconfigured")


async def test_start_refuses_when_already_linked(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    await seed_installation(db, world.seeded)
    await db.commit()
    resp = await start(client, world)
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "already_linked")


async def test_start_refuses_at_plan_limit(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    sub = await db.scalar(
        select(Subscription).where(Subscription.user_id == world.users["admin"].id)
    )
    assert sub is not None
    sub.limits = {**sub.limits, "max_integrations": 0}
    await db.commit()

    resp = await start(client, world)

    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "plan_limit_reached")
    assert (await db.scalars(select(OAuthState))).all() == []


async def test_start_rejects_unknown_body_field(client: AsyncClient, world: World) -> None:
    assert (await start(client, world, nope=1)).status_code == 422


# ------------------------------------------------------------------ install/complete


async def test_complete_links_installation(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    state = await started_state(client, world)

    resp = await complete(client, world, complete_body(state))

    assert resp.status_code == 201, resp.text
    inst = resp.json()["data"]["installation"]
    assert (inst["account_login"], inst["account_type"], inst["status"]) == (
        "acme-robotics",
        "Organization",
        "active",
    )
    assert inst["linked_by"]["user_id"] == str(world.users["admin"].id)
    (row,) = await installations(db)
    assert row.team_id == world.seeded.team.id
    assert row.external_installation_id == INSTALL_ID
    assert row.linked_by == world.users["admin"].id
    assert (row.api_base_url, row.web_base_url) == ("https://api.github.com", "https://github.com")
    acts = (await db.scalars(select(Activity).where(Activity.type == "github_org.linked"))).all()
    assert len(acts) == 1 and acts[0].team_id == world.seeded.team.id
    assert await db.get(OAuthState, state) is None  # consumed
    assert len(gh.revoke_requests) == 1  # user token dropped at GitHub


async def test_complete_emits_data_event_for_consenting_user(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    world.users["admin"].data_collection_consent = True
    await db.commit()
    state = await started_state(client, world)

    assert (await complete(client, world, complete_body(state))).status_code == 201

    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "github_org.linked"))
    ).all()
    assert len(events) == 1


async def test_complete_ignores_client_supplied_base_urls(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    state = await started_state(client, world)
    resp = await complete(client, world, complete_body(state, api_base_url="https://evil.test"))
    assert resp.status_code == 422
    assert await installations(db) == []


async def test_complete_same_team_again_is_idempotent_200(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    first = await started_state(client, world)
    assert (await complete(client, world, complete_body(first))).status_code == 201
    gh.add_installation(INSTALL_ID, login="acme-renamed")
    # A relink needs a fresh state, which start refuses while linked: seed one directly.
    db.add(
        OAuthState(
            state="relink-state",
            provider=PURPOSE,
            user_id=world.users["admin"].id,
            team_id=world.seeded.team.id,
            redirect_uri="http://127.0.0.1:1/cb",
            expires_at=utcnow() + timedelta(minutes=5),
        )
    )
    await db.commit()

    resp = await complete(client, world, complete_body("relink-state"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["installation"]["account_login"] == "acme-renamed"
    assert len(await installations(db)) == 1


@pytest.mark.parametrize("case", ["expired", "reused", "other_user", "other_team", "wrong_purpose"])
async def test_complete_rejects_bad_state_and_binds_nothing(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp, case: str
) -> None:
    other = await make_world(db)
    state = await started_state(client, world)
    who = "admin"
    if case == "expired":
        row = await db.get(OAuthState, state)
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    elif case == "reused":
        assert (await complete(client, world, complete_body(state))).status_code == 201
        for inst in await installations(db):
            await db.delete(inst)
        await db.commit()
    elif case == "other_user":
        who = "owner"
    elif case == "other_team":
        state = await started_state(client, other)
    elif case == "wrong_purpose":
        row = await db.get(OAuthState, state)
        assert row is not None
        row.provider = "github"
        await db.commit()

    before = len(await installations(db))
    resp = await complete(client, world, complete_body(state), who)

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "install_state_invalid"
    assert len(await installations(db)) == before
    assert gh.code_requests == [] or case == "reused"


async def test_complete_wrong_user_does_not_burn_victims_state(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    state = await started_state(client, world)
    assert (await complete(client, world, complete_body(state), "owner")).status_code == 404
    # The owner could not consume the admin's state; the admin still can.
    assert (await complete(client, world, complete_body(state))).status_code == 201


async def test_complete_forged_installation_id_is_403_and_user_token_revoked(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.add_installation(9999)
    state = await started_state(client, world)

    resp = await complete(client, world, complete_body(state, installation_id=9999))

    assert (resp.status_code, resp.json()["error"]["code"]) == (403, "installation_not_accessible")
    assert await installations(db) == []
    assert len(gh.revoke_requests) == 1
    assert await db.get(OAuthState, state) is None  # state burned even on failure
    replay = await complete(client, world, complete_body(state))
    assert replay.status_code == 404


async def test_complete_failed_code_exchange_is_400_and_consumes_state(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.code_response = {"error": "bad_verification_code"}
    state = await started_state(client, world)

    resp = await complete(client, world, complete_body(state))

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "oauth_exchange_failed"
    assert await installations(db) == []
    assert await db.get(OAuthState, state) is None


async def _assert_admin_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp, state: str
) -> None:
    resp = await complete(client, world, complete_body(state))
    assert (resp.status_code, resp.json()["error"]["code"]) == (403, "installation_admin_required")
    assert await installations(db) == []
    assert len(gh.revoke_requests) == 1  # the user token is still revoked


async def test_complete_org_member_who_is_not_admin_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.membership_body = {"state": "active", "role": "member"}
    await _assert_admin_refused(client, world, db, gh, await started_state(client, world))


async def test_complete_pending_org_admin_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.membership_body = {"state": "pending", "role": "admin"}
    await _assert_admin_refused(client, world, db, gh, await started_state(client, world))


@pytest.mark.parametrize("status", [403, 404])
async def test_complete_non_member_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp, status: int
) -> None:
    gh.membership_status = status
    await _assert_admin_refused(client, world, db, gh, await started_state(client, world))


@pytest.mark.parametrize("body", [[], "admin", {"role": "admin"}, {"state": "active"}])
async def test_complete_malformed_membership_body_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp, body: Any
) -> None:
    gh.membership_body = body
    resp = await complete(client, world, complete_body(await started_state(client, world)))
    assert resp.status_code in (403, 502)
    assert await installations(db) == []
    assert len(gh.revoke_requests) == 1


async def test_complete_active_org_admin_links(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    resp = await complete(client, world, complete_body(await started_state(client, world)))
    assert resp.status_code == 201, resp.text
    assert gh.membership_requests[0].url.path == "/user/memberships/orgs/acme-robotics"
    assert len(await installations(db)) == 1


async def test_complete_user_installation_checks_the_user_id(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.add_installation(INSTALL_ID, login="solo", account_id=555, account_type="User")
    gh.user_body = {"id": 555}
    ok = await complete(client, world, complete_body(await started_state(client, world)))
    assert ok.status_code == 201, ok.text
    assert gh.membership_requests == []


async def test_complete_user_installation_with_other_user_id_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.add_installation(INSTALL_ID, login="solo", account_id=555, account_type="User")
    gh.user_body = {"id": 556}
    await _assert_admin_refused(client, world, db, gh, await started_state(client, world))


async def test_complete_unknown_account_type_is_refused(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.add_installation(INSTALL_ID, account_type="Bot")
    await _assert_admin_refused(client, world, db, gh, await started_state(client, world))


@pytest.mark.parametrize("which", ["membership", "user"])
async def test_complete_network_error_on_admin_proof_is_502_and_binds_nothing(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp, which: str
) -> None:
    if which == "membership":
        gh.membership_network_error = True
    else:
        gh.add_installation(INSTALL_ID, account_id=555, account_type="User")
        gh.user_network_error = True
    resp = await complete(client, world, complete_body(await started_state(client, world)))
    assert (resp.status_code, resp.json()["error"]["code"]) == (502, "github_unreachable")
    assert await installations(db) == []
    assert len(gh.revoke_requests) == 1


async def test_complete_upstream_error_on_admin_proof_is_502(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.membership_status = 500
    resp = await complete(client, world, complete_body(await started_state(client, world)))
    assert (resp.status_code, resp.json()["error"]["code"]) == (502, "github_error")
    assert await installations(db) == []


async def test_complete_update_path_requires_admin_and_keeps_binding(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    first = await started_state(client, world)
    assert (await complete(client, world, complete_body(first))).status_code == 201
    gh.add_installation(INSTALL_ID, login="acme-renamed")
    gh.membership_body = {"state": "active", "role": "member"}
    db.add(
        OAuthState(
            state="update-state",
            provider=PURPOSE,
            user_id=world.users["admin"].id,
            team_id=world.seeded.team.id,
            redirect_uri="http://127.0.0.1:1/cb",
            expires_at=utcnow() + timedelta(minutes=5),
        )
    )
    await db.commit()

    resp = await complete(client, world, complete_body("update-state", setup_action="update"))

    assert (resp.status_code, resp.json()["error"]["code"]) == (403, "installation_admin_required")
    rows = await installations(db)
    assert [r.account_login for r in rows] == ["acme-robotics"]


async def test_complete_linked_elsewhere_is_409(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await make_world(db)
    await seed_installation(db, other.seeded, external_id=INSTALL_ID)
    await db.commit()
    state = await started_state(client, world)

    resp = await complete(client, world, complete_body(state))

    assert (resp.status_code, resp.json()["error"]["code"]) == (
        409,
        "installation_linked_elsewhere",
    )
    rows = await installations(db)
    assert [r.team_id for r in rows] == [other.seeded.team.id]


async def test_complete_request_action_binds_nothing_and_answers_202(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    state = await started_state(client, world)

    resp = await complete(client, world, {"state": state, "code": "abc", "setup_action": "request"})

    assert resp.status_code == 202, resp.text
    assert resp.json()["data"] == {"status": "requested"}
    assert await installations(db) == []
    assert await db.get(OAuthState, state) is None
    assert gh.code_requests == []


async def test_complete_install_without_installation_id_is_422(
    client: AsyncClient, world: World
) -> None:
    state = await started_state(client, world)
    body = {"state": state, "code": "abc", "setup_action": "install"}
    assert (await complete(client, world, body)).status_code == 422


async def test_complete_rejects_extra_field_and_bad_action(
    client: AsyncClient, world: World
) -> None:
    state = await started_state(client, world)
    assert (await complete(client, world, complete_body(state, extra=1))).status_code == 422
    assert (
        await complete(client, world, complete_body(state, setup_action="delete"))
    ).status_code == 422


@pytest.mark.parametrize(("who", "status"), [("member", 403), ("viewer", 403), ("outsider", 404)])
async def test_complete_role_gate(
    client: AsyncClient, world: World, gh: FakeGitHubApp, who: str, status: int
) -> None:
    resp = await complete(client, world, complete_body("whatever"), who)
    assert resp.status_code == status


async def test_complete_personal_team_unsupported(client: AsyncClient, db: AsyncSession) -> None:
    personal = await make_world(db, kind=TeamKind.PERSONAL)
    resp = await complete(client, personal, complete_body("x"), "owner")
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "personal_team_unsupported")


async def test_complete_requires_verified_email(client: AsyncClient, world: World) -> None:
    resp = await client.post(
        world.url("install/complete"),
        json=complete_body("x"),
        headers=world.headers("admin", email_verified=False),
    )
    assert resp.status_code == 403


async def test_complete_respects_plan_limit_after_state(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    state = await started_state(client, world)
    sub = await db.scalar(
        select(Subscription).where(Subscription.user_id == world.users["admin"].id)
    )
    assert sub is not None
    sub.limits = {**sub.limits, "max_integrations": 0}
    await db.commit()

    resp = await complete(client, world, complete_body(state))

    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "plan_limit_reached")
    assert await installations(db) == []


async def test_user_token_never_logged_stored_or_returned(
    client: AsyncClient,
    world: World,
    db: AsyncSession,
    gh: FakeGitHubApp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    state = await started_state(client, world)

    resp = await complete(client, world, complete_body(state))

    assert resp.status_code == 201
    assert USER_TOKEN not in resp.text and CLIENT_SECRET not in resp.text
    assert USER_TOKEN not in caplog.text and CLIENT_SECRET not in caplog.text
    rows = (
        await db.execute(
            text(
                "SELECT t::text FROM team_installations t UNION ALL "
                "SELECT o::text FROM oauth_states o UNION ALL "
                "SELECT a::text FROM activities a UNION ALL "
                "SELECT d::text FROM data_events d"
            )
        )
    ).all()
    assert all(USER_TOKEN not in row[0] for row in rows)


async def test_two_teams_racing_for_one_installation_yield_exactly_one_row(
    client: AsyncClient, world: World, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await make_world(db)
    state_a = await started_state(client, world)
    state_b = await started_state(client, other)

    resp_a, resp_b = await asyncio.gather(
        complete(client, world, complete_body(state_a)),
        complete(client, other, complete_body(state_b)),
    )

    assert sorted([resp_a.status_code, resp_b.status_code]) == [201, 409]
    loser = resp_a if resp_a.status_code == 409 else resp_b
    assert loser.json()["error"]["code"] == "installation_linked_elsewhere"
    assert len(await installations(db)) == 1


# ------------------------------------------------------------------ DELETE installation


async def test_delete_unlinks_disconnects_sources_and_refuses_ref(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    inst = await seed_installation(db, world.seeded, login="acme")
    source = await seed_installation_source(db, world.seeded)
    await db.commit()
    ref = installation_secret_ref(inst.id)

    resp = await client.delete(world.url("installation"), headers=world.headers("admin"))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["disabled_sources"] == 1
    assert data["manage_url"].startswith("https://github.com/organizations/acme/settings/")
    await db.refresh(source)
    assert source.status is SourceStatus.DISCONNECTED
    assert source.last_error is not None and source.last_error["code"] == "installation_unlinked"
    from solus_api.connectors.contracts import ConnectorError
    from solus_api.connectors.github_app import resolve_installation_credentials

    with pytest.raises(ConnectorError):
        await resolve_installation_credentials(ref)
    acts = (await db.scalars(select(Activity).where(Activity.type == "github_org.unlinked"))).all()
    assert len(acts) == 1 and acts[0].actor_id == world.users["admin"].id
    get = await client.get(world.url("installation"), headers=world.headers("admin"))
    assert get.json()["data"]["installation"] is None


@pytest.mark.parametrize(("who", "status"), [("member", 403), ("viewer", 403), ("outsider", 404)])
async def test_delete_role_gate_changes_nothing(
    client: AsyncClient, world: World, db: AsyncSession, who: str, status: int
) -> None:
    await seed_installation(db, world.seeded)
    await db.commit()
    resp = await client.delete(world.url("installation"), headers=world.headers(who))
    assert resp.status_code == status
    assert len(await installations(db)) == 1
    assert (await installations(db))[0].deleted_at is None


async def test_delete_without_installation_is_404(client: AsyncClient, world: World) -> None:
    resp = await client.delete(world.url("installation"), headers=world.headers("admin"))
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "installation_missing")


async def test_delete_personal_team_unsupported(client: AsyncClient, db: AsyncSession) -> None:
    personal = await make_world(db, kind=TeamKind.PERSONAL)
    resp = await client.delete(personal.url("installation"), headers=personal.headers("owner"))
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "personal_team_unsupported")


async def test_delete_other_teams_installation_cannot_be_reached(
    client: AsyncClient, world: World, db: AsyncSession
) -> None:
    other = await make_world(db)
    await seed_installation(db, other.seeded)
    await db.commit()
    # `world`'s admin hits the OTHER team's URL: not a member, so 404 and nothing changes.
    resp = await client.delete(other.url("installation"), headers=world.headers("admin"))
    assert resp.status_code == 404
    assert (await installations(db))[0].deleted_at is None
