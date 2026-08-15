"""MO-04 classify endpoint: preview-doesn't-lie, viability options, no side effects."""

from typing import Any

import pytest
from httpx import AsyncClient
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import CreditLedger, CreditTxnType
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.gateway import complete
from solus_api.orchestration.type_estimator import AttachmentHint
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class MockAdapter:
    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: object = None,
        conversation: object = None,
    ) -> Any:
        yield "ok"
        from solus_api.orchestration.providers import Usage

        yield Usage(tokens_in=1, tokens_out=1)


def _mock_registry() -> dict[str, Any]:
    return {name: MockAdapter() for name in ("anthropic", "openai", "google")}


async def test_classify_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/orchestration/classify", json={"query": "hi"})
    assert resp.status_code == 401


async def test_classify_returns_the_routing_decision(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={"query": "why is my SLAM drifting when the robot turns"},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["complexity"] == "hard"  # two diagnostic hits (MO-02 fixture behavior)
    assert data["type"] == "general"
    assert data["model"]["name"]
    assert data["model"]["provider"]
    assert data["source"] == {"complexity": "estimator", "type": "estimator"}
    assert data["cost_tier"] in {"low", "standard", "premium"}
    assert isinstance(data["tokens_estimate"], int)
    assert data["viable"] is True
    tier_values = [option["value"] for option in data["options"]["complexities"]]
    assert tier_values == [c.value for c in Complexity]
    type_values = [option["value"] for option in data["options"]["types"]]
    assert type_values == [t.value for t in RouteType]


async def test_classify_rejects_unknown_fields(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={"query": "hi", "model": "gpt-99"},  # raw model picking is not a thing
        headers=alice_headers,
    )
    assert resp.status_code == 422


_MATRIX: list[dict[str, Any]] = [
    {"query": "why is my SLAM drifting when the robot turns"},  # estimator × estimator
    {"query": "hi", "context": "sol_open_question"},  # context × context
    {"query": "hi", "complexity": "hard", "type": "code"},  # explicit × explicit
    {"query": "fix this traceback from my ROS node"},  # type estimator -> CODE
    {"query": "hi", "type": "visual_log"},  # explicit type only
    {  # measured size -> LONG_CONTEXT via the estimator; also exercises attachments
        "query": "please summarize the attached build output and list the failing steps",
        "attachments": [{"kind": "file", "tokens": 250_000}],
    },
]


@pytest.mark.parametrize("payload", _MATRIX, ids=[str(i) for i in range(len(_MATRIX))])
async def test_preview_does_not_lie(
    client: AsyncClient, alice_headers: dict[str, str], payload: dict[str, Any]
) -> None:
    """THE invariant: classify(x) == the ModelChoice complete(x) would use.
    Both run the same resolve_routing + route(), so this must hold exactly."""
    resp = await client.post("/api/v1/orchestration/classify", json=payload, headers=alice_headers)
    assert resp.status_code == 200, resp.text
    preview = resp.json()["data"]

    result = await complete(
        payload["query"],
        secret_store=InMemorySecretStore(),
        complexity=Complexity(payload["complexity"]) if "complexity" in payload else None,
        context=InteractionContext(payload["context"]) if "context" in payload else None,
        type=RouteType(payload["type"]) if "type" in payload else None,
        attachments=tuple(
            AttachmentHint(kind=a["kind"], tokens=a["tokens"])
            for a in payload.get("attachments", [])
        ),
        adapters=_mock_registry(),
    )
    assert preview["model"]["name"] == result.model.model_name
    assert preview["model"]["provider"] == result.model.provider
    assert preview["complexity"] == result.model.complexity.value
    assert preview["type"] == result.model.route_type.value


async def test_classify_has_no_side_effects(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """No provider call (no keys exist anywhere), no debit, no spend — repeated
    classifies never write a USAGE row. (First login DOES grant trial credits —
    SOLUSDEV-83 — so the ledger is not empty; what must stay at zero is spend.)"""
    for _ in range(5):
        resp = await client.post(
            "/api/v1/orchestration/classify",
            json={"query": "why does init_pwm() crash"},
            headers=alice_headers,
        )
        assert resp.status_code == 200
    usage_rows = await db.scalar(
        select(func.count())
        .select_from(CreditLedger)
        .where(CreditLedger.type == CreditTxnType.USAGE)
    )
    assert usage_rows == 0


async def test_classify_is_fast_on_a_max_length_adversarial_query(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Security C1 regression at the HTTP boundary: the schema-cap-sized
    all-word-char query (the old quadratic shape) must classify quickly —
    the shared resolver runs ~8x per request."""
    import time

    payload = {"query": "a" * 1_000_000}
    start = time.perf_counter()
    resp = await client.post("/api/v1/orchestration/classify", json=payload, headers=alice_headers)
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert resp.json()["data"]["type"] == "long_context"  # size rule decided
    assert elapsed < 2.0


async def test_classify_rejects_absurd_attachment_token_hints(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={"query": "hi", "attachments": [{"kind": "file", "tokens": 10_000_001}]},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_classify_marks_nonviable_downgrades_with_reason(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The tiny-downgrade-message contract: an option whose model can't hold the
    request is viable=false with a short factual reason."""
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={
            # 14 words -> STANDARD; explicit GENERAL type; 250K attached tokens.
            "query": "please summarize the attached build output and list the "
            "failing steps in order now",
            "type": "general",
            "attachments": [{"kind": "file", "tokens": 250_000}],
        },
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["viable"] is True  # standard × general -> 1M-window model fits
    by_value = {o["value"]: o for o in data["options"]["complexities"]}
    trivial = by_value["trivial"]  # 200K-window model cannot hold 250K tokens
    assert trivial["viable"] is False
    assert trivial["reason"] is not None
    assert "Too many tokens for this tier" in trivial["reason"]
    assert by_value["standard"]["viable"] is True
    assert by_value["hard"]["viable"] is True
