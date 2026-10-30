"""Whole assembly feature observations with revision-bound continuation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE
from solus_api.connectors.onshape_circle_geometry import _connector_frame, _poses
from solus_api.connectors.onshape_geometry import _contained_size_bound

_FEATURE_ID = re.compile(r"[A-Za-z0-9_+/-]{1,64}")
#: Onshape's own mate-type enum; anything else in `featureData.mateType` is untrusted text.
_MATE_TYPE = re.compile(r"[A-Z_]{1,32}")


@dataclass(frozen=True)
class MateRecord:
    """One mate feature of an assembly definition between two occurrence paths.

    Paths are instance NAMES joined by `/`, with Onshape's ` <n>` instance suffix spelled
    the way the STEP export spells repeated occurrences (`Peg <2>` → `Peg[1]`, `<1>` bare);
    `mechanical.build_mechanical_graph` resolves them against the exported node keys.
    """

    a_occurrence: str
    b_occurrence: str
    mate_type: str
    feature_id: str


def _instance_segment(name: Any) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    # `Peg <2>` → base `Peg`, index 2. A linear rpartition, not a regex: instance names are
    # user text of unbounded length and a backtracking match would stall the sync worker.
    text: str = name.strip()
    base, sep, tail = text.rpartition("<")
    if not sep or not tail.endswith(">") or not tail[:-1].isdecimal():
        return text
    index = int(tail[:-1])
    base = base.rstrip()
    return base if index <= 1 else f"{base}[{index - 1}]"


def _mated_paths(feature: dict[str, Any], instances: dict[str, str]) -> list[str] | None:
    data = feature.get("featureData")
    entities = data.get("matedEntities") if isinstance(data, dict) else None
    if not isinstance(entities, list) or len(entities) != 2:
        return None
    paths: list[str] = []
    for entity in entities:
        occurrence = entity.get("matedOccurrence") if isinstance(entity, dict) else None
        if not isinstance(occurrence, list) or not occurrence:
            return None
        segments: list[str] = []
        for identity in occurrence:
            segment = instances.get(str(identity))
            if segment is None:
                return None
            segments.append(segment)
        paths.append("/".join(segments))
    return paths


def mates_from_definition(payload: Any) -> list[MateRecord]:
    """Pure: the `mate` features of an assembly definition (`rootAssembly.features`, with
    or without `{message}` envelopes), suppressed ones and anything malformed skipped."""
    root = payload.get("rootAssembly", payload) if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        return []
    instances: dict[str, str] = {}
    raw_instances = root.get("instances")
    for instance in raw_instances if isinstance(raw_instances, list) else []:
        if isinstance(instance, dict) and isinstance(instance.get("id"), str):
            segment = _instance_segment(instance.get("name"))
            if segment is not None:
                instances[instance["id"]] = segment
    features = root.get("features")
    records: list[MateRecord] = []
    for raw in features if isinstance(features, list) else []:
        feature = raw.get("message", raw) if isinstance(raw, dict) else None
        if not isinstance(feature, dict) or feature.get("featureType") != "mate":
            continue
        if feature.get("suppressed") is True:
            continue
        data = feature.get("featureData")
        mate_type = data.get("mateType") if isinstance(data, dict) else None
        feature_id = feature.get("id")
        paths = _mated_paths(feature, instances)
        if (
            paths is None
            or not isinstance(mate_type, str)
            or not _MATE_TYPE.fullmatch(mate_type)
            or not isinstance(feature_id, str)
            or not _FEATURE_ID.fullmatch(feature_id)
        ):
            continue
        records.append(MateRecord(paths[0], paths[1], mate_type, feature_id))
    return records


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
