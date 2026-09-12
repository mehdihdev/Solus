"""MO-04 classify endpoint: preview-doesn't-lie, viability options, no side effects."""

import json
import re
from typing import Any

import pytest
from httpx import AsyncClient
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import CreditLedger, CreditTxnType
from solus_api.orchestration import SOL_REASONER_NAME, bump_complexity
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.gateway import complete, default_orchestration_config
from solus_api.orchestration.router import route
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
        **_: Any,
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
    assert data["reasoner"] == {"name": SOL_REASONER_NAME, "effort": "deep"}
    assert "model" not in data
    assert all("model" not in o for axis in data["options"].values() for o in axis)
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
    # S1: the preview names the PRODUCT reasoner, never a model; (complexity,
    # type) fully determine the model via the same deterministic route().
    assert preview["reasoner"]["name"] == SOL_REASONER_NAME
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
    request is viable=false with a short factual reason. Catalog-agnostic: the
    attachment is sized just past the SMALLEST general-type window."""
    config = default_orchestration_config()
    windows = {
        tier: route("", tier, RouteType.GENERAL, config=config).context_window
        for tier in Complexity
    }
    smallest = min(windows.values())
    if smallest == max(windows.values()):
        pytest.skip("every tier shares one window — nothing can be non-viable")
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={
            "query": "please summarize the attached build output and list the "
            "failing steps in order now",
            "type": "general",
            "attachments": [{"kind": "file", "tokens": smallest + 1}],
        },
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["viable"] is True  # system-routed: escalates to a tier that fits
    by_value = {o["value"]: o for o in data["options"]["complexities"]}
    for tier, window in windows.items():
        option = by_value[tier.value]
        if window == smallest:
            assert option["viable"] is False
            assert option["reason"] is not None
            assert "Too many tokens for this tier" in option["reason"]
        else:
            assert option["viable"] is True


_MODEL_NAME = re.compile(r"(claude|gemini)-[\w.-]*\d|gpt-\d")


async def test_classify_never_leaks_a_model_name(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """S1-W3: model identity lives ONLY in models.yaml — the preview shows the
    product reasoner + an effort label, at every depth of the JSON."""
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={"query": "why is my SLAM drifting when the robot turns"},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    assert _MODEL_NAME.search(json.dumps(resp.json())) is None


def test_bump_complexity_is_one_tier_and_capped() -> None:
    assert bump_complexity(Complexity.TRIVIAL) is Complexity.STANDARD
    assert bump_complexity(Complexity.STANDARD) is Complexity.HARD
    assert bump_complexity(Complexity.HARD) is Complexity.HARD


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"query": "hi"}, "standard"),  # estimator TRIVIAL -> bumped one tier
        ({"query": "hi", "complexity": "trivial"}, "standard"),  # explicit pick bumped
        ({"query": "why is my SLAM drifting when the robot turns"}, "hard"),  # HARD stays
    ],
)
async def test_think_harder_bumps_the_preview_one_tier(
    client: AsyncClient, alice_headers: dict[str, str], payload: dict[str, Any], expected: str
) -> None:
    resp = await client.post(
        "/api/v1/orchestration/classify",
        json={**payload, "think_harder": True},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["complexity"] == expected
    assert data["source"]["complexity"] == "explicit"
    assert data["reasoner"]["effort"] == {"standard": "standard", "hard": "deep"}[expected]
