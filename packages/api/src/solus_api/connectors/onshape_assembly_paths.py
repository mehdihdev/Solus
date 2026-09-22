"""Resolve nested part occurrences using only revision-bound vendor definitions."""

from __future__ import annotations

from typing import Any

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_assembly_geometry import (
    InspectionArgs,
    Instance,
    _complete,
    _identity,
    _invalid,
    _occurrence_name,
    _poses,
    _rows,
)
from solus_api.connectors.onshape_circle_geometry import _rigid

_REVISION_FIELDS = ("documentId", "elementId", "documentMicroversion")


def _default_configuration(row: dict[str, Any]) -> None:
    if (
        row.get("configuration") != "default"
        or row.get("fullConfiguration", "default") != "default"
    ):
        raise _invalid("Nested inspection requires default-configuration occurrences")


class _OccurrenceResolver:
    """Walk definitions while retaining independent root-space occurrence poses."""

    def __init__(self, payload: dict[str, Any], args: InspectionArgs, tracked: Any) -> None:
        root = _complete(payload.get("rootAssembly"))
        _default_configuration(root)
        self.rows = _rows(root.get("instances"))
        self.selected = set(self.rows) if args.instance_ids is None else set(args.instance_ids)
        if not self.selected <= self.rows.keys():
            raise ConnectorError("not_found", "A requested root instance is absent")
        self.poses = _poses(root)
        if len(self.poses) > 256:
            raise ConnectorError("result_too_large", "Inspection supports at most 256 occurrences")
        self.definitions = payload.get("subAssemblies", [])
        if not isinstance(self.definitions, list):
            raise _invalid()
        self.tracked = tracked
        self.result: list[Instance] = []
        self.visited: set[tuple[str, ...]] = set()

    def resolve(self) -> tuple[list[Instance], dict[str, Any]]:
        for identity in sorted(self.selected):
            self.visit(self.rows[identity], ())
        for path in self.poses:
            if path[0] in self.selected and path not in self.visited:
                raise _invalid("An occurrence path cannot be resolved to its current definition")
        if len({instance.donor for instance in self.result}) > 4:
            raise ConnectorError("result_too_large", "Inspect at most four donor payloads")
        return self.result, {
            "root_instances": len(self.rows),
            "inspected_instances": len(self.result),
            "excluded": dict.fromkeys(("nested", "suppressed", "configured", "unsupported"), 0),
        }

    def visit(
        self,
        row: dict[str, Any],
        parent: tuple[str, ...],
        ancestors: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        path = (*parent, _identity(row.get("id")))
        if len(path) > 8 or len(self.visited) >= 256:
            raise ConnectorError("result_too_large", "Nested inspection exceeds its path bound")
        self.visited.add(path)
        _default_configuration(row)
        if row.get("suppressed") is not False:
            raise _invalid("Nested inspection requires active occurrences")
        donor = tuple(_identity(row.get(k), url=True) for k in _REVISION_FIELDS)
        if not isinstance(self.tracked, list) or donor[0] not in self.tracked:
            raise ConnectorError("not_found", "A nested assembly or donor document is not tracked")
        if path not in self.poses:
            raise _invalid("A nested occurrence has no observed world transform")
        transform = _rigid(self.poses[path])
        if row.get("type") == "Part":
            self.add_part(row, path, donor, transform, ancestors)
        elif row.get("type") == "Assembly":
            children = _rows(self.definition(donor).get("instances"))
            for identity in sorted(children):
                self.visit(children[identity], path, (*ancestors, donor))
        else:
            raise _invalid("Unsupported nested occurrence type")

    def add_part(
        self,
        row: dict[str, Any],
        path: tuple[str, ...],
        donor: tuple[str, ...],
        transform: list[float],
        ancestors: tuple[tuple[str, ...], ...],
    ) -> None:
        self.result.append(
            Instance(
                path[-1],
                donor[0],
                donor[1],
                donor[2],
                _identity(row.get("partId")),
                transform,
                path,
                ancestors,
                occurrence_name=_occurrence_name(row.get("name")),
            )
        )
        if len(self.result) > 64:
            raise ConnectorError(
                "result_too_large", "Filter root instances to inspect at most 64 parts"
            )

    def definition(self, donor: tuple[str, ...]) -> dict[str, Any]:
        matches = [
            row
            for row in self.definitions
            if isinstance(row, dict)
            and tuple(row.get(k) for k in _REVISION_FIELDS) == donor
            and row.get("configuration") == "default"
        ]
        if len(matches) != 1:
            raise _invalid("A nested definition is missing, ambiguous or at a different revision")
        definition = _complete(matches[0])
        _default_configuration(definition)
        return definition


def nested_instances(
    payload: dict[str, Any], args: InspectionArgs, tracked: Any
) -> tuple[list[Instance], dict[str, Any]]:
    return _OccurrenceResolver(payload, args, tracked).resolve()
