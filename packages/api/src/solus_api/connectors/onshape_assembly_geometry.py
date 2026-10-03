"""Bounded, revision-bound numerical observations for assembly inspection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import ONSHAPE_ID_RE, OnshapeConnector
from solus_api.connectors.onshape_circle_geometry import _rigid, circle_frame
from solus_api.connectors.onshape_geometry import _contained_size_bound
from solus_api.connectors.onshape_ops import OnshapeOperation, read_element, workspace_for

_TOPOLOGY = r"^[A-Za-z0-9_+/-]{1,128}$"
_TOLERANCE = 1e-8


class InspectionArgs(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    document_id: str = Field(pattern=ONSHAPE_ID_RE.pattern)
    workspace_id: str | None = Field(default=None, pattern=ONSHAPE_ID_RE.pattern)
    element_id: str = Field(pattern=ONSHAPE_ID_RE.pattern)
    instance_ids: list[str] | None = Field(default=None, min_length=1, max_length=16)
    view: Literal["circles", "coincident_circles", "coaxial_circles"] = "coincident_circles"
    include_nested: bool = False
    min_radius: float = Field(default=0, ge=0)
    max_radius: float | None = Field(default=None, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=10)
    expected_snapshot: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{16}(?::[0-9a-f]{16}){3}$"
    )

    @model_validator(mode="after")
    def consistent(self) -> InspectionArgs:
        if self.max_radius is not None and self.max_radius < self.min_radius:
            raise ValueError("Radius bounds are reversed")
        if self.offset and not self.expected_snapshot:
            raise ValueError("Continuation requires its snapshot")
        if self.instance_ids is not None:
            if len(set(self.instance_ids)) != len(self.instance_ids):
                raise ValueError("Instance identities must be unique")
            for identity in self.instance_ids:
                _identity(identity)
        return self


def _invalid(
    message: str = "Assembly geometry identities or measurements are invalid",
) -> ConnectorError:
    return ConnectorError("api_error", message)


def _identity(value: Any, *, url: bool = False) -> str:
    import re

    if not isinstance(value, str) or not re.fullmatch(
        ONSHAPE_ID_RE.pattern if url else _TOPOLOGY, value
    ):
        raise _invalid()
    return value


def _rows(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise _invalid()
    result = {}
    for row in value:
        if not isinstance(row, dict):
            raise _invalid()
        identity = _identity(row.get("id"))
        if identity in result:
            raise _invalid()
        result[identity] = row
    return result


def _finite(value: Any) -> float:
    if type(value) not in (int, float):
        raise _invalid()
    try:
        number = float(value)
    except OverflowError:
        raise _invalid() from None
    if not math.isfinite(number):
        raise _invalid()
    return number


@dataclass(frozen=True)
class Instance:
    identity: str
    document: str
    element: str
    revision: str
    body: str
    transform: list[float]
    path: tuple[str, ...] = ()
    ancestors: tuple[tuple[str, ...], ...] = ()
    occurrence_name: str | None = None

    @property
    def donor(self) -> tuple[str, str, str]:
        return self.document, self.element, self.revision


def _occurrence_name(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= 200 and value.strip() and value.isprintable():
        return value
    return None


def _poses(root: dict[str, Any]) -> dict[tuple[str, ...], Any]:
    occurrences = root.get("occurrences")
    if not isinstance(occurrences, list):
        raise _invalid()
    poses = {}
    for occurrence in occurrences:
        if (
            not isinstance(occurrence, dict)
            or not isinstance(occurrence.get("path"), list)
            or not occurrence["path"]
        ):
            raise _invalid()
        path = tuple(_identity(v) for v in occurrence["path"])
        if path in poses:
            raise _invalid()
        poses[path] = occurrence.get("transform")
    return poses


def _instances(
    root: dict[str, Any], args: InspectionArgs, tracked: Any
) -> tuple[list[Instance], dict[str, Any]]:
    if (
        root.get("configuration") != "default"
        or root.get("fullConfiguration", "default") != "default"
    ):
        raise _invalid("Only the default assembly configuration can be inspected")
    rows = _rows(root.get("instances"))
    if args.instance_ids is None and len(rows) > 64:
        raise ConnectorError(
            "result_too_large", "Filter instance_ids to inspect at most 64 root instances"
        )
    selected = set(rows) if args.instance_ids is None else set(args.instance_ids)
    if not selected <= rows.keys():
        raise ConnectorError("not_found", "A requested root instance is absent")
    poses = _poses(root)
    excluded = dict.fromkeys(("nested", "suppressed", "configured", "unsupported"), 0)
    result = []
    for identity in sorted(selected):
        row = rows[identity]
        reason = _exclusion(row)
        if reason:
            excluded[reason] += 1
            continue
        donor = tuple(
            _identity(row.get(k), url=True)
            for k in ("documentId", "elementId", "documentMicroversion")
        )
        if not isinstance(tracked, list) or donor[0] not in tracked:
            raise ConnectorError("not_found", "The donor document is not tracked in this project")
        result.append(
            Instance(
                identity,
                donor[0],
                donor[1],
                donor[2],
                _identity(row.get("partId")),
                _rigid(poses.get((identity,))),
                occurrence_name=_occurrence_name(row.get("name")),
            )
        )
    if len({instance.donor for instance in result}) > 4:
        raise ConnectorError(
            "result_too_large", "Filter instance_ids to inspect at most four donor payloads"
        )
    return result, {
        "root_instances": len(rows),
        "inspected_instances": len(result),
        "excluded": excluded,
    }


def _exclusion(row: dict[str, Any]) -> str | None:
    if row.get("suppressed") is True:
        return "suppressed"
    if row.get("suppressed") is not False:
        raise _invalid()
    if row.get("type") == "Assembly":
        return "nested"
    if row.get("type") != "Part":
        return "unsupported"
    if (
        row.get("configuration") != "default"
        or row.get("fullConfiguration", "default") != "default"
    ):
        return "configured"
    return None


def _circles(
    instances: list[Instance], donors: dict[tuple[str, str, str], Any], args: InspectionArgs
) -> list[dict[str, Any]]:
    result = []
    count = 0
    for instance in instances:
        parts = _rows(donors[instance.donor].get("bodies"))
        part = parts.get(instance.body)
        if not part:
            raise _invalid()
        edges = _rows(part.get("edges"))
        for identity, edge in sorted(edges.items()):
            curve = edge.get("curve")
            if not isinstance(curve, dict) or curve.get("type") != "CIRCLE":
                continue
            geometry = edge.get("geometry")
            sweep = geometry.get("arcSweep") if isinstance(geometry, dict) else None
            sweep = _finite(sweep)
            if not math.isclose(abs(sweep), math.tau, rel_tol=1e-6, abs_tol=0):
                continue
            frame = circle_frame(part, identity, instance.transform)
            count += 1
            if count > 2000:
                raise ConnectorError(
                    "result_too_large", "Filter instances to inspect at most 2000 complete circles"
                )
            radius = curve["radius"]
            if radius < args.min_radius or (
                args.max_radius is not None and radius > args.max_radius
            ):
                continue
            result.append(
                {
                    "instance_id": instance.identity,
                    "occurrence_path": list(instance.path or (instance.identity,)),
                    "occurrence_name": instance.occurrence_name,
                    "document_id": instance.document,
                    "element_id": instance.element,
                    "revision": instance.revision,
                    "body_id": instance.body,
                    "edge_id": identity,
                    "center": frame["origin"],
                    "normal": frame["axis"],
                    "radius": radius,
                }
            )
    return result


def _coincident(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        math.dist(left["center"], right["center"]) <= _TOLERANCE
        and min(
            math.dist(left["normal"], right["normal"]),
            math.dist(left["normal"], [-v for v in right["normal"]]),
        )
        <= _TOLERANCE
    )


def _groups(circles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for circle in circles:
        for group in groups:
            if all(_coincident(circle, member) for member in group):
                group.append(circle)
                break
        else:
            groups.append([circle])
    return [
        {"center": group[0]["center"], "members": group}
        for group in groups
        if len({tuple(member.get("occurrence_path", [member["instance_id"]])) for member in group})
        > 1
    ]


def _coaxial_pairs(circles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report closest measured edge pair per collinear line/occurrence pair."""
    from itertools import combinations

    groups: list[list[dict[str, Any]]] = []
    for circle in circles:
        for group in groups:
            if all(_same_axis(circle, member) for member in group):
                group.append(circle)
                break
        else:
            groups.append([circle])
    result = []
    for group in groups:
        by_path: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for member in group:
            by_path.setdefault(
                tuple(member.get("occurrence_path", [member["instance_id"]])), []
            ).append(member)
        for left, right in combinations(sorted(by_path), 2):
            candidates = ((a, b) for a in by_path[left] for b in by_path[right])
            a, b = min(
                candidates,
                key=lambda pair: (
                    math.dist(pair[0]["center"], pair[1]["center"]),
                    pair[0]["edge_id"],
                    pair[1]["edge_id"],
                ),
            )
            result.append(
                {"members": [a, b], "axial_separation_m": math.dist(a["center"], b["center"])}
            )
            if len(result) > 2000:
                raise ConnectorError(
                    "result_too_large", "Filter instances or radii to bound coaxial pairs"
                )
    return result


