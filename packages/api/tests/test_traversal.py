"""Graph-traversal helper tests (SOLUS-CHK-01, SOLUSDEV-115).

The checkers walk the linked graph through `GraphView`. It must be a pure, read-only index:
resolve entities by id, yield resolved (src, dst) pairs per relation type, drop dangling edges
(so a half-ingested graph never crashes a rule), and never mutate the wrapped graph.
"""

from uuid import uuid4

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.traversal import GraphView, domains_of


def _entity(name: str, domain: str = "electrical") -> EntityRead:
    return EntityRead(id=uuid4(), kind="component", domain=domain, name=name)


def _edge(src: EntityRead, dst: EntityRead, relation_type: str) -> EdgeRead:
    return EdgeRead(
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation_type,
        domain_pair=f"{src.domain}<->{dst.domain}",
        confidence=1.0,
    )


def test_entity_lookup_by_id() -> None:
    a = _entity("A")
    view = GraphView(GraphContext(entities=[a], edges=[]))
    assert view.entity(a.id) is a
    assert view.entity(uuid4()) is None


def test_edges_of_type_resolves_src_and_dst() -> None:
    op_amp = _entity("U1")
    load = _entity("motor_driver")
    graph = GraphContext(entities=[op_amp, load], edges=[_edge(op_amp, load, "drives")])
    view = GraphView(graph)

    pairs = view.edges_of_type("drives")

    assert pairs == [(op_amp, load)]


def test_edges_of_type_unknown_relation_is_empty() -> None:
    view = GraphView(GraphContext(entities=[_entity("A")], edges=[]))
    assert view.edges_of_type("powers") == []


def test_edges_of_type_drops_dangling_edge() -> None:
    # An edge referencing an entity not in the set cannot be evaluated → dropped, not crashed.
    op_amp = _entity("U1")
    ghost = _entity("gone")
    graph = GraphContext(entities=[op_amp], edges=[_edge(op_amp, ghost, "drives")])

    assert GraphView(graph).edges_of_type("drives") == []


def test_edges_of_type_groups_multiple_relations() -> None:
    supply = _entity("VREG")
    load_a = _entity("mcu")
    load_b = _entity("radio")
    graph = GraphContext(
        entities=[supply, load_a, load_b],
        edges=[_edge(supply, load_a, "powers"), _edge(supply, load_b, "powers")],
    )

    pairs = GraphView(graph).edges_of_type("powers")

    assert (supply, load_a) in pairs and (supply, load_b) in pairs
    assert len(pairs) == 2


def test_edges_of_type_deduplicates_identical_pairs() -> None:
    # A double-linked edge (re-run sync / fingerprint linker) must resolve to ONE pair.
    op_amp = _entity("U1")
    load = _entity("drv")
    graph = GraphContext(
        entities=[op_amp, load],
        edges=[_edge(op_amp, load, "drives"), _edge(op_amp, load, "drives")],
    )
    assert GraphView(graph).edges_of_type("drives") == [(op_amp, load)]


def test_domains_of_is_sorted_and_unique() -> None:
    code = _entity("loop.cpp", domain="code")
    sensor = _entity("imu", domain="electrical")
    other = _entity("adc", domain="electrical")

    assert domains_of(sensor, code, other) == ("code", "electrical")


def test_graph_view_does_not_mutate_graph() -> None:
    a = _entity("A")
    b = _entity("B")
    graph = GraphContext(entities=[a, b], edges=[_edge(a, b, "drives")])
    GraphView(graph).edges_of_type("drives")
    assert graph.entities == [a, b]
    assert len(graph.edges) == 1
