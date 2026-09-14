"""Account/page-isolated I1 cache for optional connector tree navigation."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.connectors.contracts import Connector, ConnectorError, Credentials
from solus_api.connectors.integration_cache import Fetched, IntegrationCache
from solus_api.connectors.runtime import call_with_refresh, resolve_credentials
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError


class _TreeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["folder", "document"]
    node: str | None

    @model_validator(mode="after")
    def navigation_matches_kind(self) -> Self:
        if (self.kind == "folder" and not self.node) or (
            self.kind == "document" and self.node is not None
        ):
            raise ValueError("Invalid tree item navigation")
        return self


class _TreePage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[_TreeItem]
    next_offset: int | None = Field(ge=0, le=100000)


def _validated_page(value: Any, node: str, offset: int) -> dict[str, Any]:
    try:
        page = _TreePage.model_validate(value)
        if page.next_offset is not None and (node == "root" or page.next_offset <= offset):
            raise ValueError("Invalid tree page offset")
    except (ValidationError, ValueError) as exc:
        raise APIError(502, "api_error", "Document listing is invalid; reload this folder") from exc
    return page.model_dump()


async def _cached_page(
    cache: IntegrationCache, key: str, node: str, offset: int
) -> Fetched[dict[str, Any]]:
    entry = await cache.get(key)
    if isinstance(entry, dict) and isinstance(entry.get("fetched_at"), str):
        try:
            datetime.fromisoformat(entry["fetched_at"])
            value = _validated_page(entry.get("value"), node, offset)
        except (ValueError, APIError):
            await cache.invalidate(key)
        else:
            return Fetched(value, True, entry["fetched_at"])
    raise APIError(409, "listing_not_cached", "Load this folder to populate its listing")


async def document_tree(
    cache: IntegrationCache,
    *,
    connector: Connector,
    secret_store: SecretStore,
    secret_ref: str,
    provider: str,
    account_ref: str,
    node: str,
    offset: int,
    refresh: bool,
    cache_only: bool,
) -> Fetched[dict[str, Any]]:
    lister: Callable[[Credentials, str, int], Awaitable[dict[str, Any]]] | None = getattr(
        connector, "list_document_tree", None
    )
    if lister is None or not getattr(connector, "supports_document_tree", False):
        raise APIError(400, "unsupported", "This provider does not support document folders")
    key = cache.payload_key(provider, account_ref, node, str(offset), "document-tree")
    if cache_only:
        return await _cached_page(cache, key, node, offset)

    async def fetch() -> dict[str, Any]:
        credentials = await resolve_credentials(secret_store, secret_ref)

        async def run(creds: Credentials) -> dict[str, Any]:
            return _validated_page(await lister(creds, node, offset), node, offset)

        try:
            return await call_with_refresh(
                connector=connector,
                credentials=credentials,
                secret_store=secret_store,
                secret_ref=secret_ref,
                run=run,
            )
        except ConnectorError as exc:
            raise APIError(502, exc.code, exc.message) from exc

    fetched = await cache.fetch(
        key,
        ttl_seconds=cache.listing_ttl_seconds,
        fetch=fetch,
        refresh=refresh,
        min_age_seconds=cache.listing_refresh_cooldown_seconds,
    )
    try:
        value = _validated_page(fetched.value, node, offset)
    except APIError:
        await cache.invalidate(key)
        raise
    return Fetched(value, fetched.cached, fetched.fetched_at)