def _same_axis(left: dict[str, Any], right: dict[str, Any]) -> bool:
    axis = left["normal"]
    if (
        min(math.dist(axis, right["normal"]), math.dist(axis, [-v for v in right["normal"]]))
        > _TOLERANCE
    ):
        return False
    delta = [_finite(b - a) for a, b in zip(left["center"], right["center"], strict=True)]
    along = _finite(sum(a * b for a, b in zip(delta, axis, strict=True)))
    residual = [_finite(a - along * b) for a, b in zip(delta, axis, strict=True)]
    return math.hypot(*residual) <= _TOLERANCE


def _snapshot(root: Any, donors: Any, circles: list[dict[str, Any]], args: InspectionArgs) -> str:
    filters = args.model_dump(exclude={"offset", "limit", "expected_snapshot"})
    if filters["instance_ids"] is not None:
        filters["instance_ids"].sort()
    try:
        encoded = json.dumps(
            [root, sorted(donors), circles, filters], sort_keys=True, allow_nan=False
        )
    except (ValueError, TypeError, OverflowError):
        raise _invalid() from None
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return ":".join(digest[i : i + 16] for i in range(0, 64, 16))


def _page(
    items: list[dict[str, Any]], args: InspectionArgs, base: dict[str, Any]
) -> dict[str, Any]:
    if args.offset > len(items):
        raise ConnectorError("config_invalid", "Offset exceeds the observation count")
    count = min(args.limit, len(items) - args.offset)
    while True:
        end = args.offset + count
        result = {
            **base,
            "total": len(items),
            "offset": args.offset,
            "next_offset": end if end < len(items) else None,
            "items": items[args.offset : end],
        }
        if _contained_size_bound({"ok": True, "value": result}) < 3000:
            return result
        if count <= 1:
            raise ConnectorError(
                "result_too_large",
                "A complete observation exceeds the result bound; filter instance_ids",
            )
        count -= 1


