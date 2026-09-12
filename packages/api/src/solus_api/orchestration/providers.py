"""Provider adapters — the ONLY module that may import provider SDKs (ADR-026).

Normalizes Anthropic / OpenAI / Google Gemini behind one streaming interface so
the gateway (`gateway.py`) never cares which provider a `ModelChoice.provider`
names. Provider selection is config-driven: switching the provider that fills a
role is a `models.yaml` edit, not a code change. Model identity always arrives
via the `model_name` argument — never a literal in this file.

API keys are read from the connector-work `SecretStore` at call time, by these
refs (set them in Secrets Manager / the local encrypted store; nothing here
needs a key until a real call is made):

- ``anthropic_api_key``
- ``openai_api_key``
- ``google_api_key``

Transient classification (MO-03): each adapter maps its SDK's rate-limit /
overload / transient-network errors to `ProviderTransientError`, which the
gateway's exponential backoff retries (before the first streamed chunk only).
``max_retries=0`` stays deliberate — SDK silent retries would preempt OUR
policy. Per-provider circuit breakers remain deferred to route-exposure work
(§7); the gateway is still not exposed on any HTTP route. Timeouts (the one
per-call §7 requirement) ARE set on every client.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import time
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NamedTuple, Protocol, Self, cast

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from solus_api.connectors.secrets import SecretNotFoundError, SecretStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

logger = logging.getLogger("solus.orchestration.providers")

# §7: every model call is bounded. Client-level, applies to request + stream read.
DEFAULT_TIMEOUT_SECONDS: float = 120.0
DEFAULT_MAX_TOKENS: int = 4096

# §7: the provider SDKs log their FULL request bodies — including the user's
# prompt — at DEBUG on their own loggers (anthropic/openai _base_client
# "Request options: %s"; google_genai._api_client). Floor them to INFO so an
# operator raising the root level to DEBUG never writes customer IP into logs.
# This module is the one sanctioned SDK surface, so the floor lives here; an
# operator who truly needs SDK wire logs can re-lower these named loggers.
_PROVIDER_SDK_LOGGERS = ("anthropic", "openai", "google_genai")
for _sdk_logger in _PROVIDER_SDK_LOGGERS:
    logging.getLogger(_sdk_logger).setLevel(logging.INFO)

ANTHROPIC_API_KEY_NAME = "anthropic_api_key"
OPENAI_API_KEY_NAME = "openai_api_key"
GOOGLE_API_KEY_NAME = "google_api_key"


class Usage(NamedTuple):
    """The adapter's FINAL report for one model call: token usage (the cost
    hook's input) plus anything opaque the next round must replay.

    `tokens_cached_in` is the cached-prefix subset of `tokens_in` (billed at the
    catalog's `price_cached_in` when set). `provider_items` are provider-native
    output items (e.g. OpenAI Responses reasoning + function_call items) that a
    stateless multi-round loop must send back verbatim on the next round; the
    runner copies them onto the assistant `Turn` and never inspects them.
    """

    tokens_in: int
    tokens_out: int
    tokens_cached_in: int = 0
    provider_items: tuple[dict[str, Any], ...] = ()


class ProviderCredentialsMissingError(RuntimeError):
    """No API key in the SecretStore for the provider being called."""


class UnknownProviderError(KeyError):
    """`ModelChoice.provider` names a provider with no registered adapter."""


class ProviderError(RuntimeError):
    """A provider SDK call failed; carries provider+model context, never the query."""


class ProviderTransientError(ProviderError):
    """A RETRYABLE provider-side failure: 429 rate limit, overload/5xx, or a
    transient network error. The gateway's MO-03 backoff retries exactly these
    (and nothing else), only before the first streamed chunk."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _retry_delay(error: Any, now: float) -> float | None:
    """Read only documented timing fields; never retain response bodies."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    value = headers.get("retry-after")
    delays: list[float] = []
    if value is not None:
        try:
            delay = float(value)
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(value)
                delay = date.replace(tzinfo=date.tzinfo or UTC).timestamp() - now
            except (TypeError, ValueError, OverflowError):
                delay = -1.0
        if math.isfinite(delay) and delay >= 0:
            delays.append(delay)
    google_delay = _google_retry_delay(error)
    if google_delay is not None:
        delays.append(google_delay)
    return max(delays) if delays else None


def _google_retry_delay(error: Any) -> float | None:
    delays: list[float] = []
    body = getattr(error, "details", None)
    if isinstance(body, dict):
        details = body.get("error", body)
        details = details.get("details", []) if isinstance(details, dict) else []
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict) or detail.get("@type") != (
                "type.googleapis.com/google.rpc.RetryInfo"
            ):
                continue
            duration = detail.get("retryDelay")
            if isinstance(duration, str) and duration.endswith("s"):
                try:
                    delay = float(duration[:-1])
                except ValueError:
                    continue
                if math.isfinite(delay) and delay >= 0:
                    delays.append(delay)
    return max(delays) if delays else None


_PERMANENT_CODES: Final = frozenset(
    {
        "insufficient_quota",
        "billing_hard_limit_reached",
        "enforced_spend_limit_reached",
        "model_not_found",
        "invalid_api_key",
        "permission_denied",
    }
)


def normalize_provider_error(
    provider: str,
    model_name: str,
    error: Any,
    *,
    now: float | None = None,
) -> ProviderError:
    """One safe taxonomy for streaming and embeddings across the three SDKs.

    Unknown provider codes are never echoed: response fields can contain secrets.
    Call sites suppress SDK exception chains for the same reason.
    """
    code = getattr(error, "code", None)
    status = getattr(error, "status_code", None)
    if provider == "google":
        status = code
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        body = body.get("error", body)
        if isinstance(body, dict):
            code = body.get("code", code)
            details = body.get("details", {})
            if isinstance(details, dict):
                code = details.get("error_code", code)
    known = (
        code
        if isinstance(code, str) and code in (_PERMANENT_CODES | _OPENAI_TRANSIENT_CODES)
        else "provider_error"
    )
    message = f"{provider} failure for model {model_name}: {type(error).__name__} code={known}"
    # Quota and authorization cannot be repaired by a retry, even with HTTP 429.
    if known in _PERMANENT_CODES or status in (400, 401, 403, 404):
        return ProviderError(message)
    transient = status in (408, 429) or (isinstance(status, int) and 500 <= status <= 599)
    transient = (
        transient
        or known in _OPENAI_TRANSIENT_CODES
        or isinstance(
            error, (httpx.NetworkError, httpx.TimeoutException, httpx.RemoteProtocolError)
        )
        or type(error).__name__
        in (
            "APIConnectionError",
            "APITimeoutError",
            "ConnectError",
            "ReadTimeout",
            "ConnectTimeout",
        )
    )
    if transient:
        return ProviderTransientError(
            message, retry_after_seconds=_retry_delay(error, time.time() if now is None else now)
        )
    return ProviderError(message)


class ToolCallingUnsupportedError(ProviderError):
    """This provider's adapter cannot carry a multi-turn/tool conversation.

    A `ProviderError` (so the gateway's taxonomy classifies it) but NOT a
    `ProviderTransientError` — retrying a structural gap burns the whole budget
    on something that can never succeed. Raised rather than silently dropping
    the tools array: a model that cannot act still TALKS about acting, which is
    indistinguishable from it choosing not to.
    """


class ToolSpec(BaseModel):
    """One tool advertised to the model. Provider-neutral; each adapter maps it
    to its own wire shape. `input_schema` is a `ToolDescriptor.params` verbatim —
    which is why a tool's params are now literally model-facing wire content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolUse(BaseModel):
    """A call the MODEL proposed. Solus code decides whether it runs — this shape
    carries no way to execute itself. `id` is the provider's own tool-use id and
    MUST be echoed on the matching result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    args: dict[str, Any] = {}


class ToolOutcome(BaseModel):
    """The result of one dispatched call, going back to the model as DATA.
    `content` is always a string on the wire; the runner JSON-encodes there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # echoes ToolUse.id
    content: str
    is_error: bool = False


class ImageBlock(BaseModel):
    """Raw image bytes + media type for one vision call (FP-03). Plain pydantic:
    SDK content shapes never leak out of the adapters, and callers never
    base64-encode — each adapter encodes its own provider's way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_type: str  # image/png, image/jpeg, image/webp
    data: bytes


class Turn(BaseModel):
    """One provider-neutral conversation turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "assistant"]
    text: str | None = None
    tool_uses: tuple[ToolUse, ...] = ()  # assistant turns only
    tool_results: tuple[ToolOutcome, ...] = ()  # user turns only
    #: Opaque provider replay items for this assistant turn (`Usage.provider_items`
    #: of the round that produced it). An adapter that emitted them replays them
    #: verbatim instead of re-synthesising the turn; every other adapter ignores
    #: them. Never inspected, never rendered, never persisted to the transcript.
    provider_items: tuple[dict[str, Any], ...] = ()
    #: SOLUSDEV-252 S3 (sol-window.md §8.2): a screenshot the person attached,
    #: riding the LIVE user turn so a reasoner whose adapter carries images in a
    #: conversation sees the evidence. Additive: every text-only turn is unchanged.
    #: Never persisted — the transcript keeps `attrs.screenshot` dims only.
    images: tuple[ImageBlock, ...] = ()

    @model_validator(mode="after")
    def _images_ride_a_plain_user_turn(self) -> Self:
        if self.images and (self.role != "user" or self.tool_results):
            raise ValueError("images ride only on a plain user turn (no tool_results)")
        return self


class ToolConversation(BaseModel):
    """System prompt + multi-turn messages + tools, as ONE optional parameter.

    Bundled rather than three loose kwargs so "the text-only path is untouched"
    stays a single `if conversation is None` branch — the property every existing
    caller depends on.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    messages: tuple[Turn, ...] = ()
    tools: tuple[ToolSpec, ...] = ()


def _b64(image: ImageBlock) -> str:
    return base64.b64encode(image.data).decode("ascii")


def anthropic_content(
    query: str, images: Sequence[ImageBlock] | None
) -> str | list[dict[str, object]]:
    """Anthropic content blocks: images first (base64 source), then the text."""
    if not images:
        return query
    blocks: list[dict[str, object]] = []
    for img in images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type,
                    "data": _b64(img),
                },
            }
        )
    blocks.append({"type": "text", "text": query})
    return blocks


def openai_content(
    query: str, images: Sequence[ImageBlock] | None
) -> str | list[dict[str, object]]:
    """OpenAI Responses input content: data-URL input_image parts, then the text."""
    if not images:
        return query
    blocks: list[dict[str, object]] = [
        {"type": "input_image", "image_url": f"data:{img.media_type};base64,{_b64(img)}"}
        for img in images
    ]
    blocks.append({"type": "input_text", "text": query})
    return blocks


def openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, object]]:
    """Tool specs → Responses API function tools. `strict` stays False: the
    registry's own JSON-Schema validation gates dispatch, and strict mode would
    reject every `ToolDescriptor.params` that is not additionalProperties=false."""
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
            "strict": False,
        }
        for t in tools
    ]


def openai_input(turns: Sequence[Turn]) -> list[dict[str, Any]]:
    """Provider-neutral turns → Responses API input items.

    An assistant turn that carries `provider_items` (the reasoning / message /
    function_call items OpenAI emitted for that round) is replayed VERBATIM —
    that is what keeps encrypted reasoning valid across a stateless (`store=False`)
    multi-round loop. Only a turn without them is synthesised from text + tool
    uses. Tool results become one `function_call_output` each; an error result
    is prefixed so the model sees it as a failure, not data.
    """
    items: list[dict[str, Any]] = []
    for turn in turns:
        if turn.tool_results:
            items.extend(
                {
                    "type": "function_call_output",
                    "call_id": r.id,
                    "output": f"ERROR: {r.content}" if r.is_error else r.content,
                }
                for r in turn.tool_results
            )
        elif turn.role == "assistant" and turn.provider_items:
            items.extend(dict(item) for item in turn.provider_items)
        elif turn.role == "assistant":
            if turn.text:
                items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": turn.text}],
                    }
                )
            items.extend(
                {
                    "type": "function_call",
                    "call_id": u.id,
                    "name": u.name,
                    "arguments": json.dumps(u.args),
                }
                for u in turn.tool_uses
            )
        else:
            # `openai_content` is a bare string when the turn carries no images.
            items.append({"role": "user", "content": openai_content(turn.text or "", turn.images)})
    return items


def openai_tool_use(item: Any) -> ToolUse | None:
    """A completed output item → proposed call, or None for any other item.

    Provider output is UNTRUSTED: a call whose name/call_id are not strings or
    whose arguments are not a JSON object is DROPPED (logged, never raised) —
    args must be a mapping before the registry's JSON-Schema validation can mean
    anything. The log line carries the reason only, never the arguments.
    """
    if getattr(item, "type", None) != "function_call":
        return None
    name = getattr(item, "name", None)
    call_id = getattr(item, "call_id", None)
    raw = getattr(item, "arguments", None)
    if not (isinstance(name, str) and isinstance(call_id, str) and isinstance(raw, str)):
        logger.warning("openai function_call dropped: non-string name/call_id/arguments")
        return None
    try:
        args = json.loads(raw)
    except ValueError:
        logger.warning("openai function_call %r dropped: arguments are not JSON", name)
        return None
    if not isinstance(args, dict):
        logger.warning("openai function_call %r dropped: arguments are not a JSON object", name)
        return None
    return ToolUse(id=call_id, name=name, args=args)


def openai_request(
    model_name: str,
    query: str,
    *,
    max_tokens: int,
    images: Sequence[ImageBlock] | None,
    conversation: ToolConversation | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    """`responses.create` kwargs. No temperature, ever (reasoning models reject
    it). `store=False` always (§7). The text-only path is one user message with
    no instructions and no tools — the contract's "byte-identical" invariant."""
    request: dict[str, Any] = {
        "model": model_name,
        "max_output_tokens": max_tokens,
        "store": False,
        "stream": True,
    }
    if reasoning_effort is not None:
        request["reasoning"] = {"effort": reasoning_effort}
        request["include"] = ["reasoning.encrypted_content"]
    if conversation is None:
        request["input"] = [{"role": "user", "content": openai_content(query, images)}]
    else:
        request["instructions"] = conversation.system
        request["tools"] = openai_tools(conversation.tools)
        request["input"] = openai_input(conversation.messages)
    return request


def _openai_usage(usage: Any, provider_items: Sequence[dict[str, Any]]) -> Usage:
    details = getattr(usage, "input_tokens_details", None)
    return Usage(
        tokens_in=getattr(usage, "input_tokens", 0) or 0,
        tokens_out=getattr(usage, "output_tokens", 0) or 0,
        tokens_cached_in=getattr(details, "cached_tokens", 0) or 0,
        provider_items=tuple(provider_items),
    )


def gemini_contents(query: str, images: Sequence[ImageBlock] | None, types_module: Any) -> object:
    """Gemini contents: Part.from_bytes entries, then the raw query string.
    The SDK types module is injected so this stays testable without the SDK
    (the import-ratchet keeps SDK imports inside the adapters)."""
    if not images:
        return query
    return [
        *(types_module.Part.from_bytes(data=img.data, mime_type=img.media_type) for img in images),
        query,
    ]


def anthropic_tools(tools: Sequence[ToolSpec]) -> list[dict[str, object]]:
    """Tool specs → Anthropic's wire shape. `input_schema` passes straight
    through: `ToolDescriptor.params` is already JSON Schema."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def anthropic_messages(turns: Sequence[Turn]) -> list[dict[str, object]]:
    """Provider-neutral turns → Anthropic messages.

    A plain user turn stays a bare string (identical to the text-only path). An
    assistant turn becomes text + tool_use blocks; a results turn becomes
    tool_result blocks — ALL of a round's results in ONE user turn, because
    splitting them across messages teaches the model to stop making parallel
    calls.

    An assistant turn with no text emits no text block: the API rejects an empty
    one, and a model going straight to a tool call is the common case.
    """
    messages: list[dict[str, object]] = []
    for turn in turns:
        if turn.tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
                        for r in turn.tool_results
                    ],
                }
            )
            continue
        if turn.tool_uses:
            blocks: list[dict[str, object]] = []
            if turn.text:
                blocks.append({"type": "text", "text": turn.text})
            blocks.extend(
                {"type": "tool_use", "id": u.id, "name": u.name, "input": u.args}
                for u in turn.tool_uses
            )
            messages.append({"role": turn.role, "content": blocks})
            continue
        # `anthropic_content` is a bare string when the turn carries no images.
        messages.append(
            {"role": turn.role, "content": anthropic_content(turn.text or "", turn.images)}
        )
    return messages


def anthropic_tool_uses(blocks: Sequence[Any]) -> tuple[ToolUse, ...]:
    """Final-message content blocks → proposed calls.

    Provider output is UNTRUSTED and providers add block types: an unknown block
    is ignored rather than fatal, and a malformed tool_use (non-string name,
    non-mapping input) is DROPPED rather than guessed at — args must be a mapping
    before the registry's JSON-Schema validation can mean anything.
    """
    uses: list[ToolUse] = []
    for block in blocks:
        if getattr(block, "type", None) != "tool_use":
            continue
        name = getattr(block, "name", None)
        identifier = getattr(block, "id", None)
        if not isinstance(name, str) or not isinstance(identifier, str):
            continue
        raw = getattr(block, "input", {})
        if not isinstance(raw, dict):
            continue
        uses.append(ToolUse(id=identifier, name=name, args=dict(raw)))
    return tuple(uses)


def _refuse_conversation(provider: str, conversation: ToolConversation | None) -> None:
    """Adapters that send exactly one user message refuse a conversation OUTRIGHT.

    Not just when tools are present: silently keeping the last turn and dropping
    the rest would lose the conversation without any signal.
    """
    if conversation is not None:
        raise ToolCallingUnsupportedError(
            f"{provider} adapter does not implement tool calling or multi-turn "
            "conversations; route this interaction to a tool-capable provider in models.yaml"
        )


class ProviderAdapter(Protocol):
    """One streaming call surface per provider.

    Contract: yield zero or more ``str`` text chunks, then zero or more
    `ToolUse`, then EXACTLY ONE `Usage`, last, after the provider stream closes.
    On provider failure: raise — never yield a `Usage`. The gateway's
    `complete()` drains this same stream for request-response calls, so both
    paths share one implementation and report identical usage numbers.

    `conversation` is None for the text-only path: the adapter sends exactly one
    user message built from `query`, with no system prompt — byte-identical to
    the pre-tool-calling behaviour every existing caller depends on. When
    supplied, `conversation` IS the request and `query` is used only upstream in
    the gateway, for routing and token estimation.
    """

    def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]: ...


class _BaseAdapter:
    """Shared SecretStore key fetch. Key material goes into the SDK client
    constructor and nowhere else — never logged, never in error messages."""

    provider: ClassVar[str]
    secret_name: ClassVar[str]

    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    async def _api_key(self) -> str:
        try:
            return await self._secret_store.get(self.secret_name)
        except SecretNotFoundError as exc:
            raise ProviderCredentialsMissingError(
                f"No API key for provider {self.provider!r}; set {self.secret_name!r} "
                "in Secrets Manager / SecretStore."
            ) from exc


class AnthropicAdapter(_BaseAdapter):
    provider = "anthropic"
    secret_name = ANTHROPIC_API_KEY_NAME

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,  # ponytail: no thinking mapping yet
    ) -> AsyncIterator[str | ToolUse | Usage]:
        api_key = await self._api_key()
        import anthropic  # lazy: keyless environments never touch provider SDKs

        # max_retries=0 keeps the SDK's silent default retries from preempting
        # the gateway's MO-03 backoff (which retries ProviderTransientError).
        # SDK boundary: plain-dict content blocks are accepted at runtime; the
        # typed overloads want SDK TypedDicts.
        if conversation is None:
            request: dict[str, Any] = {
                "messages": cast(
                    "Any", [{"role": "user", "content": anthropic_content(query, images)}]
                )
            }
        else:
            request = {
                "system": conversation.system,
                "messages": cast("Any", anthropic_messages(conversation.messages)),
                "tools": cast("Any", anthropic_tools(conversation.tools)),
            }

        client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=0
        )
        try:
            async with (
                client,
                client.messages.stream(
                    model=model_name, max_tokens=max_tokens, **request
                ) as stream,
            ):
                # `text_stream` filters to text blocks, so the streaming text path
                # is unchanged when tools are present.
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                # Tool calls arrive assembled: the SDK accumulates input_json_delta
                # internally, so no second non-streaming path is needed. Partial
                # args would be useless anyway — half an argument object cannot
                # be dispatched.
                for use in anthropic_tool_uses(final.content):
                    yield use
                yield Usage(
                    tokens_in=final.usage.input_tokens, tokens_out=final.usage.output_tokens
                )
        except anthropic.APIError as exc:
            raise normalize_provider_error(self.provider, model_name, exc) from None


#: Error codes OpenAI reports INSIDE a stream body (not as an HTTP status), which
#: the SDK surfaces as a bare `APIError`. Retryable ones must reach the gateway's
#: MO-03 backoff; `insufficient_quota` deliberately does NOT (retrying a billing
#: problem burns the budget on something that cannot succeed).
_OPENAI_TRANSIENT_CODES: Final = frozenset(
    {"rate_limit_exceeded", "server_error", "overloaded", "slow_down", "server_is_overloaded"}
)


class OpenAIAdapter(_BaseAdapter):
    """OpenAI on the Responses API (SOLUSDEV-252). Chat Completions is not an
    option: with tools it forces reasoning effort `none`, which the reasoning
    models reject. `store=False` on every call — proprietary designs are never
    retained server-side (§7); `reasoning.encrypted_content` is requested so
    reasoning items replay statelessly via `Usage.provider_items`."""

    provider = "openai"
    secret_name = OPENAI_API_KEY_NAME

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        api_key = await self._api_key()
        import openai  # lazy: keyless environments never touch provider SDKs

        request = openai_request(
            model_name,
            query,
            max_tokens=max_tokens,
            images=images,
            conversation=conversation,
            reasoning_effort=reasoning_effort,
        )
        # max_retries=0 keeps the SDK's silent default retries from preempting
        # the gateway's MO-03 backoff (which retries ProviderTransientError).
        client = openai.AsyncOpenAI(api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=0)
        try:
            async with client:
                events = await client.responses.create(**cast("Any", request))
                state = _OpenAIStreamState(model_name)
                try:
                    async for event in events:
                        text = state.handle(event)
                        if text:
                            yield text
                finally:
                    closer = getattr(events, "close", None) or getattr(events, "aclose", None)
                    if closer is not None:
                        await closer()
                for use in state.uses:
                    yield use
                yield state.final_usage()
        except openai.APIError as exc:
            raise normalize_provider_error(self.provider, model_name, exc) from None


class _OpenAIStreamState:
    """Folds Responses stream events into text deltas, proposed calls, replay
    items and the final usage. One method per event so the adapter's generator
    stays a straight yield loop."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.items: list[dict[str, Any]] = []
        self.uses: list[ToolUse] = []
        self.usage: Usage | None = None

    def handle(self, event: Any) -> str | None:
        kind = event.type
        if kind == "response.output_text.delta":
            return cast("str", event.delta)
        if kind == "response.output_item.done":
            self._item_done(event.item)
        elif kind in ("response.completed", "response.incomplete"):
            # `incomplete` (max_output_tokens hit) is a real, BILLED call with
            # partial output — it terminates normally so the cost hook fires
            # (security review C1); the text is what the model managed to say.
            self.usage = _openai_usage(event.response.usage, self.items)
            if kind == "response.incomplete":
                logger.warning(
                    "openai response incomplete for model %s: %s",
                    self.model_name,
                    _openai_reason(event.response),
                )
        elif kind == "response.failed":
            reason = _openai_reason(event.response)
            error_cls = (
                ProviderTransientError if reason in _OPENAI_TRANSIENT_CODES else ProviderError
            )
            safe_reason = (
                reason
                if reason in (_OPENAI_TRANSIENT_CODES | _PERMANENT_CODES)
                else "provider_error"
            )
            raise error_cls(f"openai {kind} for model {self.model_name}: {safe_reason}")
        return None

    def _item_done(self, item: Any) -> None:
        use = openai_tool_use(item)
        # Every item is kept, in order, for stateless replay — EXCEPT a
        # function_call dropped as malformed: replaying it with no
        # function_call_output would 400 the next round (security review M5).
        if use is not None or getattr(item, "type", None) != "function_call":
            self.items.append(item.model_dump(mode="json", exclude_none=True))
        if use is not None:
            self.uses.append(use)

    def final_usage(self) -> Usage:
        if self.usage is None:
            # The stream ended without a terminal event: a dropped connection or a
            # protocol change. Never report success with zero usage.
            raise ProviderError(
                f"openai stream for model {self.model_name} ended without completion"
            )
        return self.usage


def _openai_reason(response: Any) -> str:
    """Status reason for a failed/incomplete response — a code, never content."""
    error = getattr(response, "error", None)
    if error is not None:
        return str(getattr(error, "code", None) or "error")
    details = getattr(response, "incomplete_details", None)
    return str(getattr(details, "reason", None) or "incomplete")


class GeminiAdapter(_BaseAdapter):
    provider = "google"
    secret_name = GOOGLE_API_KEY_NAME

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,  # ponytail: no thinking mapping yet
    ) -> AsyncIterator[str | ToolUse | Usage]:
        _refuse_conversation(self.provider, conversation)
        api_key = await self._api_key()
        from google import genai  # lazy: keyless environments never touch provider SDKs
        from google.genai import errors as genai_errors
        from google.genai import types

        # Own HTTPX explicitly: Google's optional aiohttp path reconnects once
        # independently of retry_options. The SDK does not close supplied clients.
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as transport:
            # One attempt: Google defaults to five, which would multiply gateway retries.
            # HttpOptions.timeout is milliseconds.
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(DEFAULT_TIMEOUT_SECONDS * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                    httpx_async_client=transport,
                ),
            )
            try:
                contents = gemini_contents(query, images, types)
                response = await client.aio.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(max_output_tokens=max_tokens),
                )
                meta = None
                async for chunk in response:
                    if chunk.text:
                        yield chunk.text
                    if chunk.usage_metadata is not None:
                        meta = chunk.usage_metadata
                yield Usage(
                    tokens_in=(meta.prompt_token_count or 0) if meta else 0,
                    tokens_out=(meta.candidates_token_count or 0) if meta else 0,
                )
            except (genai_errors.APIError, httpx.TransportError) as exc:
                raise normalize_provider_error(self.provider, model_name, exc) from None
            finally:
                await client.aio.aclose()


def build_adapter_registry(secret_store: SecretStore) -> dict[str, ProviderAdapter]:
    """provider string (from `ModelChoice.provider` / models.yaml) → adapter.

    A plain dict IS the registry; dispatch is an explicit lookup, never
    getattr/importlib on config strings (§7).
    """
    # ponytail: adapters build their SDK client per call; cache per-adapter if
    # latency ever matters.
    return {
        AnthropicAdapter.provider: AnthropicAdapter(secret_store),
        OpenAIAdapter.provider: OpenAIAdapter(secret_store),
        GeminiAdapter.provider: GeminiAdapter(secret_store),
    }
