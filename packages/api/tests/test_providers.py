"""Provider adapter layer: registry, SecretStore keys, no-key behavior (MO-01)."""

import base64
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    DEFAULT_TIMEOUT_SECONDS,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
    AnthropicAdapter,
    GeminiAdapter,
    ImageBlock,
    OpenAIAdapter,
    ProviderCredentialsMissingError,
    ProviderError,
    ProviderTransientError,
    ToolOutcome,
    Turn,
    Usage,
    anthropic_content,
    anthropic_messages,
    build_adapter_registry,
    gemini_contents,
    openai_content,
)
from solus_api.orchestration.router import route


def test_registry_covers_all_three_providers() -> None:
    registry = build_adapter_registry(InMemorySecretStore())
    assert set(registry) == {"anthropic", "openai", "google"}
    assert isinstance(registry["anthropic"], AnthropicAdapter)
    assert isinstance(registry["openai"], OpenAIAdapter)
    assert isinstance(registry["google"], GeminiAdapter)


def test_every_shipped_matrix_cell_resolves_to_a_registered_adapter() -> None:
    """Config-driven switchability: whatever provider the shipped yaml names,
    the registry can serve it — no unwired providers behind the matrix."""
    config = load_orchestration_config()
    registry = build_adapter_registry(InMemorySecretStore())
    for complexity in Complexity:
        for route_type in RouteType:
            choice = route("q", complexity, route_type, config=config)
            assert choice.provider in registry, (
                f"matrix[{complexity}][{route_type}] routes to provider "
                f"{choice.provider!r} which has no registered adapter"
            )


@pytest.mark.parametrize("route_type", [RouteType.VISUAL_LOG, RouteType.LONG_CONTEXT])
@pytest.mark.parametrize("complexity", [Complexity.STANDARD, Complexity.HARD])
def test_gemini_routed_roles_resolve_to_google_adapter(
    complexity: Complexity, route_type: RouteType
) -> None:
    """ADR-026 rationale: VISUAL_LOG / LONG_CONTEXT are Gemini-class at
    standard/hard, and the google adapter is wired for them."""
    config = load_orchestration_config()
    registry = build_adapter_registry(InMemorySecretStore())
    choice = route("q", complexity, route_type, config=config)
    assert choice.provider == "google"
    assert isinstance(registry[choice.provider], GeminiAdapter)


@pytest.mark.parametrize(
    ("adapter_cls", "provider", "secret_name"),
    [
        (AnthropicAdapter, "anthropic", ANTHROPIC_API_KEY_NAME),
        (OpenAIAdapter, "openai", OPENAI_API_KEY_NAME),
        (GeminiAdapter, "google", GOOGLE_API_KEY_NAME),
    ],
)
async def test_missing_key_raises_actionable_error(
    adapter_cls: type, provider: str, secret_name: str
) -> None:
    """No key in the SecretStore → a clear, actionable error on a real call.

    Raised before any SDK client is constructed — no network, no SDK needed.
    """
    adapter = adapter_cls(InMemorySecretStore())
    with pytest.raises(ProviderCredentialsMissingError) as excinfo:
        async for _ in adapter.stream("some-model", "hello", max_tokens=16):
            pass  # pragma: no cover - never reached
    message = str(excinfo.value)
    assert provider in message
    assert secret_name in message


def test_secret_names_are_the_documented_ones() -> None:
    assert ANTHROPIC_API_KEY_NAME == "anthropic_api_key"
    assert OPENAI_API_KEY_NAME == "openai_api_key"
    assert GOOGLE_API_KEY_NAME == "google_api_key"


