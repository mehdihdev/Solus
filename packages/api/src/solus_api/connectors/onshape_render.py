"""SOLUSDEV-321 P5 (R104, D4) — one shaded view of a synced Onshape element.

`render_synced_view` is what `OnshapeConnector.render_view` runs for SOL's renderer
(`agent/vision/renderers.py` reaches it through `Capability.RENDER`, never by name):

- **The synced revision.** It renders the entity's own `document_id`, `element_id` and
  `observed_microversion` — the revision the graph was synced at — on the immutable `m/` route,
  never the live workspace, so the picture and the graph's facts describe the same model.
- **Never without a cached document.** The element's collection comes from the element listing the
  sync cached for that revision (`ELEMENTS_KIND`, the sync's own key). Without it the view is
  refused, and nothing is probed.
- **Metered as an agent read.** It runs under its own scoped connector, built as SOL's other
  Onshape reads are: the source's (or its account connection's) account and application,
  `purpose="agent"`, `label="agent_read"`. The existing quota meter therefore refuses it above
  `integration_degrade_ratio`, and at the allowance, before the request leaves the process. A
  connector without a meter or an integration cache is refused outright.
- **No token refresh.** An expired access token is refused with its reason; the source's next sync
  refreshes it. The render path writes no secret.
- **One call per (microversion, element, view, size).** The PNG is kept in the integration cache
  under the account (`SHADED_VIEW_KIND`); a repeat is served from there.
- **Untrusted bytes.** Onshape's answer must be one base64 PNG of at most `MAX_VIEW_BYTES`,
  checked by its magic before it is kept, and again when it is read back.
- **Tracked documents only.** A document the source no longer tracks is `not_found`, the same
  addressing guard every Onshape tool applies.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import (
    EXPORTABLE_COLLECTIONS,
    ONSHAPE_ID_RE,
    OnshapeConnector,
    tracked_document_ids,
)
from solus_api.connectors.registry import ConnectorContext
from solus_api.connectors.runtime import resolve_credentials
from solus_api.connectors.secrets import SecretNotFoundError
from solus_api.models import ConnectionStatus, SourceType
from solus_api.services.connections import account_ref_for, onshape_application_for

if TYPE_CHECKING:
    from solus_api.connectors.secrets import SecretStore
    from solus_api.models import AccountConnection, Source

PROVIDER: Final = "onshape"
#: The sync's own key for an element listing (`OnshapeConnector._payload_key("elements", …)`).
ELEMENTS_KIND: Final = "revision-v3-elements"
SHADED_VIEW_KIND: Final = "shaded-view-v1"
#: A view → Onshape's named view matrix.
VIEW_MATRICES: Final = MappingProxyType(
    {
        "front": "front",
        "back": "back",
        "left": "left",
        "right": "right",
        "top": "top",
        "bottom": "bottom",
        "iso": "isometric",
    }
)
MAX_VIEW_BYTES: Final = 2 * 1024 * 1024
MIN_VIEW_PX: Final = 64
MAX_VIEW_PX: Final = 1024
_PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"


async def shaded_view(
    connector: OnshapeConnector,
    client: httpx.AsyncClient,
    *,
    document_id: str,
    element_id: str,
    microversion: str,
    view: str,
    width: int,
    height: int,
) -> bytes:
    """One shaded view at an immutable microversion (module docstring); `ConnectorError` when it
    is refused or Onshape's answer is not a PNG."""
    for identity in (document_id, element_id, microversion):
        if ONSHAPE_ID_RE.fullmatch(identity) is None:
            raise ConnectorError("config_invalid", "an Onshape view names Onshape ids only")
    matrix = VIEW_MATRICES.get(view)
    sizes_ok = all(MIN_VIEW_PX <= side <= MAX_VIEW_PX for side in (width, height))
    if matrix is None or not sizes_ok:
        raise ConnectorError("config_invalid", "an Onshape view is a named view of bounded size")
    cache, account = connector.mirror_handle()
    # `request` admits a call only through the meter it was built with: no meter, no admission.
    if cache is None or account is None or getattr(connector, "_meter", None) is None:
        raise ConnectorError(
            "unavailable", "Onshape views need the metered, cached connection SOL reads through"
        )
    collection = await _cached_collection(cache, account, document_id, element_id, microversion)

    async def fetch() -> str:
        body = await connector.get_json(
            client,
            f"/api/v6/{collection}/d/{document_id}/m/{microversion}/e/{element_id}/shadedviews",
            what="shaded view",
            params={
                "viewMatrix": matrix,
                "outputWidth": width,
                "outputHeight": height,
                "pixelSize": 0,
                "edges": "show",
            },
        )
        return _png_of(body)

    key = IntegrationCache.payload_key(
        PROVIDER, account, document_id, microversion, SHADED_VIEW_KIND, element_id, view,
        f"{width}x{height}",
    )  # fmt: skip
    fetched = await cache.fetch(key, ttl_seconds=cache.payload_ttl_seconds, fetch=fetch)
    return _decoded_png(fetched.value)


