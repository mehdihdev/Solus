"""Error envelope per §1.4: {"error": {"code", "message", "details"}}."""

from httpx import AsyncClient
from solus_api.core.errors import APIError


def test_api_error_defaults_code_from_status() -> None:
    err = APIError(404)
    assert err.code == "not_found"
    assert err.status_code == 404
    assert err.details == []


def test_api_error_custom_code_and_details() -> None:
    err = APIError(409, "invite_expired", "Invite has expired", [{"field": "token"}])
    assert err.code == "invite_expired"
    assert err.message == "Invite has expired"
    assert err.details == [{"field": "token"}]


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]
    assert "details" in body["error"]


async def test_validation_error_envelope(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/v1/teams", json={}, headers=alice_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]
