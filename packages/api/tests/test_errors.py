"""Error envelope per §1.4: {"error": {"code", "message", "details"}}."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
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


async def test_uncaught_exception_returns_enveloped_500(app: FastAPI) -> None:
    """An uncaught error hits the catch-all handler and still returns the §1.4
    envelope (not FastAPI's default 500). `raise_app_exceptions=False` lets httpx
    return the handler's response instead of re-raising what ServerErrorMiddleware
    re-throws for the server log."""

    async def _boom() -> None:
        raise RuntimeError("intentional test failure")

    app.add_api_route("/api/v1/_boom", _boom, methods=["GET"])
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/_boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal server error"
    assert "details" in body["error"]


# ------------------------------------------------ S3 review H2: 422 never echoes the input


def test_redact_input_keeps_short_scalars_and_hides_long_or_structured_values() -> None:
    from solus_api.core.errors import _redact_input

    assert _redact_input({"loc": ["body", "n"], "msg": "x", "input": "short"})["input"] == "short"
    assert _redact_input({"loc": [], "msg": "x", "input": 7})["input"] == 7
    assert _redact_input({"loc": [], "msg": "x", "input": "a" * 257})["input"] == (
        "<redacted: 257 chars>"
    )
    assert _redact_input({"loc": [], "msg": "x", "input": {"data": "a" * 5}})["input"] == (
        "<redacted>"
    )
    assert _redact_input({"loc": [], "msg": "x", "input": [1, 2]})["input"] == "<redacted>"
    assert _redact_input({"loc": ["body"], "msg": "x"}) == {"loc": ["body"], "msg": "x"}


async def test_a_sibling_field_failure_does_not_echo_the_screenshot(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """pydantic sets `input` to the PARENT object for `missing` errors, so a
    missing `content` next to a screenshot used to return the whole base64
    payload in the 422 body."""
    from conftest import create_project, create_team, me

    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    convo = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations",
        json={"title": "t"},
        headers=alice_headers,
    )
    data = "A" * 5000
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{convo.json()['data']['id']}/messages",
        json={
            "screenshot": {"media_type": "image/png", "data": data, "width": 1, "height": 1},
        },
        headers=alice_headers,
    )
    assert resp.status_code == 422, resp.text
    assert data not in resp.text
    [detail] = resp.json()["error"]["details"]
    assert detail["loc"] == ["body", "content"] and detail["type"] == "missing"
    assert detail["input"] == "<redacted>"


async def test_a_short_field_failure_still_names_loc_and_msg(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/v1/teams", json={"name": 7}, headers=alice_headers)
    assert resp.status_code == 422
    [detail] = resp.json()["error"]["details"]
    assert detail["loc"] == ["body", "name"] and detail["msg"] and detail["input"] == 7
