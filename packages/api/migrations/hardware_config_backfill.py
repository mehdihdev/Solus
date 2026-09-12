"""SOLUSDEV-260 frozen backfill: validate the complete plan before any mutation.

Maintenance transaction only. Existing graph identities and provenance survive;
no binding is created/enabled and no legacy file is opened. Conflicting copies
abort rather than inventing a winner or an additional evidence store.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from solus_api.hardware.config import EntityHardwareConfig, _leaf_items
from solus_api.hardware.migration import split_legacy_document
from sqlalchemy.engine import Connection

Row = dict[str, Any]
_PARTS = {"part", "component", "cad_part", "assembly"}
_CONNECTION = {"identity", "protocol", "bus_map", "disambiguated_by"}


@dataclass
class Candidate:
    document: EntityHardwareConfig
    source: Row
    entry: Row | None


def _signature(document: EntityHardwareConfig, field: str) -> tuple[Any, dict[str, Any]]:
    value = document.model_dump(mode="json")[field]
    evidence = {
        path: document.provenance_of(path).model_dump(mode="json")
        for path, _ in _leaf_items(value, field + ".")
    }
    return value, evidence


def _merge(first: EntityHardwareConfig, second: EntityHardwareConfig) -> EntityHardwareConfig:
    merged = first.model_dump(mode="json")
    other = second.model_dump(mode="json")
    for field in {"component", *_CONNECTION}:
        if (
            merged[field] is not None
            and merged[field] != []
            and other[field] is not None
            and other[field] != []
        ):
            if _signature(first, field) != _signature(second, field):
                raise RuntimeError(
                    f"Conflicting hardware configuration for subject {first.entity_id}"
                )
        elif other[field] is not None and other[field] != []:
            merged[field] = other[field]
            for path, _ in _leaf_items(other[field], field + "."):
                merged["provenance"][path] = second.provenance_of(path).model_dump(mode="json")
    return EntityHardwareConfig.model_validate(merged)


class Backfill:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        metadata = sa.MetaData()
        self.tables = {
            name: sa.Table(name, metadata, autoload_with=connection, resolve_fks=False)
            for name in ("projects", "graph_entity", "graph_edge", "solus_entries")
        }
        self.projects = self._rows("projects")
        self.nodes = self._rows("graph_entity")
        self.edges = self._rows("graph_edge")
        self.entries = self._rows("solus_entries")
        self.groups: dict[tuple[uuid.UUID, uuid.UUID], list[Candidate]] = defaultdict(list)
        self.updates: dict[str, dict[uuid.UUID, Row]] = defaultdict(dict)
        self.inserts: dict[str, list[Row]] = defaultdict(list)
        self.now = datetime.now(UTC)

    def _rows(self, name: str) -> dict[uuid.UUID, Row]:
        return {
            row["id"]: dict(row)
            for row in self.connection.execute(sa.select(self.tables[name])).mappings()
        }

    def _subject(self, project: uuid.UUID, subject: uuid.UUID) -> Row:
        node = self.nodes.get(subject)
        if (
            node is None
            or node["project_id"] != project
            or node["kind"] not in _PARTS | {"physical_robot"}
        ):
            raise RuntimeError(f"Invalid hardware subject {subject}")
        if node["kind"] == "physical_robot" and (
            node["origin"] != "manual" or node["source_id"] is not None
        ):
            raise RuntimeError(f"Invalid robot provenance {subject}")
        return node

    def _section(self, entry: Row, subject: uuid.UUID) -> Row:
        node = self.nodes.get(entry["entity_id"])
        if (
            node is None
            or node["project_id"] != entry["project_id"]
            or node["kind"] != "hardware_config"
            or node["origin"] != "manual"
            or node["source_id"] is not None
        ):
            raise RuntimeError(f"Invalid configuration graph identity {entry['id']}")
        incoming = [
            edge
            for edge in self.edges.values()
            if edge["dst_id"] == node["id"] and edge["relation_type"] == "contains"
        ]
        outgoing = [
            edge
            for edge in self.edges.values()
            if edge["src_id"] == node["id"] and edge["relation_type"] == "configures"
        ]
        live = entry["deleted_at"] is None and self.nodes[subject]["deleted_at"] is None
        if live and node["deleted_at"] is not None:
            raise RuntimeError(f"Live configuration has deleted identity {entry['id']}")
        if live:
            incoming = [edge for edge in incoming if edge["deleted_at"] is None]
            outgoing = [edge for edge in outgoing if edge["deleted_at"] is None]
        if len(incoming) != 1 or len(outgoing) != 1 or outgoing[0]["dst_id"] != subject:
            raise RuntimeError(f"Ambiguous configuration references {entry['id']}")
        for edge in [*incoming, *outgoing]:
            if (
                edge["project_id"] != entry["project_id"]
                or edge["origin"] != "manual"
                or edge["source_id"] is not None
            ):
                raise RuntimeError(f"Invalid configuration relation {entry['id']}")
        section = self.nodes.get(incoming[0]["src_id"])
        if (
            section is None
            or section["project_id"] != entry["project_id"]
            or section["kind"] != "solus_section"
            or section["attrs"].get("section") != "hardware"
            or section["origin"] != "manual"
            or section["source_id"] is not None
            or section["deleted_at"] is not None
        ):
            raise RuntimeError(f"Invalid hardware section {entry['id']}")
        return section

    def _collect(self, entry: Row) -> None:
        payload = entry["payload"]
        if not isinstance(payload, dict) or entry["section"] != "hardware":
            raise RuntimeError(f"Invalid configuration payload or section {entry['id']}")
        project = entry["project_id"]
        if project not in self.projects or entry["config_version"] < 0:
            raise RuntimeError(f"Invalid configuration project/version {entry['id']}")
        if payload.get("schema_version") == 2:
            owner = EntityHardwareConfig.model_validate(payload)
            documents = {owner.entity_id: owner}
        else:
            documents = split_legacy_document(payload, source_namespace=project)
            owner = documents[uuid.UUID(payload["robot_entity_id"])]
        self._subject(project, owner.entity_id)
        self._section(entry, owner.entity_id)
        if entry["configured_entity_id"] not in (None, owner.entity_id):
            raise RuntimeError(f"Configured subject disagrees with payload {entry['id']}")
        for subject, document in documents.items():
            self._subject(project, subject)
            for mapping in document.bus_map:
                if mapping.part_entity_id is not None:
                    target = self._subject(project, mapping.part_entity_id)
                    if target["kind"] not in _PARTS:
                        raise RuntimeError(f"Invalid bus component {mapping.part_entity_id}")
            self.groups[(project, subject)].append(
                Candidate(document, entry, entry if subject == owner.entity_id else None)
            )

    def _retire(self, entry: Row, when: datetime) -> None:
        self.updates["solus_entries"].setdefault(entry["id"], {})["deleted_at"] = (
            entry["deleted_at"] or when
        )
        node = self.nodes[entry["entity_id"]]
        self.updates["graph_entity"].setdefault(node["id"], {})["deleted_at"] = (
            node["deleted_at"] or when
        )
        for edge in self.edges.values():
            if node["id"] not in {edge["src_id"], edge["dst_id"]} or edge["deleted_at"] is not None:
                continue
            if (
                edge["origin"] != "manual"
                or edge["source_id"] is not None
                or edge["project_id"] != entry["project_id"]
                or edge["relation_type"] not in {"contains", "configures", "binds"}
            ):
                raise RuntimeError(f"Unsafe relation on retired configuration {entry['id']}")
            values: Row = {"deleted_at": when}
            if edge["relation_type"] == "binds":
                values["attrs"] = {
                    **edge["attrs"],
                    "enabled": False,
                    "disabled_reason": "migration_history",
                }
            self.updates["graph_edge"][edge["id"]] = values

    def _new_entry(
        self,
        project: uuid.UUID,
        subject: uuid.UUID,
        document: EntityHardwareConfig,
        source: Row,
        inactive: datetime | None,
    ) -> None:
        entry_id = uuid.uuid5(project, f"hardware-config-entry:{subject}")
        node_id = uuid.uuid5(project, f"hardware-config-node:{subject}")
        if entry_id in self.entries or node_id in self.nodes:
            raise RuntimeError(f"New configuration identity collision {subject}")
        owner = uuid.UUID(
            source["payload"].get("entity_id") or source["payload"]["robot_entity_id"]
        )
        section = self._section(source, owner)
        timestamps = {
            "created_at": source["created_at"],
            "updated_at": source["updated_at"],
            "deleted_at": inactive,
        }
        self.inserts["graph_entity"].append(
            {
                "id": node_id,
                "project_id": project,
                "kind": "hardware_config",
                "domain": "project",
                "name": f"Hardware config — {self.nodes[subject]['name']}",
                "origin": "manual",
                "version": 1,
                "attrs": {"configured_entity_id": str(subject)},
                "modality_hints": {},
                **timestamps,
            }
        )
        self.inserts["solus_entries"].append(
            {
                "id": entry_id,
                "project_id": project,
                "section": "hardware",
                "kind": "config",
                "entity_id": node_id,
                "configured_entity_id": subject,
                "config_version": 1,
                "text": f"Hardware config — {self.nodes[subject]['name']}",
                "author": source["author"],
                "created_by": source["created_by"],
                "payload": document.model_dump(mode="json"),
                **timestamps,
            }
        )
        for relation, src, dst in (
            ("contains", section["id"], node_id),
            ("configures", node_id, subject),
        ):
            edge_id = uuid.uuid5(project, f"hardware-config-edge:{relation}:{src}:{dst}")
            if edge_id in self.edges:
                raise RuntimeError(f"New configuration relation collision {subject}")
            self.inserts["graph_edge"].append(
                {
                    "id": edge_id,
                    "project_id": project,
                    "src_id": src,
                    "dst_id": dst,
                    "relation_type": relation,
                    "domain_pair": f"project<->{self.nodes[subject]['domain']}"
                    if relation == "configures"
                    else "project<->project",
                    "origin": "manual",
                    "confidence": 1.0,
                    "attrs": {},
                    **timestamps,
                }
            )

    def _plan_group(
        self, project: uuid.UUID, subject: uuid.UUID, candidates: list[Candidate]
    ) -> EntityHardwareConfig | None:
        candidates.sort(
            key=lambda item: (
                item.entry is None,
                item.source["deleted_at"] is not None,
                item.source["created_at"],
                str(item.source["id"]),
            )
        )
        merged = candidates[0].document
        for item in candidates[1:]:
            merged = _merge(merged, item.document)
        subject_row = self.nodes[subject]
        inactive = subject_row["deleted_at"] or self.projects[project]["deleted_at"]
        existing = [item for item in candidates if item.entry is not None]
        live = [
            item for item in existing if item.entry is not None and item.entry["deleted_at"] is None
        ]
        canonical = (
            live[0] if live else (existing[0] if inactive is not None and existing else None)
        )
        if (
            canonical is None
            and (inactive is None or not existing)
            and any(item.entry is None for item in candidates)
        ):
            self._new_entry(project, subject, merged, candidates[0].source, inactive)
        for item in existing:
            entry = item.entry
            assert entry is not None
            document = merged if item is canonical else item.document
            payload = document.model_dump(mode="json")
            if entry["payload"].get(
                "schema_version"
            ) == 2 and document == EntityHardwareConfig.model_validate(entry["payload"]):
                payload = entry["payload"]
            self.updates["solus_entries"][entry["id"]] = {
                "payload": payload,
                "configured_entity_id": subject,
                "config_version": entry["config_version"] or 1,
            }
            if inactive is not None or (canonical is not None and item is not canonical):
                self._retire(entry, inactive or self.now)
        return (
            merged
            if inactive is None
            and (canonical is not None or any(item.entry is None for item in candidates))
            else None
        )

    def _validate_ownership(self) -> None:
        roots = {
            node["id"]
            for node in self.nodes.values()
            if node["kind"] == "physical_robot"
            and node["origin"] == "manual"
            and node["source_id"] is None
            and node["deleted_at"] is None
        }
        containers = set(roots)
        live_edges = [
            edge
            for edge in self.edges.values()
            if edge["deleted_at"] is None
            and edge["origin"] == "manual"
            and edge["source_id"] is None
            and edge["relation_type"] == "contains"
        ]
        for edge in live_edges:
            category = self.nodes.get(edge["dst_id"])
            if category is None or edge["src_id"] not in roots:
                continue
            root = self.nodes[edge["src_id"]]
            if (
                category["kind"] == "robot_category"
                and category["origin"] == "manual"
                and category["source_id"] is None
                and category["deleted_at"] is None
                and category["project_id"] == edge["project_id"] == root["project_id"]
                and category["attrs"].get("robot_id") == str(root["id"])
                and category["attrs"].get("category")
                in {
                    "sensors",
                    "actuators",
                    "controllers",
                    "end_effectors",
                    "power",
                    "structure",
                    "wiring",
                }
            ):
                containers.add(category["id"])
        counts: dict[uuid.UUID, int] = defaultdict(int)
        for edge in live_edges:
            target = self.nodes.get(edge["dst_id"])
            if edge["src_id"] not in containers or target is None or target["kind"] not in _PARTS:
                continue
            parent = self.nodes[edge["src_id"]]
            if (
                target["project_id"] != edge["project_id"]
                or parent["project_id"] != edge["project_id"]
            ):
                raise RuntimeError(f"Cross-project hardware ownership {target['id']}")
            if target["deleted_at"] is None:
                counts[target["id"]] += 1
                if counts[target["id"]] > 1:
                    raise RuntimeError(f"Ambiguous hardware ownership {target['id']}")

    def _collect_entries(self) -> None:
        identities: dict[uuid.UUID, int] = defaultdict(int)
        for entry in self.entries.values():
            if entry["entity_id"] is not None:
                identities[entry["entity_id"]] += 1
        for entry in self.entries.values():
            if entry["kind"] == "config":
                if identities[entry["entity_id"]] > 1:
                    raise RuntimeError(f"Shared configuration graph identity {entry['id']}")
                try:
                    self._collect(entry)
                except (ValueError, KeyError, TypeError):
                    raise RuntimeError(
                        f"Invalid hardware configuration requires review: {entry['id']}"
                    ) from None
            elif entry["configured_entity_id"] is not None or entry["config_version"] != 0:
                raise RuntimeError(f"Non-CONFIG subject/version requires review {entry['id']}")

    def plan(self) -> None:
        self._validate_ownership()
        self._collect_entries()
        endpoints: dict[tuple[uuid.UUID, str, str], uuid.UUID] = {}
        for (project, subject), candidates in sorted(self.groups.items()):
            document = self._plan_group(project, subject, candidates)
            if document is None or document.identity is None:
                continue
            for address in ["", *(item.address for item in document.bus_map)]:
                key = (project, document.identity.device_ref, address)
                if key in endpoints and endpoints[key] != subject:
                    raise RuntimeError(f"Conflicting hardware endpoint for subject {subject}")
                endpoints[key] = subject

    def apply(self) -> None:
        for name in ("graph_entity", "solus_entries", "graph_edge"):
            if self.inserts[name]:
                self.connection.execute(self.tables[name].insert(), self.inserts[name])
        for name, rows in self.updates.items():
            table = self.tables[name]
            for identity, values in rows.items():
                self.connection.execute(
                    table.update().where(table.c.id == identity).values(**values)
                )


def upgrade_data(connection: Connection) -> None:
    connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(
        sa.text(
            "LOCK TABLE projects, graph_entity, graph_edge, solus_entries "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    plan = Backfill(connection)
    plan.plan()
    plan.apply()
