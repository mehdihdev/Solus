"""The extensions router aggregator is wired into `create_app()` (SOLUSDEV-235 EXT-03).

The aggregator ships empty — sub-routers (catalog, publish, installs, storage,
layout, policy) are later EXT tasks that `include_router` into it. What this
suite pins is the seam: whatever is mounted on the aggregator is served by the
app, and a miss under `/api/v1/extensions` is the standard 404 envelope, never a
405 or an unenveloped 500.
"""

from collections.abc import Iterator

import pytest
from conftest import ALICE, bearer
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.routers import extensions
from sqlalchemy.ext.asyncio import AsyncEngine

PROBE_PATH = "/api/v1/extensions/_ext03_probe"


@pytest.fixture
def probe_route() -> Iterator[None]:
    """Mount a throwaway route on the aggregator for the duration of one test.
    `include_router` copies routes at include time, so the probe must be present
    BEFORE `create_app()` runs — and must be gone afterwards for every other suite."""

    async def _probe() -> dict[str, str]:
        return {"data": "probe"}

    before = len(extensions.router.routes)
    extensions.router.add_api_route(PROBE_PATH, _probe, methods=["GET"])
    try:
        yield
    finally:
        del extensions.router.routes[before:]


async def test_aggregator_starts_empty_and_is_an_apirouter() -> None:
    assert extensions.router.routes == []
    assert extensions.router.prefix == ""


async def test_routes_mounted_on_the_aggregator_are_served_by_create_app(
    probe_route: None, settings: Settings, engine: AsyncEngine
) -> None:
    app: FastAPI = create_app(settings=settings, engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(PROBE_PATH)
    assert resp.status_code == 200
    assert resp.json() == {"data": "probe"}


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_unknown_extensions_path_is_the_standard_404_envelope(
    client: AsyncClient, method: str
) -> None:
    resp = await client.request(
        method, "/api/v1/extensions/no-such-thing", headers=bearer(ALICE["sub"], ALICE["email"])
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert set(body["error"]) == {"code", "message", "details"}
