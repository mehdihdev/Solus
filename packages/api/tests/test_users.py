"""§2.1 Users & settings (api-keys deferred to a later slice per §8 Phase 1)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import ALICE, BOB, add_member, bearer, create_team, me
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import Subscription, SubscriptionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_get_me_shape(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    data = await me(client, alice_headers)
    assert set(data) >= {"id", "email", "name", "avatar_url", "created_at", "teams"}
    team = data["teams"][0]
    assert set(team) >= {"team_id", "name", "role", "is_personal", "plan_status", "trial_ends_at"}
    assert team["plan_status"] == "trial"


async def test_patch_me_updates_profile(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        json={"name": "Alice Liddell", "avatar_url": "https://example.com/a.png"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Alice Liddell"
    assert (await me(client, alice_headers))["name"] == "Alice Liddell"


async def test_patch_me_rejects_unknown_fields(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch("/api/v1/users/me", json={"email": "x@y.z"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_settings_default_sol_mode_guide(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_mode"] == "guide"


async def test_settings_patch_sol_mode(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"sol_mode": "expert"}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_mode"] == "expert"


async def test_settings_patch_rejects_invalid_mode(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"sol_mode": "yolo"}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_delete_me_removes_account_and_personal_team(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204

    # Deletion is durable (SOLUSDEV-82): a still-valid token for the deleted
    # identity is refused, not silently re-provisioned into a zombie account.
    after = await client.get("/api/v1/users/me", headers=alice_headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "account_deleted"


async def test_delete_me_blocked_while_sole_owner_of_shared_team(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ownership_transfer_required"


async def test_users_cannot_read_each_other(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    assert alice["id"] != bob["id"]
    assert alice["email"] == ALICE["email"]
    assert bob["email"] == BOB["email"]


async def test_settings_include_and_persist_consent(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """ADR-011: collection is consent-gated, so consent must be a settable
    setting — defaulting to off."""
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["data_collection_consent"] is False

    resp = await client.patch(
        "/api/v1/users/me/settings",
        json={"data_collection_consent": True},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["data_collection_consent"] is True
    # And it round-trips.
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["data_collection_consent"] is True

    # Revocation: False is an explicit value, not "unset" — opting back out
    # must work (ADR-011), and must survive a naive truthiness refactor.
    resp = await client.patch(
        "/api/v1/users/me/settings",
        json={"data_collection_consent": False},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["data_collection_consent"] is False
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["data_collection_consent"] is False


async def test_consent_gate_actually_opens(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """Before opt-in no DataEvent rows are written; after opt-in they are."""
    from solus_api.models import DataEvent
    from sqlalchemy import func, select

    async def event_count() -> int:
        async with app.state.sessionmaker() as db:
            return int(await db.scalar(select(func.count()).select_from(DataEvent)) or 0)

    team = await create_team(client, alice_headers)  # emits team.created (unconsented)
    assert await event_count() == 0

    await client.patch(
        "/api/v1/users/me/settings",
        json={"data_collection_consent": True},
        headers=alice_headers,
    )
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "Consented"}, headers=alice_headers
    )
    assert resp.status_code == 201
    assert await event_count() >= 1


async def test_onboarding_step_defaults_and_round_trips(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """FND-08: onboarding state persists server-side so resume works across
    reloads and machines."""
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["onboarding_step"] == "about"

    for step in ("connect", "build", "done"):
        resp = await client.patch(
            "/api/v1/users/me/settings", json={"onboarding_step": step}, headers=alice_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["onboarding_step"] == step

    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["onboarding_step"] == "done"


async def test_onboarding_step_rejects_unknown_value(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"onboarding_step": "yolo"}, headers=alice_headers
    )
    assert resp.status_code == 422


# --------------------------------------- custom instruction (SOLUSDEV-233)


async def test_custom_instruction_defaults_none_and_round_trips(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/users/me/settings", headers=alice_headers)
    assert resp.json()["data"]["sol_custom_instruction"] is None

    resp = await client.patch(
        "/api/v1/users/me/settings",
        json={"sol_custom_instruction": "Prefer metric units."},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_custom_instruction"] == "Prefer metric units."

    # Absent field = no change; explicit null = clear.
    resp = await client.patch(
        "/api/v1/users/me/settings", json={"sol_mode": "expert"}, headers=alice_headers
    )
    assert resp.json()["data"]["sol_custom_instruction"] == "Prefer metric units."
    resp = await client.patch(
        "/api/v1/users/me/settings",
        json={"sol_custom_instruction": None},
        headers=alice_headers,
    )
    assert resp.json()["data"]["sol_custom_instruction"] is None


async def test_custom_instruction_rejects_over_cap(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/settings",
        json={"sol_custom_instruction": "x" * 501},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_custom_instruction_text_never_reaches_data_events(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """The instruction is user-authored prompt input — events record THAT it
    changed, never WHAT it says (§7: prompt content stays out of stores)."""
    from solus_api.models import DataEvent
    from sqlalchemy import select

    await client.patch(
        "/api/v1/users/me/settings",
        json={"data_collection_consent": True},
        headers=alice_headers,
    )
    secret_text = "Prefer metric units and mention project Falcon."
    await client.patch(
        "/api/v1/users/me/settings",
        json={"sol_custom_instruction": secret_text},
        headers=alice_headers,
    )
    async with app.state.sessionmaker() as db:
        events = (await db.scalars(select(DataEvent))).all()
    assert events, "consented settings change must emit an event"
    for event in events:
        assert secret_text not in str(event.payload)


async def test_custom_instruction_is_private_to_its_owner(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """The instruction is per-user prompt input (§7): another user's settings
    response must never carry it."""
    secret_note = "Alice's private preference about project Falcon."
    await client.patch(
        "/api/v1/users/me/settings",
        json={"sol_custom_instruction": secret_note},
        headers=alice_headers,
    )
    resp = await client.get("/api/v1/users/me/settings", headers=bob_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["sol_custom_instruction"] is None
    assert secret_note not in resp.text


# --- SOLUSDEV-236: trial length + team trial_ends_at come from the caller's subscription ---


async def _own_sub(db: AsyncSession, user_id: str) -> Subscription:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
    assert sub is not None
    return sub


def _parse(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def test_team_trial_ends_at_is_callers_subscription_expiry(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _own_sub(db, alice["id"])
    sub.expires_at = datetime(2031, 3, 4, 5, 6, tzinfo=UTC)
    await db.commit()
    data = await me(client, alice_headers)
    assert _parse(data["teams"][0]["trial_ends_at"]) == datetime(2031, 3, 4, 5, 6, tzinfo=UTC)


async def test_team_trial_ends_at_is_null_when_not_trialing(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _own_sub(db, alice["id"])
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()
    data = await me(client, alice_headers)
    assert data["teams"][0]["trial_ends_at"] is None


async def test_team_trial_ends_at_never_uses_another_members_subscription(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    alice_end = datetime(2031, 1, 1, tzinfo=UTC)
    bob_end = datetime(2032, 2, 2, tzinfo=UTC)
    (await _own_sub(db, alice["id"])).expires_at = alice_end
    (await _own_sub(db, bob["id"])).expires_at = bob_end
    await db.commit()
    team = await create_team(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    for headers, expected in ((alice_headers, alice_end), (bob_headers, bob_end)):
        teams = (await me(client, headers))["teams"]
        shared = next(t for t in teams if t["team_id"] == team["id"])
        assert _parse(shared["trial_ends_at"]) == expected


async def test_provisioned_trial_length_reads_single_config_value(
    settings: Settings, engine: Any, db: AsyncSession
) -> None:
    app = create_app(settings=settings.model_copy(update={"stripe_trial_days": 7}), engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        headers = bearer(ALICE["sub"], ALICE["email"])
        user = await me(c, headers)
    sub = await _own_sub(db, user["id"])
    assert sub.expires_at is not None
    remaining = _expires(sub) - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


def _expires(sub: Subscription) -> datetime:
    assert sub.expires_at is not None
    return sub.expires_at if sub.expires_at.tzinfo else sub.expires_at.replace(tzinfo=UTC)
