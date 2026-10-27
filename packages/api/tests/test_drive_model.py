"""The drive loop's model call (ADR-041 §6 + 2026-10-26 amendment): Anthropic's
computer-use toolset, one action per call, through the ADR-026 gateway (gates,
retry, breaker, debit) — the only place a provider SDK is touched stays
providers.py."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from solus_api.agent.drive.actions import TOOLSET
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration import gateway
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    AnthropicAdapter,
    ToolCallingUnsupportedError,
    ToolUse,
    Usage,
)

MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Place R1"}]}]


def _block(**fields: Any) -> Any:
    """An SDK content block: attribute access plus `model_dump`."""

    def model_dump(*, exclude_none: bool = False) -> dict[str, Any]:
        return {k: v for k, v in fields.items() if not (exclude_none and v is None)}

    return SimpleNamespace(**fields, model_dump=model_dump)


def _fake_client(recorder: dict[str, Any], response: Any) -> type:
    class Messages:
        async def create(self, **kwargs: Any) -> Any:
            recorder["create"] = kwargs
            return response

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            recorder["client"] = kwargs
            self.messages = Messages()

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return Client


def _response(content: list[Any], stop_reason: str = "tool_use") -> Any:
    usage = SimpleNamespace(input_tokens=1200, output_tokens=40, cache_read_input_tokens=1000)
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


async def _adapter() -> AnthropicAdapter:
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, "test-key")
    return AnthropicAdapter(store)


async def test_the_request_is_the_toolset_with_one_action_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder: dict[str, Any] = {}
    response = _response(
        [
            _block(type="thinking", thinking="", signature="sig", caller=None),
            _block(
                type="tool_use",
                id="toolu_1",
                name="left_click",
                input={"coordinate": [4, 5]},
                toolset_name="computer",
                caller=None,
            ),
        ]
    )
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_client(recorder, response))
    adapter = await _adapter()
    events = [
        e
        async for e in adapter.computer_use(
            "claude-opus-5-5",
            system="SYS",
            messages=MESSAGES,
            tools=[TOOLSET],
            max_tokens=4096,
            effort="high",
        )
    ]
    sent = recorder["create"]
    assert sent["model"] == "claude-opus-5-5"
    assert sent["tools"] == [TOOLSET]
    assert sent["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert sent["output_config"] == {"effort": "high"}
    assert sent["system"] == "SYS"
    assert sent["messages"] == MESSAGES
    assert "thinking" not in sent  # always on for Opus 5.5; `disabled` would 400
    assert recorder["client"]["max_retries"] == 0
    assert events[0] == ToolUse(id="toolu_1", name="left_click", args={"coordinate": [4, 5]})
    usage = events[-1]
    assert isinstance(usage, Usage)
    assert (usage.tokens_in, usage.tokens_out, usage.tokens_cached_in) == (1200, 40, 1000)
    # The assistant content replays verbatim — thinking blocks included — minus nulls.
    assert usage.provider_items == (
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "left_click",
            "input": {"coordinate": [4, 5]},
            "toolset_name": "computer",
        },
    )
    assert usage.stop_reason == "tool_use"


async def test_a_tool_use_outside_the_toolset_is_never_proposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder: dict[str, Any] = {}
    response = _response(
        [_block(type="tool_use", id="t", name="bash", input={}, toolset_name=None)]
    )
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_client(recorder, response))
    adapter = await _adapter()
    events = [
        e
        async for e in adapter.computer_use(
            "m", system="S", messages=MESSAGES, tools=[TOOLSET], max_tokens=8, effort="high"
        )
    ]
    assert not [e for e in events if isinstance(e, ToolUse)]


async def test_text_and_refusals_come_back_with_their_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder: dict[str, Any] = {}
    response = _response([_block(type="text", text="Done.", citations=None)], "refusal")
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_client(recorder, response))
    adapter = await _adapter()
    events = [
        e
        async for e in adapter.computer_use(
            "m", system="S", messages=MESSAGES, tools=[TOOLSET], max_tokens=8, effort="high"
        )
    ]
    assert events[0] == "Done."
    assert isinstance(events[-1], Usage) and events[-1].stop_reason == "refusal"


# --- the gateway call -------------------------------------------------------------------


class _FakeAdapter:
    provider = "anthropic"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def computer_use(self, model_name: str, **kwargs: Any) -> Any:
        self.calls.append({"model": model_name, **kwargs})
        yield ToolUse(id="t1", name="screenshot", args={})
        yield Usage(
            tokens_in=10,
            tokens_out=2,
            provider_items=({"type": "tool_use", "id": "t1"},),
            stop_reason="tool_use",
        )


def test_the_catalog_routes_computer_use_to_opus_5_5_at_high_effort() -> None:
    entry = load_orchestration_config().entry_for_role(gateway.COMPUTER_USE_ROLE)
    assert (entry.provider, entry.name, entry.reasoning_effort) == (
        "anthropic",
        "claude-opus-5-5",
        "high",
    )
    assert (entry.price_in, entry.price_out, entry.price_cached_in) == (4.0, 20.0, 0.2)


async def test_gateway_runs_one_computer_use_round() -> None:
    fake = _FakeAdapter()
    completion = await gateway.computer_use(
        system="S",
        messages=MESSAGES,
        tools=[TOOLSET],
        secret_store=InMemorySecretStore(),
        adapters={"anthropic": fake},  # type: ignore[dict-item]
    )
    assert fake.calls[0]["model"] == "claude-opus-5-5"
    assert fake.calls[0]["effort"] == "high"
    assert completion.tool_calls == (ToolUse(id="t1", name="screenshot", args={}),)
    assert completion.provider_items == ({"type": "tool_use", "id": "t1"},)
    assert completion.stop_reason == "tool_use"
    assert completion.model.role == gateway.COMPUTER_USE_ROLE


async def test_gateway_refuses_a_provider_without_computer_use() -> None:
    class TextOnly:
        provider = "anthropic"

    with pytest.raises(ToolCallingUnsupportedError):
        await gateway.computer_use(
            system="S",
            messages=MESSAGES,
            tools=[TOOLSET],
            secret_store=InMemorySecretStore(),
            adapters={"anthropic": TextOnly()},  # type: ignore[dict-item]
        )


async def test_gateway_applies_the_spend_gates_for_an_identified_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def cap(*_a: Any, **_k: Any) -> None:
        seen.append("cap")

    async def spend(*_a: Any, **_k: Any) -> None:
        seen.append("spend")

    async def debit(**_k: Any) -> None:
        seen.append("debit")

    monkeypatch.setattr(gateway, "check_frequency_cap", cap)
    monkeypatch.setattr(gateway, "assert_can_spend", spend)
    monkeypatch.setattr(gateway, "_fire_cost_hook", debit)
    await gateway.computer_use(
        system="S",
        messages=MESSAGES,
        tools=[TOOLSET],
        secret_store=InMemorySecretStore(),
        adapters={"anthropic": _FakeAdapter()},  # type: ignore[dict-item]
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    assert seen == ["cap", "spend", "debit"]
