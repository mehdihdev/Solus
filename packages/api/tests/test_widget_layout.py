"""Widget layout — docs/api/extensions.md §8 (SOLUSDEV-235 EXT-09): the empty
default, round-trip, per-user separation, and the shape rules (≤ 24 slots,
ref regexes, distinct refs, CTR-01 sizes) → 422."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import BOB, add_member
from fastapi import FastAPI
from fixtures.extensions.routes import installs_app, project_for
from httpx import AsyncClient
from solus_api.core.config import Settings
from solus_api.models import WIDGET_LAYOUT_MAX_SLOTS, DataEvent, WidgetLayout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SLOTS = [{"ref": "builtin:signals", "size": "wide"}, {"ref": "ext:bom", "size": "standard"}]


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return installs_app(settings, engine)


def url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/widget-layout"


async def test_get_without_a_stored_row_is_the_empty_default(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await client.get(url(project_id), headers=alice_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"data": {"project_id": project_id, "layout": [], "updated_at": None}}


async def test_put_replaces_the_whole_layout_and_get_returns_it(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project_id = await project_for(client, alice_headers)

    saved = await client.put(url(project_id), json={"layout": SLOTS}, headers=alice_headers)
    got = await client.get(url(project_id), headers=alice_headers)
    replaced = await client.put(url(project_id), json={"layout": [SLOTS[1]]}, headers=alice_headers)

    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["layout"] == SLOTS
    assert saved.json()["data"]["project_id"] == project_id
    assert saved.json()["data"]["updated_at"] is not None
    assert got.json()["data"]["layout"] == SLOTS
    assert replaced.json()["data"]["layout"] == [SLOTS[1]]
    rows = (await db.scalars(select(WidgetLayout))).all()
    assert len(rows) == 1 and rows[0].layout == [SLOTS[1]]
    # §8: pure per-user display state — no data event.
    assert (await db.scalars(select(DataEvent))).all() == []


async def test_an_empty_layout_can_be_saved(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    assert (
        await client.put(url(project_id), json={"layout": SLOTS}, headers=alice_headers)
    ).status_code == 200

    resp = await client.put(url(project_id), json={"layout": []}, headers=alice_headers)

    assert resp.status_code == 200
    assert resp.json()["data"]["layout"] == []


async def test_layouts_are_personal_per_user_within_one_project(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team_id, project_id = await project_for(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="member")
    bobs = [{"ref": "builtin:console", "size": "full"}]

    assert (
        await client.put(url(project_id), json={"layout": SLOTS}, headers=alice_headers)
    ).status_code == 200
    assert (
        await client.put(url(project_id), json={"layout": bobs}, headers=bob_headers)
    ).status_code == 200

    assert (await client.get(url(project_id), headers=alice_headers)).json()["data"][
        "layout"
    ] == SLOTS
    assert (await client.get(url(project_id), headers=bob_headers)).json()["data"]["layout"] == bobs


async def test_layouts_are_per_project_for_one_user(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    from conftest import create_project, create_team

    team = await create_team(client, alice_headers)
    p1 = (await create_project(client, alice_headers, team["id"], "P1"))["id"]
    p2 = (await create_project(client, alice_headers, team["id"], "P2"))["id"]

    assert (
        await client.put(url(p1), json={"layout": SLOTS}, headers=alice_headers)
    ).status_code == 200

    assert (await client.get(url(p2), headers=alice_headers)).json()["data"]["layout"] == []


async def test_ext_refs_are_not_checked_against_installs(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await client.put(
        url(project_id),
        json={"layout": [{"ref": "ext:not-installed", "size": "compact"}]},
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "body",
    [
        {"layout": [{"ref": "builtin:signals", "size": "huge"}]},
        {"layout": [{"ref": "signals", "size": "wide"}]},
        {"layout": [{"ref": "ext:Bom", "size": "wide"}]},
        {"layout": [{"ref": "ext:b", "size": "wide"}]},
        {"layout": [{"ref": "builtin:", "size": "wide"}]},
        {"layout": [{"ref": "ext:bom", "size": "wide"}, {"ref": "ext:bom", "size": "compact"}]},
        {"layout": [{"ref": "ext:bom", "size": "wide", "x": 1}]},
        {"layout": [{"ref": "ext:bom"}]},
        {"layout": SLOTS, "extra": True},
        {},
        {
            "layout": [
                {"ref": f"builtin:w{i}", "size": "compact"}
                for i in range(WIDGET_LAYOUT_MAX_SLOTS + 1)
            ]
        },
    ],
    ids=[
        "bad-size",
        "ref-without-prefix",
        "ext-uppercase",
        "ext-too-short",
        "builtin-empty",
        "duplicate-refs",
        "unknown-slot-key",
        "missing-size",
        "unknown-top-level",
        "missing-layout",
        "too-many-slots",
    ],
)
async def test_layout_shape_violations_are_422(
    client: AsyncClient, alice_headers: dict[str, str], body: dict[str, Any]
) -> None:
    _, project_id = await project_for(client, alice_headers)

    resp = await client.put(url(project_id), json=body, headers=alice_headers)

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_exactly_the_maximum_number_of_slots_is_accepted(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    full = [{"ref": f"builtin:w{i}", "size": "compact"} for i in range(WIDGET_LAYOUT_MAX_SLOTS)]

    resp = await client.put(url(project_id), json={"layout": full}, headers=alice_headers)

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]["layout"]) == WIDGET_LAYOUT_MAX_SLOTS
