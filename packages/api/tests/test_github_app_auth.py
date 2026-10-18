"""SOLUSDEV-216 T2 — GitHub App auth core (ADR-039): JWT, minter, client, resolver.

Everything runs against the respx fake in `fixtures/github_app_fake.py` with a key pair
generated at runtime. The headline security claims are measured: the token is never in
any log record at any level, never in any database text column, and never cached
anywhere a second process could read it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
import respx
from fixtures.github_app_fake import (
    API,
    APP_ID,
    CLIENT_ID,
    CLIENT_SECRET,
    WEB,
    FakeGitHubApp,
    app_settings,
    basic_auth_user,
    decode_jwt_unverified,
    generate_key_pair,
)
from solus_api.connectors import github_app
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import (
    GitHubAppClient,
    InstallationInfo,
    app_jwt,
    clear_installation_tokens,
    configure_github_app,
    invalidate_installation_token,
    mint_installation_token,
    resolve_installation_credentials,
)
from solus_api.core.config import Settings
from solus_api.models import Base, InstallationStatus, Team, TeamInstallation, TeamKind
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

INSTALL_ID = 1001
#: The seeded `team_installations` row; refs name OUR row, never GitHub's id.
ROW_ID = uuid.UUID("0190f0e0-0000-7000-8000-000000000001")
REF = f"github-app/installation/{ROW_ID}"
NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


class Clock:
    """A frozen, advanceable clock shared by the module under test and the fake."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def key_pair() -> tuple[str, str]:
    return generate_key_pair()


@pytest.fixture
def configured(settings: Settings, key_pair: tuple[str, str]) -> Settings:
    return app_settings(settings, key_pair[0])


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    frozen = Clock()
    monkeypatch.setattr(github_app, "_utcnow", frozen)
    return frozen


@pytest.fixture
async def gh(
    configured: Settings, settings: Settings, maker: async_sessionmaker[Any], clock: Clock
) -> AsyncIterator[FakeGitHubApp]:
    configure_github_app(configured, maker)
    clear_installation_tokens()
    with respx.mock(assert_all_called=False) as router:
        fake = FakeGitHubApp(router)
        fake.clock = clock
        yield fake
    clear_installation_tokens()
    configure_github_app(settings)


async def seed_installation(
    maker: async_sessionmaker[Any],
    *,
    external_id: int = INSTALL_ID,
    row_id: uuid.UUID = ROW_ID,
    status: InstallationStatus = InstallationStatus.ACTIVE,
    deleted: bool = False,
    team_deleted: bool = False,
    api_base_url: str = API,
) -> TeamInstallation:
    async with maker() as session:
        team = Team(name="Acme", kind=TeamKind.COLLABORATIVE)
        if team_deleted:
            team.deleted_at = NOW
        session.add(team)
        await session.flush()
        row = TeamInstallation(
            id=row_id,
            team_id=team.id,
            external_installation_id=external_id,
            account_login="acme-robotics",
            account_external_id=777,
            account_type="Organization",
            repository_selection="selected",
            status=status,
            api_base_url=api_base_url,
        )
        if deleted:
            row.deleted_at = NOW
        session.add(row)
        await session.commit()
        return row


async def reload(maker: async_sessionmaker[Any], row_id: Any) -> TeamInstallation:
    async with maker() as session:
        row = await session.get(TeamInstallation, row_id)
        assert row is not None
        fresh: TeamInstallation = row
        return fresh


# ------------------------------------------------------------------ the App JWT


def test_app_jwt_claims_verify_with_the_public_key(
    gh: FakeGitHubApp, key_pair: tuple[str, str]
) -> None:
    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
    token = app_jwt(now)
    claims = jwt.decode(
        token, key_pair[1], algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
    )
    assert claims["iss"] == APP_ID
    assert claims["iat"] == int(now.timestamp()) - 60
    assert claims["exp"] == int(now.timestamp()) + 9 * 60
    assert jwt.get_unverified_header(token)["alg"] == "RS256"


