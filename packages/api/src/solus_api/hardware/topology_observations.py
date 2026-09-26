"""Normalize supplied runtime records and serialized EDA graphs without acquisition or writes."""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.hardware.topology_evidence import (
    MAX_BATCH_BYTES,
    MAX_ROWS,
    Reference,
    SourceKind,
    TopologyEvidence,
    TopologyExtraction,
    TopologyProvenance,
)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _USB(_Record):
    bus: Reference | None = None
    address: Reference | None = None
    vid: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{4}$")] | None = None
    pid: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{4}$")] | None = None
    description: Reference | None = None


class _TTY(_Record):
    path: Reference
    usb_bus: Reference | None = None
    usb_address: Reference | None = None
    serial: Reference | None = None


class _Vendor(_Record):
    bus: Reference | None = None
    protocol: Reference
    address: Reference | None = None
    device: Reference | None = None
    part_candidate: Reference | None = None
    entity_ref: Reference | None = None


class _Entity(BaseModel):
    # The canonical serializer also carries timestamps/version/origin/properties. They are
    # bounded by preflight but do not acquire meaning merely by appearing in this projection.
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: UUID
    project_id: UUID
    source_id: UUID
    type: Literal["component", "net"]
    source_key: Reference
    name: Reference
    domain: Literal["electrical"]


class _Pins(_Record):
    net: Reference
    pins: list[Reference] = Field(min_length=1, max_length=MAX_ROWS)


class _Relation(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: UUID
    project_id: UUID
    source_id: UUID
    type: Literal["connected_to"]
    from_entity_id: UUID
    to_entity_id: UUID
    properties: _Pins


def _text_size(value: str) -> int:
    if len(value) > 2048:
        raise ValueError("observation text exceeds budget")
    return len(value.encode("utf-8"))


def _authority_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError("explicit UUID scope is required")
    return value


def _scalar(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (bool, int, UUID, datetime))


def _preflight(value: object) -> None:
    """Bound raw counts/depth/text before parsing or materializing normalized output."""
    stack = [(value, 0)]
    remaining = 8192
    text_bytes = 0
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > 8:
            raise ValueError("observation structure exceeds budget")
        if isinstance(item, str):
            text_bytes += _text_size(item)
            if text_bytes > MAX_BATCH_BYTES:
                raise ValueError("observation text exceeds total budget")
        elif isinstance(item, dict):
            if len(item) * 2 > remaining - len(stack):
                raise ValueError("observation object exceeds budget")
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, (list, tuple)):
            if len(item) > remaining - len(stack):
                raise ValueError("observation list exceeds budget")
            stack.extend((child, depth + 1) for child in item)
        elif not _scalar(item):
            raise ValueError("unsupported observation value")