def test_provider_sdk_loggers_are_floored_to_info() -> None:
    """§7 ratchet: the provider SDKs log their full request bodies (the user's
    prompt) at DEBUG on their own loggers; providers.py floors them to INFO so
    an operator root-DEBUG session can never write customer IP into logs."""
    for name in ("anthropic", "openai", "google_genai"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.INFO


def test_usage_is_a_simple_value_type() -> None:
    usage = Usage(tokens_in=10, tokens_out=20)
    assert usage.tokens_in == 10
    assert usage.tokens_out == 20
    assert usage == Usage(10, 20)


# --- SDK-lifecycle regression guards (fake anthropic SDK, zero network) -------
# The cleanup guarantee depends purely on code structure (yields inside the
# async-with blocks); MO-03 rewrites this area for retries/circuit breakers, so
# these keep abandonment cleanup and the no-retry fence under CI signal.


class _FakeAnthropicRecorder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.client_kwargs: dict[str, object] = {}
        self.stream_kwargs: dict[str, object] = {}


def _fake_anthropic_cls(recorder: _FakeAnthropicRecorder) -> type:
    class FakeUsage:
        input_tokens = 7
        output_tokens = 9

    class FakeFinalMessage:
        usage = FakeUsage()
        # Real messages always carry content blocks; the adapter now scans them
        # for tool_use (SOLUS-RUN-01). Empty = a text-only reply.
        content: list[object] = []

    class FakeStreamManager:
        async def __aenter__(self) -> "FakeStreamManager":
            recorder.events.append("stream_enter")
            return self

        async def __aexit__(self, *exc: object) -> bool:
            recorder.events.append("stream_exit")
            return False

        @property
        def text_stream(self) -> AsyncIterator[str]:
            async def chunks() -> AsyncIterator[str]:
                yield "a"
                yield "b"

            return chunks()

        async def get_final_message(self) -> FakeFinalMessage:
            return FakeFinalMessage()

    class FakeMessages:
        def stream(self, **kwargs: object) -> FakeStreamManager:
            recorder.stream_kwargs = dict(kwargs)
            return FakeStreamManager()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            recorder.client_kwargs = dict(kwargs)
            self.messages = FakeMessages()

        async def __aenter__(self) -> "FakeAsyncAnthropic":
            recorder.events.append("client_enter")
            return self

        async def __aexit__(self, *exc: object) -> bool:
            recorder.events.append("client_exit")
            return False

    return FakeAsyncAnthropic


async def _keyed_anthropic_adapter() -> AnthropicAdapter:
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, "test-key")
    return AnthropicAdapter(store)


async def test_anthropic_adapter_full_consumption_reports_sdk_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _FakeAnthropicRecorder()
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_anthropic_cls(recorder))
    adapter = await _keyed_anthropic_adapter()
    events = [event async for event in adapter.stream("some-model", "q", max_tokens=8)]
    assert events == ["a", "b", Usage(tokens_in=7, tokens_out=9)]
    assert recorder.events == ["client_enter", "stream_enter", "stream_exit", "client_exit"]
    # §7 timeout + the MO-01 no-retry fence, enforced functionally:
    assert recorder.client_kwargs["max_retries"] == 0
    assert recorder.client_kwargs["timeout"] == DEFAULT_TIMEOUT_SECONDS


