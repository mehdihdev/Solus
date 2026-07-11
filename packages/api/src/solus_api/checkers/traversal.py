"""Read-only graph traversal for the compatibility rules (SOLUS-CHK-01, SOLUSDEV-115).

The checkers are pure functions (ADR-003): they walk a serializable ``GraphContext`` but never
mutate it. ``GraphView`` indexes that graph ONCE per check so a rule can resolve entities by id
and iterate the cross-domain edges it cares about, and ``domains_of`` derives a warning's spanned
domains from the entities it actually implicates (per the ``Warning.domains`` contract).
"""

from collections import defaultdict
from uuid import UUID

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext


class GraphView:
    """An indexed, read-only view over a ``GraphContext``.

    Built once per ``check`` call. Holds only references into the wrapped graph and exposes no
    mutation — the checkers' purity guarantee (graph in, warnings out) rests on this."""

    def __init__(self, graph: GraphContext) -> None:
        self._by_id: dict[UUID, EntityRead] = {e.id: e for e in graph.entities}
        self._by_relation: dict[str, list[EdgeRead]] = defaultdict(list)
        for edge in graph.edges:
            self._by_relation[edge.relation_type].append(edge)

    def entity(self, entity_id: UUID) -> EntityRead | None:
        """The entity with ``entity_id``, or ``None`` if it is not in the graph."""
        return self._by_id.get(entity_id)

    def edges_of_type(self, relation_type: str) -> list[tuple[EntityRead, EntityRead]]:
        """Resolved ``(src, dst)`` entity pairs for every edge of ``relation_type``.

        A dangling edge — one whose src or dst entity is absent from the graph — is DROPPED, not
        raised on: an incompletely-ingested graph must degrade gracefully, never crash a rule.
        A duplicate ``(src, dst)`` pair is collapsed to one, so a double-linked edge (e.g. from a
        re-run sync or the fingerprint linker) never yields duplicate warnings for one finding."""
        pairs: list[tuple[EntityRead, EntityRead]] = []
        seen: set[tuple[UUID, UUID]] = set()
        for edge in self._by_relation.get(relation_type, ()):
            key = (edge.src_id, edge.dst_id)
            if key in seen:
                continue
            src = self._by_id.get(edge.src_id)
            dst = self._by_id.get(edge.dst_id)
            if src is not None and dst is not None:
                seen.add(key)
                pairs.append((src, dst))
        return pairs


def domains_of(*entities: EntityRead) -> tuple[str, ...]:
    """Sorted, de-duplicated domains of ``entities`` — the ``Warning.domains`` derivation."""
    return tuple(sorted({e.domain for e in entities}))