async def render_synced_view(
    *,
    registry: Any,
    source: Source,
    account: AccountConnection | None,
    secret_store: SecretStore,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    target: Mapping[str, Any],
    view: str,
    width: int,
    height: int,
) -> bytes:
    """The shaded view of the element `target` (an entity's attrs) was synced from, under its
    own scoped, metered connector (module docstring). `ConnectorError` when it is refused."""
    document_id, element_id, microversion = _target_ids(target)
    config = source.config if isinstance(source.config, dict) else {}
    if document_id not in tracked_document_ids(config):
        raise ConnectorError("not_found", "That Onshape document is not one this project tracks")
    if account is not None and (
        account.status is not ConnectionStatus.CONNECTED
        or account.provider is not SourceType.ONSHAPE
    ):
        raise ConnectorError("invalid_credentials", "The connected Onshape account is unavailable")
    holder = account if account is not None else source
    if not holder.secret_ref:
        raise ConnectorError("invalid_credentials", "No Onshape credentials are stored")
    connector = registry.create_scoped(
        PROVIDER,
        ConnectorContext(
            project_id=project_id,
            team_id=team_id,
            acting_user_id=source.created_by,
            account_ref=account_ref_for(holder),
            onshape_application=onshape_application_for(holder),
            # ADR-038 §4: SOL's reads are attributed, and past the degrade band deferred, as
            # agent reads.
            purpose="agent",
            label="agent_read",
        ),
    )
    if not isinstance(connector, OnshapeConnector):
        raise ConnectorError("unavailable", "The Onshape connector is not available")
    try:
        credentials = await resolve_credentials(secret_store, holder.secret_ref)
    except SecretNotFoundError:
        raise ConnectorError(
            "invalid_credentials", "The stored Onshape credentials are missing; reconnect it"
        ) from None
    async with connector.http(credentials) as client:
        return await shaded_view(
            connector,
            client,
            document_id=document_id,
            element_id=element_id,
            microversion=microversion,
            view=view,
            width=width,
            height=height,
        )


def _target_ids(target: Mapping[str, Any]) -> tuple[str, str, str]:
    """The synced element an entity names (`document_id`, `element_id`, `observed_microversion`),
    each an Onshape id, or `ConnectorError`."""
    ids = tuple(target.get(key) for key in ("document_id", "element_id", "observed_microversion"))
    if not all(isinstance(value, str) and ONSHAPE_ID_RE.fullmatch(value) for value in ids):
        raise ConnectorError("not_found", "This entity names no synced Onshape element to render")
    return str(ids[0]), str(ids[1]), str(ids[2])


async def _cached_collection(
    cache: IntegrationCache, account: str, document_id: str, element_id: str, microversion: str
) -> str:
    """The element's collection, read from the listing the sync cached for this revision only."""
    entry = await cache.get(
        IntegrationCache.payload_key(PROVIDER, account, document_id, microversion, ELEMENTS_KIND)
    )
    rows = entry.get("value") if isinstance(entry, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, list) and len(row) == 3 and row[0] == element_id:
            collection = EXPORTABLE_COLLECTIONS.get(str(row[1]))
            if collection is not None:
                return collection
    raise ConnectorError(
        "not_found", "No cached revision of this Onshape element to render; sync the source first"
    )


def _png_of(body: Any) -> str:
    """Onshape's answer as the one base64 PNG it must hold, checked; else `ConnectorError`."""
    images = body.get("images") if isinstance(body, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
        raise ConnectorError("api_error", "Onshape returned no single shaded view")
    _decoded_png(images[0])
    return images[0]


def _decoded_png(encoded: Any) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > MAX_VIEW_BYTES * 4 // 3 + 4:
        raise ConnectorError("api_error", "Onshape returned an oversize or malformed view")
    try:
        png = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ConnectorError("api_error", "Onshape returned a view that is not base64") from None
    if len(png) > MAX_VIEW_BYTES or not png.startswith(_PNG_MAGIC):
        raise ConnectorError("api_error", "Onshape returned a view that is not a PNG")
    return png