async def test_the_text_only_request_is_unchanged_by_tool_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOLUS-RUN-01's load-bearing invariant: with `conversation=None` the wire
    request is exactly what it was before tool calling existed — one user
    message, NO system prompt, NO tools key. `fingerprint/escalation.py` and
    `visual.py` go down this path and were not edited."""
    recorder = _FakeAnthropicRecorder()
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_anthropic_cls(recorder))
    adapter = await _keyed_anthropic_adapter()

    async for _ in adapter.stream("some-model", "q", max_tokens=8):
        pass

    assert recorder.stream_kwargs["messages"] == [{"role": "user", "content": "q"}]
    assert "system" not in recorder.stream_kwargs
    assert "tools" not in recorder.stream_kwargs


async def test_a_conversation_sends_system_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """...and the tool path sends the system prompt and tool array it must."""
    from solus_api.orchestration.providers import ToolConversation, ToolSpec, Turn

    recorder = _FakeAnthropicRecorder()
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_anthropic_cls(recorder))
    adapter = await _keyed_anthropic_adapter()
    conversation = ToolConversation(
        system="You are SOL.",
        messages=(Turn(role="user", text="what changed?"),),
        tools=(ToolSpec(name="get_entity", description="d", input_schema={"type": "object"}),),
    )

    async for _ in adapter.stream("some-model", "ignored", max_tokens=8, conversation=conversation):
        pass

    assert recorder.stream_kwargs["system"] == "You are SOL."
    assert recorder.stream_kwargs["messages"] == [{"role": "user", "content": "what changed?"}]
    tools = recorder.stream_kwargs["tools"]
    assert isinstance(tools, list)
    assert tools[0]["name"] == "get_entity"


def test_transient_error_is_a_provider_error() -> None:
    assert issubclass(ProviderTransientError, ProviderError)


async def test_anthropic_rate_limit_is_classified_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MO-03: SDK 429/overload surfaces as ProviderTransientError so the
    gateway's backoff can retry it — message carries provider+model, never the
    query (§7)."""
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_error = anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )

    class FakeStreamManager:
        async def __aenter__(self) -> "FakeStreamManager":
            raise sdk_error

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class FakeMessages:
        def stream(self, **kwargs: object) -> FakeStreamManager:
            return FakeStreamManager()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.messages = FakeMessages()

        async def __aenter__(self) -> "FakeAsyncAnthropic":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    adapter = await _keyed_anthropic_adapter()
    with pytest.raises(ProviderTransientError) as excinfo:
        async for _ in adapter.stream("some-model", "secret query text", max_tokens=8):
            pass
    message = str(excinfo.value)
    assert "anthropic" in message
    assert "some-model" in message
    assert "secret query text" not in message  # §7: never the query


async def test_anthropic_adapter_closes_sdk_client_when_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _FakeAnthropicRecorder()
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_anthropic_cls(recorder))
    adapter = await _keyed_anthropic_adapter()
    agen = adapter.stream("some-model", "q", max_tokens=8)
    assert isinstance(agen, AsyncGenerator)
    assert await anext(agen) == "a"
    await agen.aclose()  # abandon mid-stream
    assert "stream_exit" in recorder.events
    assert "client_exit" in recorder.events


# --- FP-03 image blocks: content shapes + bare-string regression ---------------------


def _image() -> ImageBlock:
    return ImageBlock(media_type="image/png", data=b"\x89PNG\r\n\x1a\nfakebytes")


def test_anthropic_content_bare_string_without_images() -> None:
    assert anthropic_content("extract markings", None) == "extract markings"
    assert anthropic_content("extract markings", []) == "extract markings"


def test_anthropic_content_image_blocks_shape() -> None:
    content = anthropic_content("extract markings", [_image()])
    assert isinstance(content, list)
    image_block, text_block = content
    assert image_block["type"] == "image"
    source = image_block["source"]
    assert isinstance(source, dict)
    assert source["type"] == "base64"
    assert source["media_type"] == "image/png"
    assert base64.b64decode(str(source["data"])) == _image().data
    assert text_block == {"type": "text", "text": "extract markings"}


def test_openai_content_bare_string_without_images() -> None:
    assert openai_content("extract markings", None) == "extract markings"


def test_openai_content_data_url_shape() -> None:
    content = openai_content("extract markings", [_image()])
    assert isinstance(content, list)
    image_block, text_block = content
    # Responses API input shape: image_url is a bare data-URL string.
    assert image_block["type"] == "input_image"
    url = str(image_block["image_url"])
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == _image().data
    assert text_block == {"type": "input_text", "text": "extract markings"}


def test_image_block_is_frozen_and_strict() -> None:
    image = _image()
    with pytest.raises(ValidationError):
        ImageBlock.model_validate({"media_type": "image/png", "data": b"x", "extra": "no"})
    with pytest.raises(ValidationError):
        image.media_type = "image/jpeg"


def test_gemini_contents_bare_string_without_images() -> None:
    types_stub = SimpleNamespace(Part=SimpleNamespace(from_bytes=lambda **kw: kw))
    assert gemini_contents("extract markings", None, types_stub) == "extract markings"


