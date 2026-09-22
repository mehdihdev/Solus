"""Whole assembly feature observations with revision-bound continuation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE
from solus_api.connectors.onshape_circle_geometry import _connector_frame, _poses
from solus_api.connectors.onshape_geometry import _contained_size_bound

_FEATURE_ID = re.compile(r"[A-Za-z0-9_+/-]{1,64}")


def _invalid() -> ConnectorError:
    return ConnectorError(
        "api_error", "Complete revision-bound assembly feature evidence is required"
    )


def _rows(value: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise _invalid()
    result: dict[str, dict[str, Any]] = {}
    for raw in value:
        row = raw.get("message", raw) if isinstance(raw, dict) else None
        identity = row.get(key) if isinstance(row, dict) else None
        if (
            not isinstance(row, dict)
            or not isinstance(identity, str)
            or not _FEATURE_ID.fullmatch(identity)
            or identity in result
        ):
            raise _invalid()
        result[identity] = row
    return result


def _item(
    root: dict[str, Any], feature: dict[str, Any], tree: dict[str, Any], state: Any
) -> dict[str, Any]:
    state = state.get("message", state) if isinstance(state, dict) else None
    kind, suppressed = feature.get("featureType"), feature.get("suppressed")
    if (
        not isinstance(kind, str)
        or not kind
        or type(suppressed) is not bool
        or tree.get("featureType") != kind
        or tree.get("suppressed") is not suppressed
        or not isinstance(tree.get("name"), str)
        or not isinstance(state, dict)
        or not isinstance(state.get("featureStatus"), str)
        or not state["featureStatus"]
        or type(state.get("inactive")) is not bool
    ):
        raise _invalid()
    result = {
        "feature_id": feature["id"],
        "name": tree["name"],
        "type": kind,
        "suppressed": suppressed,
        "health": {"status": state["featureStatus"], "inactive": state["inactive"]},
    }
    if kind == "mate":
        parameters = _rows(tree.get("parameters"), "parameterId")
        mate_type = parameters.get("mateType", {})
        if (
            mate_type.get("enumName") != "Mate type"
            or not isinstance(mate_type.get("value"), str)
            or not mate_type["value"]
        ):
            raise _invalid()
        result["mate_type"] = mate_type["value"]
    if kind == "mateConnector":
        data = feature.get("featureData")
        path = data.get("occurrence") if isinstance(data, dict) else None
        if not isinstance(path, list):
            raise _invalid()
        # The validator requires an active connector; suppressed rows cannot claim a frame.
        if suppressed:
            raise _invalid()
        frame = _connector_frame(root, feature["id"], path, include_basis=True)
        result.update(
            occurrence_path=path,
            world_origin_m=frame["origin"],
            world_axis=frame["axis"],
            world_x_axis=frame["x_axis"],
            world_y_axis=frame["y_axis"],
        )
    return result


def _observations(payload: Any, tree: Any) -> tuple[str, list[dict[str, Any]], Any]:
    # Deferred to avoid assembly_geometry -> operations -> this module during registration.
    from solus_api.connectors.onshape_assembly_geometry import _complete

    _complete(payload)
    _complete(tree)
    root = payload.get("rootAssembly") if isinstance(payload, dict) else None
    _complete(root)
    revision = root.get("documentMicroversion") if isinstance(root, dict) else None
    if (
        not isinstance(root, dict)
        or not isinstance(revision, str)
        or not ONSHAPE_ID_RE.fullmatch(revision)
        or not isinstance(tree, dict)
        or tree.get("sourceMicroversion") != revision
        or tree.get("isComplete") is not True
        or root.get("configuration") != "default"
        or root.get("fullConfiguration", "default") != "default"
        or not isinstance(tree.get("featureStates"), dict)
    ):
        raise _invalid()
    features = _rows(root.get("features"), "id")
    observed = _rows(tree.get("features"), "featureId")
    if features.keys() != observed.keys():
        raise _invalid()
    items = [
        _item(root, feature, observed[key], tree["featureStates"].get(key))
        for key, feature in features.items()
    ]
    poses = [[list(path), transform] for path, transform in sorted(_poses(root).items())]
    return revision, items, poses


class AssemblyFeaturePage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    view: Literal["features"]
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=2, ge=1, le=10)
    expected_snapshot: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{16}(?::[0-9a-f]{16}){3}$"
    )

    @classmethod
    def from_args(cls, args: dict[str, Any]) -> AssemblyFeaturePage | None:
        fields = {key: value for key, value in args.items() if key in cls.model_fields}
        if not fields:
            return None
        try:
            return cls.model_validate(fields)
        except ValidationError:
            raise ConnectorError(
                "config_invalid", "Supply view=features and valid page options"
            ) from None

    def select(self, payload: Any, tree: Any, *, workspace_id: str | None = None) -> dict[str, Any]:
        revision, items, poses = _observations(payload, tree)
        encoded = json.dumps(
            [workspace_id, revision, items, poses], sort_keys=True, allow_nan=False
        )
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        snapshot = ":".join(digest[i : i + 16] for i in range(0, 64, 16))
        if self.offset and not self.expected_snapshot:
            raise ConnectorError("config_invalid", "Continuation requires the first page snapshot")
        if self.expected_snapshot is not None and self.expected_snapshot != snapshot:
            raise ConnectorError("stale_state", "Assembly changed; restart at offset zero")
        if self.offset > len(items):
            raise ConnectorError("config_invalid", "Offset exceeds assembly feature count")
        count = min(self.limit, len(items) - self.offset)
        while True:
            end = self.offset + count
            result = {
                "workspace_id": workspace_id,
                "root_revision": revision,
                "snapshot": snapshot,
                "total": len(items),
                "offset": self.offset,
                "next_offset": end if end < len(items) else None,
                "items": items[self.offset : end],
            }
            if _contained_size_bound(result) < 3000:
                return result
            if count <= 1:
                raise ConnectorError(
                    "result_too_large", "A complete assembly feature exceeds the response limit"
                )
            count -= 1