def _complete(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("errorEnum", "NO_ERROR") != "NO_ERROR"
        or any(value.get(flag, False) is not False for flag in ("incomplete", "isIncomplete"))
        or value.get("isComplete", True) is not True
    ):
        raise _invalid("Onshape returned incomplete assembly geometry")
    return value


async def inspect_geometry(
    connector: OnshapeConnector, client: httpx.AsyncClient, raw: dict[str, Any]
) -> dict[str, Any]:
    try:
        args = InspectionArgs.model_validate({k: v for k, v in raw.items() if k != "_documents"})
    except (ValidationError, ConnectorError):
        raise ConnectorError("config_invalid", "Invalid assembly inspection arguments") from None
    workspace = await workspace_for(connector, client, args.model_dump(exclude_none=True))
    payload = await read_element(
        connector,
        client,
        kind="assemblies",
        document_id=args.document_id,
        workspace_id=workspace,
        element_id=args.element_id,
        what="assembly geometry inspection",
    )
    root = _complete(_complete(payload).get("rootAssembly"))
    revision = _identity(root.get("documentMicroversion"), url=True)
    if args.include_nested:
        from solus_api.connectors.onshape_assembly_paths import nested_instances

        instances, coverage = nested_instances(payload, args, raw.get("_documents"))
    else:
        instances, coverage = _instances(root, args, raw.get("_documents"))
    donors = {}
    for document, element, version in sorted({instance.donor for instance in instances}):
        try:
            donors[(document, element, version)] = _complete(
                await connector.immutable_body_details(
                    client, document_id=document, element_id=element, microversion_id=version
                )
            )
        except (ValueError, TypeError, OverflowError):
            raise _invalid() from None
    circles = await asyncio.to_thread(_circles, instances, donors, args)
    # Bind all reported geometry, not unrelated vendor face measurements.
    snapshot_root = (
        [root, [(instance.path, instance.ancestors) for instance in instances]]
        if args.include_nested
        else root
    )
    snapshot = _snapshot(
        snapshot_root, donors, circles, args.model_copy(update={"workspace_id": workspace})
    )
    if args.expected_snapshot is not None and args.expected_snapshot != snapshot:
        raise ConnectorError(
            "stale_state", "Assembly geometry changed; restart inspection at offset zero"
        )
    grouping = {"coincident_circles": _groups, "coaxial_circles": _coaxial_pairs}
    items = (
        await asyncio.to_thread(grouping[args.view], circles) if args.view in grouping else circles
    )
    return _page(
        items,
        args,
        {
            "workspace_id": workspace,
            "root_revision": revision,
            "snapshot": snapshot,
            "view": args.view,
            "units": "m",
            "coverage": coverage,
        },
    )


INSPECTION_OPERATIONS = (
    OnshapeOperation(
        name="onshape.inspect_assembly_geometry",
        description=(
            "Inspect measured world-space complete circles in a tracked assembly. "
            "Default coincident_circles groups shared centers across root parts; these are "
            "geometric observations, not recommended joints. Use view=circles for individual "
            "edges, instance_ids/radius filters to bound work, and next_offset with "
            "expected_snapshot to continue. Use include_nested=true to inspect verified nested "
            "occurrence paths, and view=coaxial_circles for shared axis lines "
            "with separated centers. "
            "Coaxial pairs are geometric observations, not joint recommendations. "
            "Continuing pages reuses one cached read of the assembly. "
            "No images or writes."
        ),
        params=InspectionArgs.model_json_schema(),
        returns={"type": "object"},
        run=inspect_geometry,
        tags=("read", "geometry"),
    ),
)