def test_gemini_contents_parts_shape() -> None:
    """The one provider VISUAL_LOG actually routes to: Part.from_bytes entries
    first, raw query string last."""
    recorded: list[dict[str, object]] = []

    def from_bytes(**kwargs: object) -> dict[str, object]:
        recorded.append(kwargs)
        return kwargs

    types_stub = SimpleNamespace(Part=SimpleNamespace(from_bytes=from_bytes))
    contents = gemini_contents("extract markings", [_image()], types_stub)
    assert isinstance(contents, list)
    assert contents[-1] == "extract markings"
    assert recorded == [{"data": _image().data, "mime_type": "image/png"}]


# --- Turn.images (SOLUSDEV-252 S3, sol-window.md §8.2) ---------------------------


def test_a_user_turn_with_images_becomes_image_then_text_blocks() -> None:
    [message] = anthropic_messages([Turn(role="user", text="what is this?", images=(_image(),))])
    assert message["role"] == "user"
    content = message["content"]
    assert isinstance(content, list)
    image_block, text_block = content
    assert image_block["type"] == "image"
    source = image_block["source"]
    assert isinstance(source, dict)
    assert source["media_type"] == "image/png"
    assert base64.b64decode(str(source["data"])) == _image().data
    assert text_block == {"type": "text", "text": "what is this?"}


def test_a_text_only_turn_is_unchanged_by_the_images_field() -> None:
    assert anthropic_messages([Turn(role="user", text="hi")]) == [{"role": "user", "content": "hi"}]


def test_images_ride_only_on_a_plain_user_turn() -> None:
    with pytest.raises(ValidationError):
        Turn(role="assistant", text="x", images=(_image(),))
    with pytest.raises(ValidationError):
        Turn(role="user", tool_results=(ToolOutcome(id="1", content="x"),), images=(_image(),))


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
@pytest.mark.parametrize("header", ["9", "Thu, 01 Jan 1970 00:16:49 GMT"])
def test_provider_retry_metadata_is_safe_and_honors_headers(provider: str, header: str) -> None:
    import httpx
    from solus_api.orchestration import providers

    error = SimpleNamespace(
        status_code=429,
        code=429 if provider == "google" else "rate_limit_exceeded",
        response=httpx.Response(429, headers={"retry-after": header}),
        body={"message": "private prompt and key"},
        details={},
    )
    normalized = providers.normalize_provider_error(provider, "model", error, now=1000.0)
    assert isinstance(normalized, ProviderTransientError)
    assert normalized.retry_after_seconds == 9.0
    assert "private" not in str(normalized)


@pytest.mark.parametrize("code", ["insufficient_quota", "billing_hard_limit_reached"])
def test_openai_quota_429_is_permanent(code: str) -> None:
    from solus_api.orchestration import providers

    error = SimpleNamespace(status_code=429, code=code, body={"code": code})
    normalized = providers.normalize_provider_error("openai", "model", error)
    assert isinstance(normalized, ProviderError)
    assert not isinstance(normalized, ProviderTransientError)


@pytest.mark.parametrize("code", ["slow_down", "server_is_overloaded"])
def test_openai_in_stream_overload_codes_are_transient(code: str) -> None:
    from solus_api.orchestration import providers

    normalized = providers.normalize_provider_error("openai", "model", SimpleNamespace(code=code))
    assert isinstance(normalized, ProviderTransientError)


def test_google_retry_info_is_honored() -> None:
    from google.genai.errors import ClientError
    from solus_api.orchestration import providers

    error = ClientError(
        429,
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12.5s"}
                ],
            }
        },
    )
    normalized = providers.normalize_provider_error("google", "model", error)
    assert isinstance(normalized, ProviderTransientError)
    assert normalized.retry_after_seconds == 12.5


