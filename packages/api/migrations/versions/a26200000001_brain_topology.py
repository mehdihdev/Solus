"""SOLUSDEV-262: additive physical connectivity from accepted CONFIG evidence.

Frozen migration: no application model imports, no config/ownership rewrites.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

revision: str = "a26200000001"
down_revision: str | None = "a26100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
MARKER = "hardware_topology_v1"
RELATION = "hardware_connected_to"
MEMBERSHIP = "hardware_topology_member"
PREFIX = {
    "usb_serial": "usb",
    "usb_can": "can",
    "ble": "ble",
    "bt_classic": "bt",
    "wifi": "ip",
    "ethernet": "ip",
    "ros2": "ros2",
}


def _insert(connection: Connection, table: sa.Table, values: dict[str, Any]) -> None:
    old = connection.execute(sa.select(table).where(table.c.id == values["id"])).mappings().first()
    if old is not None:
        if old["project_id"] != values["project_id"] or old["attrs"].get("managed_by") != MARKER:
            raise RuntimeError("Conflicting hardware topology identity; restore reviewed snapshot")
        return
    connection.execute(
        insert(table).values(**values, created_at=sa.func.now(), updated_at=sa.func.now())
    )


def upgrade_data(connection: Connection) -> None:
    metadata = sa.MetaData()
    entity = sa.Table("graph_entity", metadata, autoload_with=connection)
    edge = sa.Table("graph_edge", metadata, autoload_with=connection)
    entry = sa.Table("solus_entries", metadata, autoload_with=connection)
    owners = (
        connection.execute(
            sa.select(entry, entity.c.name)
            .join(entity, entity.c.id == entry.c.configured_entity_id)
            .where(
                entry.c.kind == "config",
                entry.c.section == "hardware",
                entry.c.deleted_at.is_(None),
                entity.c.kind == "physical_robot",
                entity.c.origin == "manual",
                entity.c.source_id.is_(None),
                entity.c.deleted_at.is_(None),
                entity.c.project_id == entry.c.project_id,
            )
        )
        .mappings()
        .all()
    )
    channels: dict[tuple[UUID, str], str] = {}
    for owner in owners:
        _preflight_owner(connection, entity, edge, dict(owner))
        _preflight_channel(dict(owner), channels)
    for owner in owners:
        payload = owner["payload"] or {}
        identity = payload.get("identity")
        if not identity:
            continue
        if payload.get("schema_version") != 2 or identity.get("kind") not in PREFIX:
            raise RuntimeError("Hardware topology requires validated v2 transport evidence")
        project, robot = owner["project_id"], owner["configured_entity_id"]
        device_ref = f"{PREFIX[identity['kind']]}:{identity['binding']}"
        endpoint = uuid5(project, f"{MARKER}:endpoint:{device_ref}")
        _insert(
            connection,
            entity,
            dict(
                id=endpoint,
                project_id=project,
                kind="hardware_brain",
                domain="electrical",
                origin="manual",
                name=device_ref,
                version=1,
                modality_hints={},
                attrs={"managed_by": MARKER, "channel": identity["kind"]},
            ),
        )
        _link(connection, edge, project, robot, robot, endpoint, None, None, [])
        disabled = _disabled(connection, edge, dict(owner))
        for index, item in enumerate(payload.get("bus_map", [])):
            part = UUID(item["part_entity_id"]) if item.get("part_entity_id") else None
            if part in disabled:
                continue
            protocol, address = item["protocol"], item["address"]
            bus = uuid5(endpoint, f"bus:{protocol}")
            _insert(
                connection,
                entity,
                dict(
                    id=bus,
                    project_id=project,
                    kind="hardware_bus",
                    domain="electrical",
                    origin="manual",
                    name=protocol,
                    version=1,
                    modality_hints={},
                    attrs={"managed_by": MARKER},
                ),
            )
            provenance = payload.get("provenance", {})
            record = next(
                (
                    provenance[key]
                    for key in [f"bus_map.{index}.protocol", f"bus_map.{index}", "bus_map"]
                    if key in provenance
                ),
                None,
            )
            if record is None:
                raise RuntimeError("Bus topology is missing accepted provenance")
            evidence = [{"by": record["by"], "source": record.get("source")}]
            _link(connection, edge, project, robot, endpoint, bus, protocol, None, evidence)
            if part is not None:
                valid = connection.scalar(
                    sa.select(entity.c.id).where(
                        entity.c.id == part,
                        entity.c.project_id == project,
                        entity.c.deleted_at.is_(None),
                    )
                )
                if valid is None:
                    raise RuntimeError("Hardware topology references an absent or foreign part")
                _link(connection, edge, project, robot, bus, part, protocol, address, evidence)


def _preflight_channel(owner: dict[str, Any], channels: dict[tuple[UUID, str], str]) -> None:
    identity = (owner["payload"] or {}).get("identity")
    if not identity:
        return
    kind = identity.get("kind")
    if kind not in PREFIX:
        raise RuntimeError("Hardware topology requires validated v2 transport evidence")
    key = (owner["project_id"], f"{PREFIX[kind]}:{identity['binding']}")
    if channels.setdefault(key, kind) != kind:
        raise RuntimeError("Shared hardware channel conflicts require review before migration")


def _disabled(connection: Connection, edge: sa.Table, owner: dict[str, Any]) -> set[UUID]:
    return set(
        connection.scalars(
            sa.select(edge.c.dst_id).where(
                edge.c.project_id == owner["project_id"],
                edge.c.src_id == owner["entity_id"],
                edge.c.relation_type == "binds",
                edge.c.deleted_at.is_(None),
                edge.c.origin == "manual",
                edge.c.source_id.is_(None),
                edge.c.attrs["enabled"].as_boolean().is_(False),
            )
        )
    )


def _preflight_owner(
    connection: Connection, entity: sa.Table, edge: sa.Table, owner: dict[str, Any]
) -> None:
    project, subject = owner["project_id"], owner["configured_entity_id"]
    node = connection.scalar(
        sa.select(entity.c.id).where(
            entity.c.id == owner["entity_id"],
            entity.c.project_id == project,
            entity.c.kind == "hardware_config",
            entity.c.origin == "manual",
            entity.c.source_id.is_(None),
            entity.c.deleted_at.is_(None),
        )
    )
    link = connection.scalar(
        sa.select(edge.c.id).where(
            edge.c.project_id == project,
            edge.c.src_id == owner["entity_id"],
            edge.c.dst_id == subject,
            edge.c.relation_type == "configures",
            edge.c.origin == "manual",
            edge.c.source_id.is_(None),
            edge.c.deleted_at.is_(None),
        )
    )
    if node is None or link is None:
        raise RuntimeError("Configuration graph requires review before topology migration")
    payload = owner["payload"] or {}
    if payload.get("schema_version") != 2 or payload.get("entity_id") != str(subject):
        raise RuntimeError("Configuration subject requires review before topology migration")
    disabled = _disabled(connection, edge, owner)
    parts = [
        item["part_entity_id"]
        for item in payload.get("bus_map", [])
        if item.get("part_entity_id") is not None and UUID(item["part_entity_id"]) not in disabled
    ]
    if len(parts) != len(set(parts)):
        raise RuntimeError("Ambiguous topology part addresses require review before migration")


def _link(
    connection: Connection,
    edge: sa.Table,
    project: UUID,
    robot: UUID,
    src: UUID,
    dst: UUID,
    protocol: str | None,
    address: str | None,
    evidence: list[dict[str, Any]],
) -> None:
    _insert(
        connection,
        edge,
        dict(
            id=uuid5(robot, f"{MARKER}:{src}:{dst}:{protocol}:{address}"),
            project_id=project,
            src_id=src,
            dst_id=dst,
            relation_type=MEMBERSHIP if src == robot else RELATION,
            domain_pair="electrical<->electrical",
            origin="manual",
            confidence=1.0,
            attrs={
                "managed_by": MARKER,
                "robot_id": str(robot),
                "protocol": protocol,
                "address": address,
                "evidence": evidence,
            },
        ),
    )


def upgrade() -> None:
    upgrade_data(op.get_bind())


def downgrade() -> None:
    # These additive facts can acquire outside links after upgrade. Never cascade them.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM graph_edge WHERE "
            "attrs->>'managed_by' = 'hardware_topology_v1')"
        )
    ):
        raise RuntimeError("Populated hardware topology requires reviewed snapshot restoration")
