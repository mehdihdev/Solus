"""Whole-item geometry pages with a fingerprint of the complete observed body."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.connectors.contracts import ConnectorError

# JSON topology tokens never enter resource URL paths; vendor tokens include + and /.
_TOPOLOGY_ID = re.compile(r"^[A-Za-z0-9_+/-]{1,128}$")


class GeometryPage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    body_id: str = Field(pattern=_TOPOLOGY_ID.pattern)
    collection: Literal["faces", "edges", "vertices"]
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=1, ge=1, le=10)
    expected_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{16}(?::[0-9a-f]{16}){3}$"
    )

    @classmethod
    def from_args(cls, args: dict[str, Any]) -> GeometryPage | None:
        fields = {key: value for key, value in args.items() if key in cls.model_fields}
        if not fields:
            return None
        try:
            page = cls.model_validate(fields)
        except ValidationError:
            raise ConnectorError(
                "config_invalid", "Supply a body id and collection with valid page options"
            ) from None
        if page.offset and not page.expected_fingerprint:
            raise ConnectorError(
                "config_invalid", "Subsequent pages require the first page fingerprint"
            )
        return page

    def select(self, payload: Any) -> dict[str, Any]:
        bodies = _identified(payload.get("bodies") if isinstance(payload, dict) else None)
        selected = next((body for body in bodies if body["id"] == self.body_id), None)
        if selected is None:
            raise ConnectorError("not_found", "The requested body was not found")
        # Validate every observed identity in this body before fingerprinting it.
        for collection in ("faces", "edges", "vertices"):
            if collection in selected:
                _identified(selected[collection])
        if self.collection not in selected:
            raise ConnectorError("not_found", "The requested geometry collection is absent")
        items = selected[self.collection]
        fingerprint = _fingerprint(selected)
        if self.expected_fingerprint is not None and self.expected_fingerprint != fingerprint:
            raise ConnectorError("stale_state", "Geometry changed; restart at the first page")
        if self.offset > len(items):
            raise ConnectorError(
                "config_invalid", "The geometry offset exceeds the collection size"
            )
        count = min(self.limit, len(items) - self.offset)
        while True:
            end = self.offset + count
            result = {
                "body_id": self.body_id,
                "collection": self.collection,
                "total": len(items),
                "offset": self.offset,
                "next_offset": end if end < len(items) else None,
                "fingerprint": fingerprint,
                "items": items[self.offset : end],
            }
            if _contained_size_bound(result) < 3000:
                return result
            if count <= 1:
                raise ConnectorError(
                    "result_too_large", "A whole geometry item exceeds the response limit"
                )
            count -= 1


def _identified(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConnectorError("api_error", "Geometry identities must be a list")
    seen: set[str] = set()
    for item in value:
        identity = item.get("id") if isinstance(item, dict) else None
        if (
            not isinstance(identity, str)
            or not _TOPOLOGY_ID.fullmatch(identity)
            or identity in seen
        ):
            raise ConnectorError("api_error", "Geometry identities are malformed or duplicated")
        seen.add(identity)
    return value


def _fingerprint(body: dict[str, Any]) -> str:
    try:
        canonical = json.dumps(body, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        raise ConnectorError("api_error", "The body contains invalid geometry data") from None
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ":".join(digest[index : index + 16] for index in range(0, 64, 16))


def _contained_size_bound(value: dict[str, Any]) -> int:
    # Prompt containment escapes '<' and may replace any dictionary value with
    # the 12-character JSON string "[REDACTED]". Reserve that much per entry,
    # including nested entries, without coupling connector reads to the agent.
    # Entropic list strings are at least 40 characters, so redaction shrinks them.
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    return len(encoded) + _redaction_reserve(value)


def _redaction_reserve(value: Any) -> int:
    if isinstance(value, dict):
        return 12 * len(value) + sum(_redaction_reserve(item) for item in value.values())
    if isinstance(value, list):
        return sum(_redaction_reserve(item) for item in value)
    return 0
