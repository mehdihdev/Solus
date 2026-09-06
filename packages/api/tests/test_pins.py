"""SOLUSDEV-246 (STORE ST3) — "Pin for all projects".

`/api/v1/users/me/extension-pins`: a per-USER, cross-project list of extension
slugs whose tab shows in every project (docs/api/extensions.md §6.5). Pins are
account state, never project state: they carry no grants, install nothing, and
follow the catalog row (an unpublished extension's pin disappears from the list).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import me
from fastapi import FastAPI
from fixtures.extensions.routes import (
    consent,
    events_of,
    install,
    installs_app,
    manifest_with,
    project_for,
    seed_extension,
)
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.models import Extension, UserExtensionPin, utcnow
from solus_api.routers.extensions import pins as pins_router
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

PINS = "/api/v1/users/me/extension-pins"


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    application = installs_app(settings, engine)
    application.include_router(pins_router.router)
    return application


async def _pinned_slugs(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    resp = await client.get(PINS, headers=headers)
    assert resp.status_code == 200, resp.text
    return [row["slug"] for row in resp.json()["data"]]


# ------------------------------------------------------------------ auth


async def test_pins_require_a_signed_in_user(client: AsyncClient) -> None:
    assert (await client.get(PINS)).status_code == 401
    assert (await client.put(f"{PINS}/bom")).status_code == 401
    assert (await client.delete(f"{PINS}/bom")).status_code == 401


# ------------------------------------------------------------------ PUT


async def test_pin_is_201_then_200_and_carries_the_rail_facts(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, "bom", {"1.2.0": manifest_with("1.2.0", slug="bom")})

    first = await client.put(f"{PINS}/bom", headers=alice_headers)
    again = await client.put(f"{PINS}/bom", headers=alice_headers)

    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    row = first.json()["data"]
    assert row["slug"] == "bom"
    assert row["name"] == "BOM"
    assert row["verified"] is False
    assert row["publisher"] == {"display_name": "Solus"}
    assert row["version"] == "1.2.0"
    # The latest approved manifest's page view — the rail draws a pinned tab
    # from this even in a project where the bundle is not installed.
    assert row["page"] == {"label": "BOM", "icon": "icon.svg"}
    assert row["pinned_at"]
    assert await _pinned_slugs(client, alice_headers) == ["bom"]


async def test_pin_slug_is_normalised_and_validated(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, "bom")
    assert (await client.put(f"{PINS}/BOM", headers=alice_headers)).status_code == 201
    assert await _pinned_slugs(client, alice_headers) == ["bom"]
    bad = await client.put(f"{PINS}/Not_A_Slug!", headers=alice_headers)
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"


async def test_pinning_an_unknown_or_unpublished_extension_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    assert (await client.put(f"{PINS}/ghost", headers=alice_headers)).status_code == 404
    catalog = await seed_extension(db, "gone")
    await db.execute(
        update(Extension).where(Extension.id == catalog.extension_id).values(deleted_at=utcnow())
    )
    await db.commit()
    assert (await client.put(f"{PINS}/gone", headers=alice_headers)).status_code == 404


async def test_pins_are_capped_per_user(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    for i in range(pins_router.PINS_MAX_PER_USER):
        await seed_extension(db, f"ext-{i}")
        assert (await client.put(f"{PINS}/ext-{i}", headers=alice_headers)).status_code == 201
    await seed_extension(db, "one-too-many")
    resp = await client.put(f"{PINS}/one-too-many", headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    assert len(await _pinned_slugs(client, alice_headers)) == pins_router.PINS_MAX_PER_USER


# ------------------------------------------------------------------ GET


async def test_list_is_pinned_order_and_hides_unpublished_rows(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, "bom")
    gone = await seed_extension(db, "gone")
    await seed_extension(db, "scope")
    for slug in ("scope", "gone", "bom"):
        assert (await client.put(f"{PINS}/{slug}", headers=alice_headers)).status_code == 201
    await db.execute(
        update(Extension).where(Extension.id == gone.extension_id).values(deleted_at=utcnow())
    )
    await db.commit()

    assert await _pinned_slugs(client, alice_headers) == ["scope", "bom"]


async def test_pins_are_per_user(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    await seed_extension(db, "bom")
    assert (await client.put(f"{PINS}/bom", headers=alice_headers)).status_code == 201

    assert await _pinned_slugs(client, bob_headers) == []
    # Bob unpinning a slug he never pinned changes nothing of Alice's.
    assert (await client.delete(f"{PINS}/bom", headers=bob_headers)).status_code == 204
    assert await _pinned_slugs(client, alice_headers) == ["bom"]


# ------------------------------------------------------------------ DELETE


async def test_unpin_is_idempotent_and_emits_events(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, "bom")
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])
    assert (await client.put(f"{PINS}/bom", headers=alice_headers)).status_code == 201

    assert (await client.delete(f"{PINS}/bom", headers=alice_headers)).status_code == 204
    assert (await client.delete(f"{PINS}/bom", headers=alice_headers)).status_code == 204
    assert await _pinned_slugs(client, alice_headers) == []

    pinned = await events_of(db, "extension.pinned")
    unpinned = await events_of(db, "extension.unpinned")
    assert [e.payload for e in pinned] == [{"slug": "bom"}]
    assert [e.payload for e in unpinned] == [{"slug": "bom"}]


async def test_unpin_unknown_slug_is_404_not_a_silent_204(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    assert (await client.delete(f"{PINS}/ghost", headers=alice_headers)).status_code == 404


# ------------------------------------------------------------ independence


async def test_a_pin_is_independent_of_installs(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Pinning installs nothing; uninstalling removes no pin (ST3 acceptance:
    the tab in project B is a pin, the bundle in project A is an install)."""
    await seed_extension(db, "bom")
    _, project_a = await project_for(client, alice_headers)
    assert (await client.put(f"{PINS}/bom", headers=alice_headers)).status_code == 201

    installs = await client.get(f"/api/v1/projects/{project_a}/extensions", headers=alice_headers)
    assert installs.json()["data"] == []

    assert (await install(client, alice_headers, project_a)).status_code == 201
    uninstalled = await client.delete(
        f"/api/v1/projects/{project_a}/extensions/bom", headers=alice_headers
    )
    assert uninstalled.status_code == 204
    assert await _pinned_slugs(client, alice_headers) == ["bom"]


async def test_pin_rows_are_unique_per_user_and_extension(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await seed_extension(db, "bom")
    for _ in range(3):
        await client.put(f"{PINS}/bom", headers=alice_headers)
    total = await db.scalar(select(func.count()).select_from(UserExtensionPin))
    assert total == 1


async def test_pin_writes_take_the_shared_install_budget(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, settings: Settings
) -> None:
    await seed_extension(db, "bom")
    budget = settings.extension_install_writes_per_minute_per_user
    last: Any = None
    for _ in range(budget + 1):
        last = await client.put(f"{PINS}/bom", headers=alice_headers)
    assert last.status_code == 429
    assert last.headers.get("Retry-After")
