"""SOLUSDEV-235 (EXT-03/EXT integration) — the extensions router aggregator.

`routers/extensions/__init__.py` is the one shared mount point: `create_app`
includes it, and each extension sub-router (publish, review, bundle, catalog,
installs, policy) is included on it in an order that keeps literal paths ahead
of the catalog's generic `/{slug}`.
"""

import pytest
from conftest import ALICE, bearer
from fastapi import APIRouter
from fastapi.routing import APIRoute
from httpx import AsyncClient
from solus_api.routers import extensions


def test_aggregator_mounts_every_extension_sub_router() -> None:
    assert isinstance(extensions.router, APIRouter)
    paths = [route.path for route in extensions.router.routes if isinstance(route, APIRoute)]
    for expected in (
        "/api/v1/extensions/publish",
        "/api/v1/extensions/{slug}/versions/{version}/review",
        "/api/v1/extensions/{slug}/versions/{version}/bundle",
        "/api/v1/extensions",
        "/api/v1/projects/{project_id}/extensions",
        "/api/v1/projects/{project_id}/widget-layout",
        "/api/v1/teams/{team_id}/extensions/policies",
    ):
        assert expected in paths, expected
    # `/publish` must register before `/{slug}` so a POST never resolves to the
    # catalog detail route.
    assert paths.index("/api/v1/extensions/publish") < paths.index("/api/v1/extensions/{slug}")


async def test_extension_routes_are_served_by_create_app(client: AsyncClient) -> None:
    """The aggregator is included by create_app: the catalog list is reachable
    (and demands auth) instead of falling through to a 404."""
    resp = await client.get("/api/v1/extensions")
    assert resp.status_code == 401


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_unknown_extensions_path_is_the_standard_404_envelope(
    client: AsyncClient, method: str
) -> None:
    resp = await client.request(
        method,
        "/api/v1/extensions/no-such-thing/nor/this/path",
        headers=bearer(ALICE["sub"], ALICE["email"]),
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert set(body["error"]) == {"code", "message", "details"}
