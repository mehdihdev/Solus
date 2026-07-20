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
import logging
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, Protocol, cast

from pydantic import BaseModel, ConfigDict

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
    """Final token usage for one model call (the cost hook's input)."""

    tokens_in: int
    tokens_out: int


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


class ImageBlock(BaseModel):
    """Raw image bytes + media type for one vision call (FP-03). Plain pydantic:
    SDK content shapes never leak out of the adapters, and callers never
    base64-encode — each adapter encodes its own provider's way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_type: str  # image/png, image/jpeg, image/webp
    data: bytes


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
    """OpenAI content blocks: data-URL image_url entries, then the text."""
    if not images:
        return query
    blocks: list[dict[str, object]] = []
    for img in images:
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img.media_type};base64,{_b64(img)}"},
            }
        )
    blocks.append({"type": "text", "text": query})
    return blocks


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


class ProviderAdapter(Protocol):
    """One streaming call surface per provider.

    Contract: yield zero or more ``str`` text chunks, then EXACTLY ONE `Usage`,
    last, after the provider stream closes. On provider failure: raise — never
    yield a `Usage`. The gateway's `complete()` drains this same stream for
    request-response calls, so both paths share one implementation and report
    identical usage numbers.
    """

    def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
    ) -> AsyncIterator[str | Usage]: ...


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
    ) -> AsyncIterator[str | Usage]:
        api_key = await self._api_key()
        import anthropic  # lazy: keyless environments never touch provider SDKs

        content = anthropic_content(query, images)

        # max_retries=0 keeps the SDK's silent default retries from preempting
        # the gateway's MO-03 backoff (which retries ProviderTransientError).
        client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=0
        )
        try:
            async with (
                client,
                client.messages.stream(
                    model=model_name,
                    max_tokens=max_tokens,
                    # SDK boundary: plain-dict content blocks are accepted at
                    # runtime; the typed overloads want SDK TypedDicts.
                    messages=cast("Any", [{"role": "user", "content": content}]),
                ) as stream,
            ):
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                yield Usage(
                    tokens_in=final.usage.input_tokens, tokens_out=final.usage.output_tokens
                )
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,  # includes APITimeoutError
        ) as exc:
            raise ProviderTransientError(
                f"anthropic transient failure for model {model_name}: {type(exc).__name__}"
            ) from exc


class OpenAIAdapter(_BaseAdapter):
    provider = "openai"
    secret_name = OPENAI_API_KEY_NAME

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
    ) -> AsyncIterator[str | Usage]:
        api_key = await self._api_key()
        import openai  # lazy: keyless environments never touch provider SDKs

        content = openai_content(query, images)

        # max_retries=0 keeps the SDK's silent default retries from preempting
        # the gateway's MO-03 backoff (which retries ProviderTransientError).
        client = openai.AsyncOpenAI(api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=0)
        try:
            async with client:
                response = await client.chat.completions.create(
                    model=model_name,
                    max_completion_tokens=max_tokens,
                    messages=cast("Any", [{"role": "user", "content": content}]),
                    stream=True,
                    stream_options={"include_usage": True},
                )
                usage = Usage(tokens_in=0, tokens_out=0)
                async for chunk in response:
                    if chunk.choices:
                        delta_text = chunk.choices[0].delta.content
                        if delta_text:
                            yield delta_text
                    if chunk.usage is not None:  # final chunk (empty choices) carries usage
                        usage = Usage(
                            tokens_in=chunk.usage.prompt_tokens,
                            tokens_out=chunk.usage.completion_tokens,
                        )
                yield usage
        except (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APIConnectionError,  # includes APITimeoutError
        ) as exc:
            raise ProviderTransientError(
                f"openai transient failure for model {model_name}: {type(exc).__name__}"
            ) from exc


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
    ) -> AsyncIterator[str | Usage]:
        api_key = await self._api_key()
        from google import genai  # lazy: keyless environments never touch provider SDKs
        from google.genai import errors as genai_errors
        from google.genai import types

        # google-genai does not auto-retry (nothing to pin to 0); the gateway's
        # MO-03 backoff retries ProviderTransientError. HttpOptions.timeout is
        # MILLISECONDS.
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(DEFAULT_TIMEOUT_SECONDS * 1000)),
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
        except genai_errors.APIError as exc:
            if getattr(exc, "code", None) == 429 or isinstance(exc, genai_errors.ServerError):
                raise ProviderTransientError(
                    f"google transient failure for model {model_name}: {type(exc).__name__}"
                ) from exc
            raise
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