def test_app_jwt_defaults_to_the_current_time(gh: FakeGitHubApp, key_pair: tuple[str, str]) -> None:
    claims = jwt.decode(
        app_jwt(),
        key_pair[1],
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["exp"] - claims["iat"] == 10 * 60


def test_app_jwt_unconfigured_raises(settings: Settings) -> None:
    configure_github_app(settings)
    with pytest.raises(ConnectorError) as exc:
        app_jwt()
    assert exc.value.code == "github_app_unconfigured"


def test_app_jwt_wrong_key_does_not_verify(gh: FakeGitHubApp) -> None:
    _, other_public = generate_key_pair()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(app_jwt(), other_public, algorithms=["RS256"])


# ------------------------------------------------------------------ the minter


async def test_second_resolve_is_served_from_cache(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    first = await resolve_installation_credentials(REF)
    second = await resolve_installation_credentials(REF)
    assert first.token == second.token == gh.minted_tokens[0]
    assert gh.mint_calls == [INSTALL_ID]
    assert len(gh.jwts_seen) == 1
    claims = decode_jwt_unverified(gh.jwts_seen[0])
    assert claims["iss"] == APP_ID


@pytest.mark.parametrize(
    ("lifetime", "cached_at_minutes", "expired_at_minutes"),
    [
        # GitHub's 1h: the 55-minute ceiling wins (expires_at - 5m is also 55m).
        (timedelta(hours=1), 54, 56),
        # A 2h token still caches only 55 minutes.
        (timedelta(hours=2), 54, 56),
        # A short token: expires_at - 5m wins.
        (timedelta(minutes=10), 4, 6),
    ],
)
async def test_cache_expiry_follows_the_min_rule(
    gh: FakeGitHubApp,
    maker: async_sessionmaker[Any],
    clock: Clock,
    lifetime: timedelta,
    cached_at_minutes: int,
    expired_at_minutes: int,
) -> None:
    await seed_installation(maker)
    gh.token_lifetime = lifetime
    await mint_installation_token(INSTALL_ID)
    clock.advance(minutes=cached_at_minutes)
    await mint_installation_token(INSTALL_ID)
    assert len(gh.mint_calls) == 1
    clock.advance(minutes=expired_at_minutes - cached_at_minutes)
    await mint_installation_token(INSTALL_ID)
    assert len(gh.mint_calls) == 2


async def test_concurrent_resolves_mint_once(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    gh.mint_delay = 0.05
    results = await asyncio.gather(*(resolve_installation_credentials(REF) for _ in range(10)))
    assert len(gh.mint_calls) == 1
    assert {c.token for c in results} == {gh.minted_tokens[0]}


async def test_invalidate_evicts_the_cached_token(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    await resolve_installation_credentials(REF)
    invalidate_installation_token(INSTALL_ID)
    await resolve_installation_credentials(REF)
    assert len(gh.mint_calls) == 2


async def test_invalidate_of_an_unknown_installation_is_a_noop(gh: FakeGitHubApp) -> None:
    invalidate_installation_token(999)


async def _resolve_unavailable() -> None:
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "installation_unavailable"


async def test_mint_404_marks_the_installation_revoked(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.mint_status[INSTALL_ID] = 404
    await _resolve_unavailable()
    fresh = await reload(maker, row.id)
    assert fresh.status is InstallationStatus.REVOKED
    assert fresh.revoked_at is not None
    assert fresh.deleted_at is not None  # a full revoke, not just a status flip
    # The next resolve fails at the status gate with no further GitHub call.
    await _resolve_unavailable()
    assert len(gh.mint_calls) == 1


async def test_mint_403_with_a_suspended_installation_marks_it_suspended(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.add_installation(INSTALL_ID, suspended_at="2026-10-01T00:00:00Z")
    gh.mint_status[INSTALL_ID] = 403
    await _resolve_unavailable()
    fresh = await reload(maker, row.id)
    assert fresh.status is InstallationStatus.SUSPENDED
    assert fresh.suspended_at is not None and fresh.revoked_at is None


async def test_mint_403_with_a_missing_installation_marks_it_revoked(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.mint_status[INSTALL_ID] = 403  # and GET /app/installations/{id} answers 404
    await _resolve_unavailable()
    fresh = await reload(maker, row.id)
    assert fresh.status is InstallationStatus.REVOKED and fresh.revoked_at is not None
    assert fresh.deleted_at is not None


async def test_mint_403_with_an_unreachable_lookup_leaves_the_status(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.mint_status[INSTALL_ID] = 403
    gh.installation_route.mock(side_effect=httpx.ConnectError("boom"))
    await _resolve_unavailable()
    fresh = await reload(maker, row.id)
    assert fresh.status is InstallationStatus.ACTIVE
    assert fresh.revoked_at is None and fresh.suspended_at is None


async def test_mint_403_with_an_active_installation_leaves_the_status(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.add_installation(INSTALL_ID)  # not suspended
    gh.mint_status[INSTALL_ID] = 403
    await _resolve_unavailable()
    assert (await reload(maker, row.id)).status is InstallationStatus.ACTIVE


async def test_mint_403_evicts_a_cached_token_whatever_the_lookup_says(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any], clock: Clock
) -> None:
    await seed_installation(maker)
    await mint_installation_token(INSTALL_ID)
    clock.advance(minutes=56)
    gh.mint_status[INSTALL_ID] = 403
    gh.installation_route.mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ConnectorError):
        await mint_installation_token(INSTALL_ID)
    gh.mint_status.clear()
    await mint_installation_token(INSTALL_ID)
    assert len(gh.mint_calls) == 3


async def test_mint_refusal_evicts_a_cached_token(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any], clock: Clock
) -> None:
    await seed_installation(maker)
    await mint_installation_token(INSTALL_ID)
    clock.advance(minutes=56)
    gh.mint_status[INSTALL_ID] = 404
    with pytest.raises(ConnectorError):
        await mint_installation_token(INSTALL_ID)
    gh.mint_status.clear()
    await mint_installation_token(INSTALL_ID)
    assert len(gh.mint_calls) == 3


async def test_mint_server_error_is_not_a_revocation(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    row = await seed_installation(maker)
    gh.mint_status[INSTALL_ID] = 502
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "github_error"
    assert (await reload(maker, row.id)).status is InstallationStatus.ACTIVE


async def test_mint_network_failure_maps_to_a_connector_error(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    gh.mint_route.mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "github_unreachable"


async def test_mint_rejects_a_malformed_token_response(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    gh.mint_route.mock(return_value=httpx.Response(201, json={"token": "x"}))
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "github_error"


async def test_unconfigured_app_raises_before_any_call(
    settings: Settings, maker: async_sessionmaker[Any], clock: Clock
) -> None:
    configure_github_app(settings, maker)
    clear_installation_tokens()
    await seed_installation(maker)
    with respx.mock(assert_all_called=False) as router:
        fake = FakeGitHubApp(router)
        with pytest.raises(ConnectorError) as exc:
            await resolve_installation_credentials(REF)
        assert exc.value.code == "github_app_unconfigured"
        with pytest.raises(ConnectorError) as mint:
            await mint_installation_token(INSTALL_ID)
        assert mint.value.code == "github_app_unconfigured"
        assert fake.mint_calls == []


# ------------------------------------------------------------------ the status gate


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": InstallationStatus.REVOKED},
        {"status": InstallationStatus.SUSPENDED},
        {"deleted": True},
        {"team_deleted": True},
    ],
    ids=["revoked", "suspended", "soft_deleted", "team_deleted"],
)
async def test_unavailable_installations_are_refused(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any], overrides: dict[str, Any]
) -> None:
    await seed_installation(maker, **overrides)
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "installation_unavailable"
    assert gh.mint_calls == []


async def test_unknown_installation_is_refused(gh: FakeGitHubApp) -> None:
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(f"github-app/installation/{uuid.uuid4()}")
    assert exc.value.code == "installation_unavailable"
    assert gh.mint_calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: setattr(row, "status", InstallationStatus.REVOKED),
        lambda row: setattr(row, "status", InstallationStatus.SUSPENDED),
        lambda row: setattr(row, "deleted_at", NOW),
    ],
    ids=["revoked", "suspended", "soft_deleted"],
)
async def test_a_cached_token_does_not_outlive_the_row(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any], mutate: Callable[[TeamInstallation], None]
) -> None:
    seeded = await seed_installation(maker)
    await resolve_installation_credentials(REF)  # warms the cache
    async with maker() as session:
        row = await session.get(TeamInstallation, seeded.id)
        assert row is not None
        mutate(row)
        await session.commit()
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "installation_unavailable"
    assert len(gh.mint_calls) == 1


async def test_a_cached_token_does_not_outlive_the_team(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    seeded = await seed_installation(maker)
    await resolve_installation_credentials(REF)
    async with maker() as session:
        team = await session.get(Team, seeded.team_id)
        assert team is not None
        team.deleted_at = NOW
        await session.commit()
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "installation_unavailable"


async def test_resolve_populates_credentials_metadata(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    creds = await resolve_installation_credentials(REF)
    assert creds.refresh_token is None
    assert creds.metadata == {
        "kind": "github_app_installation",
        "installation_id": INSTALL_ID,
        "team_installation_id": str(ROW_ID),
        "api_base": API,
        "account_login": "acme-robotics",
    }


async def test_api_base_comes_from_the_installation_row(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    base = "https://ghe.example.test/api/v3"
    await seed_installation(maker, api_base_url=base)
    route = gh.router.post(f"{base}/app/installations/{INSTALL_ID}/access_tokens").mock(
        return_value=httpx.Response(
            201, json={"token": "ghs_enterprise", "expires_at": "2026-10-17T13:00:00Z"}
        )
    )
    creds = await resolve_installation_credentials(REF)
    assert route.called and gh.mint_calls == []
    assert creds.token == "ghs_enterprise"
    assert creds.metadata["api_base"] == base


async def test_resolve_refuses_a_malformed_ref(gh: FakeGitHubApp) -> None:
    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials("github-app/installation/../1")
    assert exc.value.code == "invalid_secret_ref"


# ------------------------------------------------------------------ never logged / stored


async def test_the_token_never_reaches_logs_or_text_columns(
    gh: FakeGitHubApp,
    maker: async_sessionmaker[Any],
    engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await seed_installation(maker)
    caplog.set_level(logging.NOTSET)
    logging.getLogger().setLevel(logging.NOTSET)
    creds = await resolve_installation_credentials(REF)
    gh.mint_status[INSTALL_ID] = 404
    invalidate_installation_token(INSTALL_ID)
    with pytest.raises(ConnectorError):
        await resolve_installation_credentials(REF)
    secrets_ = [creds.token, *gh.minted_tokens, *gh.jwts_seen]
    rendered = "\n".join(
        [r.getMessage() + str(r.exc_text) + str(r.args) for r in caplog.records] + [caplog.text]
    )
    for secret in secrets_:
        assert secret not in rendered
    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            dump = (
                await conn.execute(
                    text(
                        f"SELECT coalesce(string_agg(t::text, E'\\n'), '') FROM \"{table.name}\" t"
                    )
                )
            ).scalar_one()
            for secret in secrets_:
                assert secret not in dump, table.name


async def test_the_token_is_not_in_the_minted_repr(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    await seed_installation(maker)
    minted = await mint_installation_token(INSTALL_ID)
    assert minted.token not in repr(minted)
    assert minted.expires_at == NOW + timedelta(hours=1)


# ------------------------------------------------------------------ client: headers, base


def test_client_refuses_a_non_https_base(gh: FakeGitHubApp) -> None:
    with pytest.raises(ValueError):
        GitHubAppClient(api_base_url="http://api.github.com")
    with pytest.raises(ValueError):
        GitHubAppClient(web_base_url="ftp://github.com")


async def test_client_sends_the_github_headers(gh: FakeGitHubApp) -> None:
    gh.add_installation(INSTALL_ID)
    await GitHubAppClient().get_installation(INSTALL_ID)
    request = gh.router.calls.last.request
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert request.headers["authorization"].startswith("Bearer ")


async def test_get_installation_parses_the_record(gh: FakeGitHubApp) -> None:
    gh.add_installation(
        INSTALL_ID, suspended_at="2026-10-01T00:00:00Z", selection="all", account_type="User"
    )
    info = await GitHubAppClient().get_installation(INSTALL_ID)
    assert isinstance(info, InstallationInfo)
    assert (info.installation_id, info.account_login, info.account_id) == (
        INSTALL_ID,
        "acme-robotics",
        777,
    )
    assert info.account_type == "User" and info.repository_selection == "all"
    assert info.account_avatar_url and info.suspended_at is not None
    with pytest.raises(AttributeError):
        info.account_login = "x"  # type: ignore[misc]


async def test_get_installation_404_and_bad_shape(gh: FakeGitHubApp) -> None:
    with pytest.raises(ConnectorError) as missing:
        await GitHubAppClient().get_installation(5)
    assert missing.value.code == "installation_unavailable"
    gh.installations[6] = {"id": 6}
    with pytest.raises(ConnectorError) as bad:
        await GitHubAppClient().get_installation(6)
    assert bad.value.code == "github_error"


# ------------------------------------------------------------------ user-to-server flow


async def test_exchange_user_code_returns_the_bearer_token(gh: FakeGitHubApp) -> None:
    token = await GitHubAppClient().exchange_user_code("the-code")
    assert token == "ghu_usertoken"
    request = gh.code_requests[0]
    body = request.content.decode()
    assert f"client_id={CLIENT_ID}" in body and "code=the-code" in body
    assert f"client_secret={CLIENT_SECRET}" in body
    assert request.headers["accept"] == "application/json"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "bad_verification_code", "error_description": "expired"},
        {"access_token": "ghu_x", "token_type": "mac"},
        {"access_token": "", "token_type": "bearer"},
        {"token_type": "bearer"},
        {"access_token": 5, "token_type": "bearer"},
    ],
)
async def test_exchange_user_code_refuses_bad_payloads(
    gh: FakeGitHubApp, payload: dict[str, Any]
) -> None:
    gh.code_response = payload
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().exchange_user_code("c")
    assert exc.value.code == "oauth_exchange_failed"
    assert CLIENT_SECRET not in exc.value.message


async def test_exchange_user_code_refuses_a_non_json_body(gh: FakeGitHubApp) -> None:
    gh.router.post(f"{WEB}/login/oauth/access_token").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().exchange_user_code("c")
    assert exc.value.code == "oauth_exchange_failed"


async def test_user_installation_ids_walks_pages(gh: FakeGitHubApp) -> None:
    gh.user_pages = [[1, 2], [3], [4, 5]]
    ids = await GitHubAppClient().user_installation_ids("ghu_t")
    assert ids == {1, 2, 3, 4, 5}
    assert all(r.headers["authorization"] == "Bearer ghu_t" for r in gh.user_installations_requests)


async def test_user_installation_ids_caps_pages(gh: FakeGitHubApp) -> None:
    gh.user_pages = [[i] for i in range(1, 30)]
    ids = await GitHubAppClient().user_installation_ids("ghu_t", max_pages=3)
    assert ids == {1, 2, 3}
    assert len(gh.user_installations_requests) == 3


async def test_user_installation_ids_unauthorized(gh: FakeGitHubApp) -> None:
    gh.user_route.mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().user_installation_ids("ghu_t")
    assert exc.value.code == "invalid_credentials"


async def test_revoke_user_token_calls_delete_with_basic_auth(gh: FakeGitHubApp) -> None:
    await GitHubAppClient().revoke_user_token("ghu_t")
    request = gh.revoke_requests[0]
    assert request.url.path == f"/applications/{CLIENT_ID}/token"
    assert basic_auth_user(request) == (CLIENT_ID, CLIENT_SECRET)
    assert b"ghu_t" in request.content


@pytest.mark.parametrize("failure", ["status", "network", "timeout"])
async def test_revoke_user_token_swallows_errors(
    gh: FakeGitHubApp, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    caplog.set_level(logging.NOTSET)
    route = gh.router.delete(url__regex=rf"{API}/applications/[^/]+/token$")
    if failure == "status":
        route.mock(return_value=httpx.Response(500))
    elif failure == "network":
        route.mock(side_effect=httpx.ConnectError("secret-ghu_t-detail"))
    else:
        route.mock(side_effect=httpx.ReadTimeout("slow"))
    await GitHubAppClient().revoke_user_token("ghu_t")  # must not raise
    assert "ghu_t" not in caplog.text


# ------------------------------------------------------------------ pagination guard


def _repo(n: int) -> dict[str, Any]:
    return {"id": n, "full_name": f"acme/r{n}"}


async def test_repo_listing_follows_next_across_pages(gh: FakeGitHubApp) -> None:
    gh.repo_pages = [[_repo(1), _repo(2)], [_repo(3)], [_repo(4)]]
    repos = await GitHubAppClient().list_installation_repos("ghs_t")
    assert [r["id"] for r in repos] == [1, 2, 3, 4]
    assert all(r.headers["authorization"] == "Bearer ghs_t" for r in gh.list_requests)


async def test_repo_listing_caps_pages(gh: FakeGitHubApp) -> None:
    gh.repo_pages = [[_repo(i)] for i in range(1, 30)]
    repos = await GitHubAppClient().list_installation_repos("ghs_t", max_pages=2)
    assert len(repos) == 2 and len(gh.list_requests) == 2


async def test_org_members_are_listed_and_paginated(gh: FakeGitHubApp) -> None:
    gh.member_pages = [[{"id": 1, "login": "a"}], [{"id": 2, "login": "b"}]]
    members = await GitHubAppClient().list_org_members("ghs_t", "acme-robotics")
    assert [m["id"] for m in members] == [1, 2]


async def test_org_login_is_validated_before_any_request(gh: FakeGitHubApp) -> None:
    for bad in ("../admin", "a/b", "", "a b", "x?y=1"):
        with pytest.raises(ConnectorError) as exc:
            await GitHubAppClient().list_org_members("ghs_t", bad)
        assert exc.value.code == "invalid_org"
    assert gh.list_requests == []


async def test_org_membership_role_returns_role_and_state(gh: FakeGitHubApp) -> None:
    gh.membership_body = {"state": "active", "role": "admin"}
    result = await GitHubAppClient().org_membership_role("ghu_t", "acme-robotics")
    assert result == ("admin", "active")
    request = gh.membership_requests[0]
    assert request.url.path == "/user/memberships/orgs/acme-robotics"
    assert request.headers["authorization"] == "Bearer ghu_t"


@pytest.mark.parametrize("status", [403, 404])
async def test_org_membership_role_is_none_when_not_a_member(
    gh: FakeGitHubApp, status: int
) -> None:
    gh.membership_status = status
    assert await GitHubAppClient().org_membership_role("ghu_t", "acme-robotics") is None


@pytest.mark.parametrize("body", [[], "x", {"role": "admin"}, {"state": 1, "role": "admin"}])
async def test_org_membership_role_malformed_body_is_github_error(
    gh: FakeGitHubApp, body: Any
) -> None:
    gh.membership_body = body
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().org_membership_role("ghu_t", "acme-robotics")
    assert exc.value.code == "github_error"


async def test_org_membership_role_server_error_and_network_failure(gh: FakeGitHubApp) -> None:
    gh.membership_status = 500
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().org_membership_role("ghu_t", "acme-robotics")
    assert exc.value.code == "github_error"
    gh.membership_status = 200
    gh.membership_network_error = True
    with pytest.raises(ConnectorError) as exc2:
        await GitHubAppClient().org_membership_role("ghu_t", "acme-robotics")
    assert exc2.value.code == "github_unreachable"


async def test_org_membership_login_is_validated_before_any_request(gh: FakeGitHubApp) -> None:
    for bad in ("../admin", "a/b", "", "a b", "x?y=1"):
        with pytest.raises(ConnectorError) as exc:
            await GitHubAppClient().org_membership_role("ghu_t", bad)
        assert exc.value.code == "invalid_org"
    assert gh.membership_requests == []


async def test_user_id_reads_the_authenticated_user(gh: FakeGitHubApp) -> None:
    gh.user_body = {"id": 31337, "login": "me"}
    assert await GitHubAppClient().user_id("ghu_t") == 31337
    assert gh.user_profile_requests[0].headers["authorization"] == "Bearer ghu_t"


@pytest.mark.parametrize("body", [[], {}, {"id": "7"}, {"id": True}])
async def test_user_id_malformed_body_is_github_error(gh: FakeGitHubApp, body: Any) -> None:
    gh.user_body = body
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().user_id("ghu_t")
    assert exc.value.code == "github_error"


async def test_user_id_rejection_and_network_failure(gh: FakeGitHubApp) -> None:
    gh.user_status = 401
    with pytest.raises(ConnectorError) as exc:
        await GitHubAppClient().user_id("ghu_t")
    assert exc.value.code == "invalid_credentials"
    gh.user_status = 200
    gh.user_network_error = True
    with pytest.raises(ConnectorError) as exc2:
        await GitHubAppClient().user_id("ghu_t")
    assert exc2.value.code == "github_unreachable"


@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.example/user/installations?page=2>; rel="next"',
        '<http://api.github.com/user/installations?page=2>; rel="next"',
        '<https://api.github.com.evil.example/user/installations?page=2>; rel="next"',
        '<https://api.github.com:8443/user/installations?page=2>; rel="next"',
    ],
    ids=["foreign_host", "scheme_downgrade", "suffix_host", "other_port"],
)
async def test_a_foreign_next_link_is_never_followed(gh: FakeGitHubApp, link: str) -> None:
    gh.user_pages = [[1]]
    gh.next_link_override = link
    trap = gh.router.get(
        url__regex=r"https?://(evil\.example|api\.github\.com(\.evil\.example|:8443)?)/.*"
    ).mock(return_value=httpx.Response(200, json={"installations": [{"id": 666}]}))
    ids = await GitHubAppClient().user_installation_ids("ghu_secret")
    assert ids == {1}
    for call in gh.router.calls:
        assert call.request.url.host in {"api.github.com"} and call.request.url.port is None
    assert not [c for c in trap.calls if c.request.url.host != "api.github.com"]


@pytest.mark.parametrize(
    "link",
    [
        "garbage",
        "<>; rel=next",
        '<::not a url::>; rel="next"',
        '<https://api.github.com/x>; rel="prev"',
        "",
    ],
)
async def test_malformed_link_headers_are_ignored(gh: FakeGitHubApp, link: str) -> None:
    gh.user_pages = [[1]]
    gh.next_link_override = link
    assert await GitHubAppClient().user_installation_ids("ghu_t") == {1}
    assert len(gh.user_installations_requests) == 1


# ------------------------------------------------------------------ reserved refs


def test_ref_helpers_round_trip() -> None:
    assert github_app.INSTALLATION_REF_PREFIX == "github-app/installation/"
    assert github_app.installation_secret_ref(ROW_ID) == REF
    assert github_app.is_installation_ref(REF)
    assert github_app.parse_installation_ref(REF) == ROW_ID


@pytest.mark.parametrize(
    "ref",
    [
        "github-app/installation/abc",
        "github-app/installation/../1",
        "github-app/installation/1001",
        f"{REF}/refresh",
        f"{REF}/hosted/x",
        f"github-app/installation/{str(ROW_ID).upper()}",
        f"github-app/installation/{ROW_ID.hex}",
        f"github-app/installation/{{{ROW_ID}}}",
        f"{REF} ",
        f" {REF}",
        "github-app/installation/",
        "github-app/installation",
        "/github-app/installation/1",
        "github-app/installation/١٢",
        "connection/1",
        "",
    ],
)
def test_parse_installation_ref_refuses_anything_but_the_exact_form(ref: str) -> None:
    with pytest.raises(ValueError):
        github_app.parse_installation_ref(ref)


@pytest.mark.parametrize("bad", [0, 1001, str(ROW_ID)])
def test_installation_secret_ref_needs_the_row_uuid(bad: object) -> None:
    # GitHub's numeric id is refused: a ref must name OUR row (re-link isolation).
    with pytest.raises(ValueError):
        github_app.installation_secret_ref(bad)  # type: ignore[arg-type]


def test_is_installation_ref_is_prefix_based_and_none_safe() -> None:
    assert github_app.is_installation_ref("github-app/installation/anything")
    assert not github_app.is_installation_ref(None)
    assert not github_app.is_installation_ref("source/1/github")


async def test_status_gate_reads_a_fresh_row_each_time(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    seeded = await seed_installation(maker)
    await resolve_installation_credentials(REF)
    async with maker() as session:
        rows = (await session.scalars(select(TeamInstallation))).all()
        assert len(rows) == 1 and rows[0].id == seeded.id


async def test_a_stale_ref_never_resolves_against_another_teams_relink(
    gh: FakeGitHubApp, maker: async_sessionmaker[Any]
) -> None:
    """Team A unlinks; team B links the SAME GitHub installation. A's copied ref (e.g. a
    revision source) must not mint a token for B's link (cross-tenant, ADR-039 §3-4)."""
    await seed_installation(maker, deleted=True, status=InstallationStatus.REVOKED)
    relink = uuid.UUID("0190f0e0-0000-7000-8000-000000000002")
    await seed_installation(maker, row_id=relink)

    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(REF)
    assert exc.value.code == "installation_unavailable"
    assert gh.mint_calls == []

    creds = await resolve_installation_credentials(github_app.installation_secret_ref(relink))
    assert creds.metadata["installation_id"] == INSTALL_ID
    assert creds.metadata["team_installation_id"] == str(relink)