def _items(value: object) -> list[Any] | tuple[Any, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ROWS:
        raise ValueError("expected a bounded concrete collection")
    return value


def _invalid(kind: SourceKind) -> TopologyExtraction:
    return TopologyExtraction(
        source_kind=kind, status="invalid", notes=("Invalid or over-budget observations.",)
    )


def _runtime_row(kind: str, raw: Any, scope: dict[str, str]) -> TopologyEvidence:
    fields: dict[str, Any] = {}
    if kind in {"ros2_nodes", "ros2_topics"}:
        provenance = TopologyProvenance(source_ref=scope["source_ref"], entity_ref=raw, detail=kind)
        fields = {"protocol": "ros2"}
    else:
        models: dict[str, type[_Record]] = {"usb": _USB, "tty": _TTY, "vendor": _Vendor}
        record = models[kind].model_validate(raw)
        provenance = TopologyProvenance(
            source_ref=scope["source_ref"], detail=record.model_dump_json()
        )
        if isinstance(record, _USB):
            fields = {
                "bus": record.bus,
                "address": record.address,
                "protocol": "usb",
                "device": record.description,
            }
        elif isinstance(record, _TTY):
            fields = {
                "bus": record.usb_bus,
                "address": record.usb_address,
                "protocol": "usb" if record.usb_bus or record.usb_address else None,
            }
        elif isinstance(record, _Vendor):
            fields = record.model_dump(exclude={"entity_ref"})
            provenance = TopologyProvenance(
                source_ref=scope["source_ref"],
                entity_ref=record.entity_ref,
                detail=record.model_dump_json(),
            )
    return TopologyEvidence(
        source_namespace=scope["source_namespace"],
        source_ref=scope["source_ref"],
        **fields,
        provenance=(provenance,),
    )


def onboard_topology(
    snapshot: Mapping[str, object] | None, *, source_namespace: str, source_ref: str
) -> TopologyExtraction:
    """Structured recordings only; USB/vendor labels never establish MCU identity."""
    try:
        scope = {"source_namespace": source_namespace, "source_ref": source_ref}
        TopologyEvidence(source_namespace=source_namespace, source_ref=source_ref)
        if snapshot is None:
            return TopologyExtraction(source_kind="onboard", status="unavailable")
        _preflight(snapshot)
        if not isinstance(snapshot, dict):
            raise ValueError("expected a structured snapshot")
        allowed = {"ros2_nodes", "ros2_topics", "usb", "tty", "vendor"}
        if (
            set(snapshot) - allowed
            or sum(len(_items(items)) for items in snapshot.values()) > MAX_ROWS
        ):
            return _invalid("onboard")
        rows = tuple(
            _runtime_row(kind, item, scope)
            for kind, items in snapshot.items()
            for item in _items(items)
        )
        return TopologyExtraction(source_kind="onboard", status="success", rows=rows)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _invalid("onboard")


def _scoped_nodes(
    entities: Sequence[Mapping[str, Any]], project_id: UUID, source_id: UUID
) -> dict[UUID, _Entity]:
    nodes: dict[UUID, _Entity] = {}
    for raw in _items(entities):
        entity = _Entity.model_validate(raw)
        if entity.project_id != project_id or entity.source_id != source_id or entity.id in nodes:
            raise ValueError("foreign or duplicate graph entity")
        nodes[entity.id] = entity
    return nodes


def _schematic_rows(
    nodes: dict[UUID, _Entity],
    relations: Sequence[Mapping[str, Any]],
    project_id: UUID,
    source_id: UUID,
) -> list[TopologyEvidence]:
    rows: list[TopologyEvidence] = []
    seen: set[UUID] = set()
    for raw in _items(relations):
        edge = _Relation.model_validate(raw)
        if edge.project_id != project_id or edge.source_id != source_id or edge.id in seen:
            raise ValueError("foreign or duplicate graph relation")
        seen.add(edge.id)
        component, net = nodes.get(edge.from_entity_id), nodes.get(edge.to_entity_id)
        if component is None or net is None or component.type != "component" or net.type != "net":
            raise ValueError("dangling or incompatible graph relation")
        if edge.properties.net != net.name or len(rows) + len(edge.properties.pins) > MAX_ROWS:
            raise ValueError("mismatched net or excessive pin count")
        for pin in edge.properties.pins:
            rows.append(
                TopologyEvidence(
                    source_namespace=f"{project_id}:{source_id}",
                    source_ref=str(source_id),
                    bus=str(net.id),
                    device=component.name,
                    part_candidate=str(component.id),
                    provenance=(
                        TopologyProvenance(
                            source_ref=f"{source_id}:{edge.id}",
                            entity_ref=str(component.id),
                            pin_ref=pin,
                            detail=(
                                f"component={component.source_key}; "
                                f"net={net.source_key}; net_id={net.id}"
                            ),
                        ),
                    ),
                )
            )
    return rows


def schematic_topology(
    entities: Sequence[Mapping[str, Any]] | None,
    relations: Sequence[Mapping[str, Any]] | None,
    *,
    project_id: UUID,
    source_id: UUID,
) -> TopologyExtraction:
    """Existing serialized component→net graph; caller-provided authority scopes every reference."""
    try:
        project_id, source_id = _authority_uuid(project_id), _authority_uuid(source_id)
        if entities is None or relations is None:
            return TopologyExtraction(source_kind="schematic", status="unavailable")
        _preflight((entities, relations))
        nodes = _scoped_nodes(entities, project_id, source_id)
        rows = _schematic_rows(nodes, relations, project_id, source_id)
        return TopologyExtraction(source_kind="schematic", status="success", rows=tuple(rows))
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _invalid("schematic")
