"""SOLUSDEV-216 S216-T5: transport and authentication of POST /api/v1/webhooks/github/app.

The signature is the only credential, so the headline claims are measured: a bad signature
never reaches the JSON parser, an oversize body is refused (by header and while streaming),
and a redelivery does its work once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.team_installation_seed import seed_installation, seed_installation_source, seed_team
from httpx import AsyncClient
from pydantic import SecretStr
from solus_api.connectors import worker
from solus_api.core.config import Settings
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

URL = "/api/v1/webhooks/github/app"
SECRET = "whsec-t5-test-secret"  # placeholder, not a real secret
MAX_BYTES = 2 * 1024 * 1024


@pytest.fixture
def settings(settings: Settings) -> Settings:
    # Production write budget, so the "never shares the global bucket" claim is measurable.
    return settings.model_copy(
        update={
            "github_app_webhook_secret": SecretStr(SECRET),
            "write_rate_limit_per_minute": 120,
        }
    )


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def fake_sync(**kwargs: Any) -> None:
        calls.append(kwargs["source_id"])

    monkeypatch.setattr(worker, "execute_source_sync", fake_sync)
    return calls


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def headers(body: bytes, *, event: str = "push", delivery: str | None = None) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": sign(body),
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


def push_body(
    installation_id: int, repo: str = "acme/robot", ref: str = "refs/heads/main"
) -> bytes:
    return json.dumps(
        {"ref": ref, "repository": {"full_name": repo}, "installation": {"id": installation_id}}
    ).encode()


@pytest.fixture
def parse_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []
    real = json.loads

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(args[0] if args else None)
        return real(*args, **kwargs)

    monkeypatch.setattr(json, "loads", spy)
    return seen


async def test_ping_returns_204(client: AsyncClient) -> None:
    body = b'{"zen":"hi"}'
    resp = await client.post(URL, content=body, headers=headers(body, event="ping"))
    assert resp.status_code == 204


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "sha256=" + "0" * 64,
        "sha256=" + "A" * 64,
        "sha256=short",
        "sha1=" + "0" * 40,
        "SHA256=" + "0" * 64,
    ],
)
async def test_bad_missing_or_malformed_signature_is_401_and_body_never_parsed(
    client: AsyncClient, parse_spy: list[Any], bad: str | None
) -> None:
    body = push_body(1)
    hdrs = headers(body)
    if bad is None:
        del hdrs["X-Hub-Signature-256"]
    else:
        hdrs["X-Hub-Signature-256"] = bad

    resp = await client.post(URL, content=body, headers=hdrs)

    assert resp.status_code == 401
    assert not any(isinstance(x, bytes) and b"acme/robot" in x for x in parse_spy)
    assert not any(isinstance(x, str) and "acme/robot" in x for x in parse_spy)


async def test_sha1_only_signature_is_401(client: AsyncClient) -> None:
    body = push_body(1)
    hdrs = headers(body)
    del hdrs["X-Hub-Signature-256"]
    hdrs["X-Hub-Signature"] = "sha1=" + hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
    resp = await client.post(URL, content=body, headers=hdrs)
    assert resp.status_code == 401


async def test_signature_over_different_bytes_is_401(client: AsyncClient) -> None:
    body = push_body(1)
    hdrs = headers(body)
    resp = await client.post(URL, content=body + b" ", headers=hdrs)
    assert resp.status_code == 401


async def test_unconfigured_secret_is_503(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"github_app_webhook_secret": None})
    body = push_body(1)
    resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 503


async def test_oversize_by_content_length_is_413_without_signature_work(
    client: AsyncClient, parse_spy: list[Any]
) -> None:
    body = b"x" * (MAX_BYTES + 1)
    resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 413
    assert parse_spy == []


async def test_body_at_the_cap_is_not_413(client: AsyncClient) -> None:
    body = b"x" * MAX_BYTES
    resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 400  # signed, but not JSON


async def test_chunked_overflow_is_413(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"y" * (MAX_BYTES // 2)

    hdrs = headers(b"")
    resp = await client.post(URL, content=chunks(), headers=hdrs)
    assert resp.status_code == 413


async def test_malformed_json_after_valid_signature_is_400(client: AsyncClient) -> None:
    body = b"{not json"
    resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 400


async def test_non_object_json_is_400(client: AsyncClient) -> None:
    body = b"[1,2]"
    resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 400


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("X-GitHub-Event", None),
        ("X-GitHub-Event", "Push; DROP"),
        ("X-GitHub-Event", "a" * 65),
        ("X-GitHub-Delivery", None),
        ("X-GitHub-Delivery", "../etc/passwd"),
        ("X-GitHub-Delivery", "d" * 65),
    ],
)
async def test_event_and_delivery_headers_are_required_and_validated(
    client: AsyncClient, name: str, value: str | None
) -> None:
    body = push_body(1)
    hdrs = headers(body)
    if value is None:
        del hdrs[name]
    else:
        hdrs[name] = value
    resp = await client.post(URL, content=body, headers=hdrs)
    assert resp.status_code == 400


async def test_unknown_installation_is_204_with_a_log_line_and_no_work(
    client: AsyncClient, synced: list[uuid.UUID], caplog: pytest.LogCaptureFixture
) -> None:
    body = push_body(424242424)
    with caplog.at_level(logging.INFO):
        resp = await client.post(URL, content=body, headers=headers(body))
    assert resp.status_code == 204
    assert synced == []
    assert any("webhook_dropped" in r.getMessage() for r in caplog.records)


async def test_duplicate_delivery_is_processed_once(
    client: AsyncClient, maker: async_sessionmaker[AsyncSession], synced: list[uuid.UUID]
) -> None:
    async with maker() as db:
        seeded = await seed_team(db)
        inst = await seed_installation(db, seeded)
        source = await seed_installation_source(db, seeded)
        await db.commit()
        ext_id, source_id = inst.external_installation_id, source.id
    body = push_body(ext_id)
    hdrs = headers(body, delivery="dup-delivery-1")

    first = await client.post(URL, content=body, headers=hdrs)
    second = await client.post(URL, content=body, headers=hdrs)

    assert first.status_code == second.status_code == 204
    assert synced == [source_id]


# ------------------------------------------------------------- rate limits (B3)


async def test_a_burst_of_signed_deliveries_all_pass_and_spare_the_shared_write_bucket(
    client: AsyncClient,
) -> None:
    body = b'{"zen":"hi"}'
    statuses = [
        (await client.post(URL, content=body, headers=headers(body, event="ping"))).status_code
        for _ in range(150)
    ]

    assert statuses == [204] * 150
    other = await client.post("/api/v1/webhooks/github", content=b"{}")
    assert other.status_code != 429
    assert other.headers["X-RateLimit-Limit"] == "120"
    assert other.headers["X-RateLimit-Remaining"] == "119"  # not shared with the App webhook


async def test_repeated_bad_signatures_from_one_ip_are_throttled(client: AsyncClient) -> None:
    body = push_body(1)
    bad = {**headers(body), "X-Hub-Signature-256": "sha256=" + "0" * 64}

    statuses = [(await client.post(URL, content=body, headers=bad)).status_code for _ in range(61)]

    assert statuses[:60] == [401] * 60
    assert statuses[60] == 429


async def test_valid_deliveries_are_not_throttled_by_earlier_bad_signatures(
    client: AsyncClient,
) -> None:
    body = push_body(1)
    bad = {**headers(body), "X-Hub-Signature-256": "sha256=" + "0" * 64}
    for _ in range(61):
        await client.post(URL, content=body, headers=bad)

    ping = b'{"zen":"hi"}'
    ok = await client.post(URL, content=ping, headers=headers(ping, event="ping"))

    assert ok.status_code == 204
