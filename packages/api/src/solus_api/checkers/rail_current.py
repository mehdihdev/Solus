"""Pure, bounded current accounting from explicitly attributed graph data."""

import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.attributes import CURRENT_DRAW_A, CURRENT_MAX_A, attr_nonneg_float

MAX_MEMBERS = 100
MAX_NAME = 160
MAX_SOURCE = 400


def _number(entity: EntityRead, key: str) -> float | None:
    try:
        return attr_nonneg_float(entity, key)
    except (OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class RailReport:
    """One selected rail; graph data remains untrusted declarations, not measurements."""

    graph: GraphContext
    rail: EntityRead

    def _attributed(self, member: EntityRead) -> bool:
        explicit = member.attrs.get("current_rail")
        if explicit is not None:
            if explicit == str(self.rail.id):
                return True
            if not isinstance(explicit, str) or explicit != self.rail.name:
                return False
            matching = {
                node.id
                for node in self.graph.entities
                if node.kind == "net"
                and node.name == explicit
                and node.id in self._neighbors(member.id)
            }
            return matching == {self.rail.id}
        suppliers = {
            edge.src_id
            for edge in self.graph.edges
            if edge.relation_type == "powers" and edge.dst_id == member.id
        }
        return suppliers == {self.rail.id}

    def _neighbors(self, identity: UUID) -> set[UUID]:
        neighbors = set()
        for edge in self.graph.edges:
            if edge.relation_type == "connected_to":
                if edge.src_id == identity:
                    neighbors.add(edge.dst_id)
                if edge.dst_id == identity:
                    neighbors.add(edge.src_id)
            elif edge.relation_type == "powers" and edge.src_id == identity:
                neighbors.add(edge.dst_id)
        return neighbors - {identity}

    def build(self) -> dict[str, Any]:
        nodes = {node.id: node for node in self.graph.entities}
        members = sorted(self._neighbors(self.rail.id), key=str)
        contributions, unknown = [], []
        truncated = (
            self.graph.truncated or len(members) > MAX_MEMBERS or len(self.rail.name) > MAX_NAME
        )
        for identity in members[:MAX_MEMBERS]:
            member = nodes.get(identity)
            if member is None:
                unknown.append(
                    {"entity_id": str(identity), "name": None, "reason": "missing_graph_member"}
                )
                continue
            item, reason, clipped = self._contribution(member)
            truncated |= clipped
            if reason:
                unknown.append({**item, "reason": reason})
            else:
                contributions.append(item)
        try:
            subtotal = math.fsum(item["current_a"] for item in contributions)
        except OverflowError:
            subtotal = None
        complete = bool(members) and not unknown and not truncated and subtotal is not None
        capacity = _number(self.rail, CURRENT_MAX_A)
        status = "unknown"
        if capacity is not None and subtotal is not None:
            if subtotal > capacity:
                status = "over_capacity"
            elif complete:
                status = "within_declared_capacity"
        return {
            "rail": {"entity_id": str(self.rail.id), "name": self.rail.name[:MAX_NAME]},
            "basis": "declared_graph_attributes",
            "unit": "A",
            "member_count": len(members),
            "contributions": contributions,
            "unknown": unknown,
            "known_subtotal_a": subtotal,
            "total_current_a": subtotal if complete else None,
            "complete": complete,
            "truncated": truncated,
            "capacity_a": capacity,
            "capacity_status": status,
        }

    def _contribution(self, member: EntityRead) -> tuple[dict[str, Any], str | None, bool]:
        item: dict[str, Any] = {"entity_id": str(member.id), "name": member.name[:MAX_NAME]}
        clipped = len(member.name) > MAX_NAME
        if member.domain != "electrical" or member.kind == "net":
            return item, "unsupported_graph_member", clipped
        if not self._attributed(member):
            return item, "rail_attribution_missing", clipped
        current = _number(member, CURRENT_DRAW_A)
        if current is None:
            return item, "current_missing_or_invalid", clipped
        source = member.attrs.get("current_draw_source")
        source = source if isinstance(source, str) else None
        clipped |= source is not None and len(source) > MAX_SOURCE
        return (
            {**item, "current_a": current, "source": source[:MAX_SOURCE] if source else None},
            None,
            clipped,
        )


def analyze_rail_current(graph: GraphContext, rail_entity_id: UUID) -> dict[str, Any]:
    identities = [entity.id for entity in graph.entities]
    if len(identities) != len(set(identities)):
        raise ValueError("Ambiguous graph entities")
    rail = next((node for node in graph.entities if node.id == rail_entity_id), None)
    if rail is None or rail.kind != "net" or rail.domain != "electrical":
        raise ValueError("Electrical rail not found")
    return RailReport(graph, rail).build()
