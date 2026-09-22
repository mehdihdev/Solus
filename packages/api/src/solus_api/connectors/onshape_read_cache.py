"""Account-isolated immutable Onshape reads, never mutable target observations.

Callers resolve current authorization and verify the donor revision before using
this helper. Only default-configuration responses are admitted; configured donor
responses need an explicitly configuration-bound interface before reuse. The
fetch callback must raise on transport/auth/provider failures, as the connector
transport does. No mutable workspace key, target-state cache or vendor URL is
accepted here.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import ONSHAPE_ID_RE

_MAX_SPEC_BYTES = 8 * 1024 * 1024
_MAX_DONOR_BYTES = 32 * 1024 * 1024


def _snapshot(value: Any, *, max_bytes: int = _MAX_SPEC_BYTES) -> Any:
    if not isinstance(value, (dict, list)):
        raise ValueError("immutable specification must be a JSON object or array")
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("immutable payload exceeds the bounded acquisition size")
    return json.loads(encoded)


class OnshapeReadCache:
    """Reuse immutable default-configuration donor geometry or feature specs."""

    def __init__(self, cache: IntegrationCache, account_ref: str) -> None:
        if (
            not isinstance(account_ref, str)
            or not account_ref.strip()
            or len(account_ref) > 256
            or any(ord(char) < 32 for char in account_ref)
        ):
            raise ValueError("resolved account identity is required")
        self._cache = cache
        self._account_ref = account_ref

    async def fetch(
        self,
        *,
        document_id: str,
        element_id: str,
        revision_kind: Literal["m", "v"],
        revision_id: str,
        kind: Literal["donor_geometry", "feature_spec"],
        fetch: Callable[[], Awaitable[Any]],
        collection: Literal["partstudios", "assemblies"] | None = None,
    ) -> Any:
        if revision_kind not in ("m", "v") or kind not in ("donor_geometry", "feature_spec"):
            raise ValueError("only immutable donor revisions and specifications may be reused")
        if any(
            not isinstance(value, str) or not ONSHAPE_ID_RE.fullmatch(value)
            for value in (document_id, element_id, revision_id)
        ):
            raise ValueError("invalid immutable Onshape resource identity")
        if collection not in (None, "partstudios", "assemblies"):
            raise ValueError("invalid immutable specification collection")
        key = self._cache.payload_key(
            "onshape",
            self._account_ref,
            document_id,
            revision_id,
            "immutable-read-v1",
            revision_kind,
            element_id,
            kind,
            "default-configuration",
            *([collection] if collection else []),
        )

        # Acquisition is bounded independently of cache admission. Large donor
        # geometry remains usable; IntegrationCache still declines storage above
        # its 8 MiB limit. Feature specifications retain their smaller ceiling.
        max_bytes = _MAX_DONOR_BYTES if kind == "donor_geometry" else _MAX_SPEC_BYTES

        async def acquire() -> Any:
            return _snapshot(await fetch(), max_bytes=max_bytes)

        result = await self._cache.fetch(
            key, ttl_seconds=self._cache.payload_ttl_seconds, fetch=acquire
        )
        return _snapshot(result.value, max_bytes=max_bytes)


def validated_feature_specs(body: Any) -> dict[str, Any]:
    """Reject error/partial/malformed tables before any reusable cache entry."""
    if (
        not isinstance(body, dict)
        or body.get("errorEnum") not in (None, "NO_ERROR")
        or any(body.get(key, False) is not False for key in ("incomplete", "isIncomplete"))
        or body.get("isComplete", True) is not True
        or ("libraryVersion" in body and type(body["libraryVersion"]) is not int)
        or not isinstance(body.get("featureSpecs"), list)
    ):
        raise ConnectorError("api_error", "Onshape returned incomplete feature specifications")
    for wrapped in body["featureSpecs"]:
        spec = wrapped.get("message", wrapped) if isinstance(wrapped, dict) else None
        if (
            not isinstance(spec, dict)
            or not isinstance(spec.get("featureType"), str)
            or not spec["featureType"]
        ):
            raise ConnectorError("api_error", "Onshape returned malformed feature specifications")
        _validate_parameter_collection(spec)
    try:
        return cast(dict[str, Any], _snapshot(body))
    except (ValueError, TypeError, OverflowError):
        raise ConnectorError(
            "api_error", "Onshape returned invalid feature specification values"
        ) from None


def _validate_parameter_collection(spec: dict[str, Any]) -> None:
    """Preserve vendor visibility variants; selection still requires unique IDs."""
    from solus_api.connectors.onshape_ops import _parameter_specs_by_id, _read_messages

    if "parameters" not in spec or "parameterIdToSpec" in spec:
        _parameter_specs_by_id(spec)
        return
    for parameter in _read_messages(spec["parameters"]):
        identity = parameter.get("parameterId")
        if not isinstance(identity, str) or not identity:
            raise ConnectorError("api_error", "Onshape returned malformed parameter identities")
