"""Rail budgets distinguish declared contributions from unknown electrical data."""

from copy import deepcopy
from uuid import UUID

import pytest
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.rail_current import analyze_rail_current

RAIL, LOAD, SECOND, OTHER = (UUID(int=i) for i in range(1, 5))


def entity(identity, kind="component", **attrs):
    return EntityRead(id=identity, kind=kind, domain="electrical", name=str(identity), attrs=attrs)


def edge(src, dst, relation="connected_to"):
    return EdgeRead(
        src_id=src,
        dst_id=dst,
        relation_type=relation,
        domain_pair="electrical<->electrical",
        confidence=1,
    )


def graph(*loads, edges=None, truncated=False, capacity=1):
    return GraphContext(
        entities=[entity(RAIL, "net", current_max_a=capacity), *loads],
        edges=edges or [edge(RAIL, load.id) for load in loads],
        truncated=truncated,
    )


def test_complete_declared_current_sum_deduplicates_pins_and_is_pure():
    context = graph(
        entity(
            LOAD,
            current_draw_a="0.2",
            current_rail=str(RAIL),
            current_draw_source="declared datasheet row",
        ),
        entity(SECOND, current_draw_a=0.3, current_rail=str(RAIL)),
        edges=[edge(RAIL, LOAD), edge(RAIL, LOAD), edge(SECOND, RAIL)],
    )
    before = deepcopy(context)
    report = analyze_rail_current(context, RAIL)
    assert context == before
    assert report["total_current_a"] == pytest.approx(0.5)
    assert report["known_subtotal_a"] == pytest.approx(0.5)
    assert report["complete"] is True
    assert report["member_count"] == 2
    assert report["capacity_status"] == "within_declared_capacity"
    assert report["contributions"][0]["source"] == "declared datasheet row"


@pytest.mark.parametrize("bad", [None, True, -1, "NaN", "inf", "1e999", {}, "5 mA"])
def test_missing_or_invalid_currents_are_unknown_not_zero(bad):
    report = analyze_rail_current(
        graph(entity(LOAD, current_draw_a=bad, current_rail=str(RAIL))), RAIL
    )
    assert report["total_current_a"] is None
    assert report["complete"] is False
    assert report["unknown"][0]["entity_id"] == str(LOAD)
    assert report["capacity_status"] == "unknown"


def test_boardwide_current_requires_explicit_rail_attribution():
    report = analyze_rail_current(graph(entity(LOAD, current_draw_a=0.2)), RAIL)
    assert report["known_subtotal_a"] == 0
    assert report["unknown"][0]["reason"] == "rail_attribution_missing"


def test_explicit_powers_edge_qualifies_current_but_two_suppliers_are_ambiguous():
    load = entity(LOAD, current_draw_a=0.2)
    context = graph(load, edges=[edge(RAIL, LOAD, "powers")])
    assert analyze_rail_current(context, RAIL)["total_current_a"] == pytest.approx(0.2)
    context = graph(
        load, entity(OTHER, "net"), edges=[edge(RAIL, LOAD, "powers"), edge(OTHER, LOAD, "powers")]
    )
    assert analyze_rail_current(context, RAIL)["total_current_a"] is None


def test_known_lower_bound_can_exceed_capacity_despite_unknown_load():
    report = analyze_rail_current(
        graph(entity(LOAD, current_draw_a=2, current_rail=str(RAIL)), entity(SECOND)), RAIL
    )
    assert report["known_subtotal_a"] == 2
    assert report["total_current_a"] is None
    assert report["capacity_status"] == "over_capacity"


@pytest.mark.parametrize("capacity", [None, True, -1, "nan"])
def test_unknown_capacity_is_not_inferred_from_net_name(capacity):
    report = analyze_rail_current(
        graph(entity(LOAD, current_draw_a=0, current_rail=str(RAIL)), capacity=capacity), RAIL
    )
    assert report["total_current_a"] == 0
    assert report["capacity_a"] is None
    assert report["capacity_status"] == "unknown"


def test_truncation_dangling_members_and_empty_rail_cannot_claim_complete():
    load = entity(LOAD, current_draw_a=0.2, current_rail=str(RAIL))
    for context in [
        graph(load, truncated=True),
        graph(),
        graph(load, edges=[edge(RAIL, LOAD), edge(RAIL, SECOND)]),
    ]:
        report = analyze_rail_current(context, RAIL)
        assert report["complete"] is False
        assert report["total_current_a"] is None


def test_foreign_missing_or_wrong_kind_rail_refuses():
    for context, target in [(graph(), OTHER), (graph(entity(LOAD)), LOAD)]:
        with pytest.raises(ValueError):
            analyze_rail_current(context, target)


def test_conflicting_or_ambiguous_name_attribution_is_unknown():
    rail = entity(RAIL, "net").model_copy(update={"name": "+5V"})
    same_name = entity(OTHER, "net").model_copy(update={"name": rail.name})
    load = entity(LOAD, current_draw_a=0.2, current_rail=rail.name)
    context = GraphContext(
        entities=[rail, same_name, load], edges=[edge(RAIL, LOAD), edge(OTHER, LOAD)]
    )
    assert analyze_rail_current(context, RAIL)["total_current_a"] is None
    load = load.model_copy(update={"attrs": {"current_draw_a": 0.2, "current_rail": "elsewhere"}})
    assert analyze_rail_current(graph(load), RAIL)["total_current_a"] is None


def test_member_limit_and_numeric_overflow_never_emit_complete_or_nonfinite_total():
    context = graph(
        *[entity(UUID(int=i), current_draw_a=1, current_rail=str(RAIL)) for i in range(100, 250)]
    )
    report = analyze_rail_current(context, RAIL)
    assert report["truncated"] is True
    assert report["complete"] is False
    assert len(report["contributions"]) <= 100
    report = analyze_rail_current(
        graph(
            entity(LOAD, current_draw_a=1e308, current_rail=str(RAIL)),
            entity(SECOND, current_draw_a=1e308, current_rail=str(RAIL)),
        ),
        RAIL,
    )
    assert report["total_current_a"] is None
    assert report["known_subtotal_a"] is None
    assert report["complete"] is False