def test_anthropic_monthly_spend_limit_is_permanent() -> None:
    from solus_api.orchestration import providers

    error = SimpleNamespace(
        status_code=429,
        body={
            "error": {
                "type": "rate_limit_error",
                "details": {"error_code": "enforced_spend_limit_reached"},
            }
        },
    )
    assert not isinstance(
        providers.normalize_provider_error("anthropic", "model", error), ProviderTransientError
    )


@pytest.mark.parametrize("header", ["garbage", "nan", "inf", "-2"])
def test_invalid_retry_headers_fall_back(header: str) -> None:
    import httpx
    from solus_api.orchestration import providers

    error = SimpleNamespace(
        status_code=429, response=httpx.Response(429, headers={"retry-after": header})
    )
    normalized = providers.normalize_provider_error("openai", "m", error)
    assert isinstance(normalized, ProviderTransientError)
    assert normalized.retry_after_seconds is None


async def test_gemini_disables_sdk_retries_and_masks_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.genai import errors, types

    options: list[types.HttpOptions] = []
    closed: list[bool] = []

    async def generate(**kwargs: object) -> None:
        raise errors.ClientError(403, {"error": {"message": "private prompt"}})

    async def close() -> None:
        closed.append(True)

    def client(**kwargs: object) -> SimpleNamespace:
        option = kwargs["http_options"]
        assert isinstance(option, types.HttpOptions)
        options.append(option)
        return SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content_stream=generate), aclose=close
            )
        )

    monkeypatch.setattr("google.genai.Client", client)
    store = InMemorySecretStore()
    await store.put(GOOGLE_API_KEY_NAME, "test")
    with pytest.raises(ProviderError) as error:
        async for _ in GeminiAdapter(store).stream("m", "q", max_tokens=8):
            pass
    assert not isinstance(error.value, ProviderTransientError)
    assert error.value.__suppress_context__ and error.value.__cause__ is None
    assert "private" not in str(error.value)
    assert options[0].retry_options is not None
    assert options[0].retry_options.attempts == 1
    assert closed == [True]


@pytest.mark.parametrize("kind", ["ReadTimeout", "ConnectError", "RemoteProtocolError"])
async def test_gemini_transport_failure_is_safe_and_closes_owned_client(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    import httpx
    from google.genai import types

    options: list[types.HttpOptions] = []
    closed: list[bool] = []

    async def generate(**kwargs: object) -> None:
        error_cls = getattr(httpx, kind)
        raise error_cls("private prompt and credential")

    async def close() -> None:
        closed.append(True)

    def client(**kwargs: object) -> SimpleNamespace:
        option = kwargs["http_options"]
        assert isinstance(option, types.HttpOptions)
        options.append(option)
        return SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content_stream=generate),
                aclose=close,
            )
        )

    monkeypatch.setattr("google.genai.Client", client)
    store = InMemorySecretStore()
    await store.put(GOOGLE_API_KEY_NAME, "test")
    with pytest.raises(ProviderTransientError) as error:
        async for _ in GeminiAdapter(store).stream("m", "q", max_tokens=8):
            pass
    assert "private" not in str(error.value)
    assert error.value.__suppress_context__ and error.value.__cause__ is None
    transport = options[0].httpx_async_client
    assert isinstance(transport, httpx.AsyncClient)
    assert transport.is_closed
    assert closed == [True]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_gemini_sdk_transport_failure_sends_once(
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    import asyncio

    import httpx
    from google import genai  # load the real SDK before substituting our transport

    calls = 0

    async def send(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if cancelled:
            raise asyncio.CancelledError
        raise httpx.ReadTimeout("private transport data", request=request)

    transport = httpx.AsyncClient(transport=httpx.MockTransport(send))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: transport)
    assert genai.Client is not None
    store = InMemorySecretStore()
    await store.put(GOOGLE_API_KEY_NAME, "test")
    with pytest.raises(asyncio.CancelledError if cancelled else ProviderTransientError):
        async for _ in GeminiAdapter(store).stream("m", "q", max_tokens=8):
            pass
    assert calls == 1
    assert transport.is_closed
