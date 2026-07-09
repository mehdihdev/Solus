"""Shared EDA family tests (SOLUSDEV-102): netlist IR → graph mapping + the
committed-export connector scaffold. Pure unit — no DB, no network.

Proves the family invariants every EDA connector inherits: first-class `net`
nodes, intra-source `connected_to` edges that carry the pin, unique per-source
keys, orphan-node and duplicate handling, the synthetic identity, the
content-hash change probe, and the clearly-marked v1 acquisition scaffold. The
concrete `_FakeEda` runs the package conformance suite so the base is proven
end-to-end.
"""

from __future__ import annotations

import pytest
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import ConnectorError, Credentials, Domain, SyncContext
from solus_api.connectors.eda import (
    MAX_EXPORT_BYTES,
    Component,
    EdaExportConnector,
    Net,
    Netlist,
    Node,
    _byte_len,
    build_graph,
    component_entity,
    net_entity,
)

NETLIST = Netlist(
    components=(
        Component(designator="U1", footprint="SOIC-8", value="LM358", part_number="LM358DR"),
        Component(designator="R1", footprint="0603", value="10k"),
    ),
    nets=(
        Net(name="VCC", nodes=(Node("U1", "8"), Node("R1", "1"))),
        Net(name="GND", nodes=(Node("U1", "4"),)),
    ),
)


# --------------------------------------------------------------- mapping


def test_component_entity_carries_props_and_part_number_hint() -> None:
    entity = component_entity(NETLIST.components[0])
    assert entity.source_key == "U1"
    assert entity.type == "component"
    assert entity.domain is Domain.ELECTRICAL
    assert entity.properties["footprint"] == "SOIC-8"
    # Supply-chain identity feeds the fingerprint, not properties.
    assert entity.modality_hints == {"part_number": "LM358DR"}


def test_component_without_mpn_has_empty_modality_hints() -> None:
    assert component_entity(NETLIST.components[1]).modality_hints == {}


def test_net_entity_is_namespaced_first_class_node() -> None:
    entity = net_entity(NETLIST.nets[0])
    assert entity.source_key == "net:VCC"
    assert entity.type == "net"
    assert entity.name == "VCC"


def test_build_graph_emits_components_nets_and_connected_edges() -> None:
    entities, relations, errors = build_graph(NETLIST)
    keys = {e.source_key for e in entities}
    assert keys == {"U1", "R1", "net:VCC", "net:GND"}
    assert not errors
    vcc = [r for r in relations if r.to_key == "net:VCC"]
    assert {r.from_key for r in vcc} == {"U1", "R1"}
    u1_vcc = next(r for r in vcc if r.from_key == "U1")
    assert u1_vcc.type == "connected_to"
    assert u1_vcc.properties == {"net": "VCC", "pins": ["8"]}


def test_multi_pin_component_on_a_net_yields_one_edge_with_all_pins() -> None:
    # A multi-VCC/GND IC: U1 pins 4 and 13 both on GND. One edge, both pins —
    # NOT two colliding (from, to, type) edges that drop a connection.
    netlist = Netlist(
        components=(Component(designator="U1"),),
        nets=(Net(name="GND", nodes=(Node("U1", "4"), Node("U1", "13"))),),
    )
    _, relations, _ = build_graph(netlist)
    gnd = [r for r in relations if r.to_key == "net:GND"]
    assert len(gnd) == 1
    assert gnd[0].properties == {"net": "GND", "pins": ["4", "13"]}


def test_build_graph_relations_are_intra_source() -> None:
    entities, relations, _ = build_graph(NETLIST)
    keys = {e.source_key for e in entities}
    for relation in relations:
        assert relation.from_key in keys
        assert relation.to_key in keys


def test_orphan_node_is_dropped_with_an_error() -> None:
    netlist = Netlist(
        components=(Component(designator="U1"),),
        nets=(Net(name="N1", nodes=(Node("U1", "1"), Node("GHOST", "2"))),),
    )
    _, relations, errors = build_graph(netlist)
    assert [r.from_key for r in relations] == ["U1"]
    assert any("unknown component" in e.message for e in errors)


def test_oversized_token_is_dropped_not_fatal() -> None:
    # An adversarial export plants a designator past EntityOut's field bound. The
    # one bad item is dropped with a SyncError; the rest of the netlist still lands
    # (the leniency guarantee holds against a compromised repo — §7).
    netlist = Netlist(
        components=(Component(designator="X" * 5000), Component(designator="R1")),
        nets=(Net(name="Z" * 5000, nodes=()), Net(name="N1", nodes=(Node("R1", "1"),))),
    )
    entities, relations, errors = build_graph(netlist)
    keys = {e.source_key for e in entities}
    assert keys == {"R1", "net:N1"}
    assert [r.from_key for r in relations] == ["R1"]
    assert any("exceeds field bounds" in e.message for e in errors)


def test_byte_len_counts_surrogates_rather_than_dropping_them() -> None:
    # Lossy "ignore" would count a lone surrogate as 0 bytes, letting an
    # adversarial payload slip past the size bound; surrogatepass counts it.
    assert _byte_len("\ud800") == 3


def test_parser_warnings_are_surfaced_as_errors() -> None:
    netlist = Netlist(components=(Component(designator="U1"),), warnings=("dropped 1 block",))
    _, _, errors = build_graph(netlist)
    assert any(e.item == "parse" and "dropped 1 block" in e.message for e in errors)


def test_duplicate_designator_and_net_are_deduped_with_errors() -> None:
    netlist = Netlist(
        components=(Component(designator="U1"), Component(designator="U1")),
        nets=(Net(name="N", nodes=()), Net(name="N", nodes=())),
    )
    entities, _, errors = build_graph(netlist)
    assert [e.source_key for e in entities] == ["U1", "net:N"]
    messages = " ".join(e.message for e in errors)
    assert "duplicate component" in messages and "duplicate net" in messages


# ------------------------------------------------------ connector scaffold


class _FakeEda(EdaExportConnector):
    """Minimal EDA connector: 'REF FOOTPRINT' lines, one shared net of all pin-1s."""

    provider = "fake_eda"

    def parse(self, text: str) -> Netlist:
        components = tuple(
            Component(designator=parts[0], footprint=parts[1] if len(parts) > 1 else None)
            for line in text.splitlines()
            if (parts := line.split())
        )
        net = Net(name="N1", nodes=tuple(Node(c.designator, "1") for c in components))
        return Netlist(components=components, nets=(net,))


def _ctx(config: dict[str, str] | None = None) -> SyncContext:
    return SyncContext(
        credentials=Credentials(token="unused"),
        config=config if config is not None else {"export": "U1 SOIC8\nR1 0603"},
    )


async def test_validate_credentials_returns_synthetic_identity() -> None:
    account = await _FakeEda().validate_credentials(Credentials(token="x"))
    assert account.login == "fake_eda-export"
    assert account.external_id == "fake_eda"


async def test_sync_parses_config_export_into_graph() -> None:
    result = await _FakeEda().sync(_ctx())
    assert {e.source_key for e in result.entities} == {"U1", "R1", "net:N1"}
    assert result.cursor["content_sha"]


async def test_detect_changes_is_true_when_content_hash_differs() -> None:
    connector = _FakeEda()
    result = await connector.sync(_ctx())
    same = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": "U1 SOIC8\nR1 0603"},
        cursor=result.cursor,
    )
    assert await connector.detect_changes(same) is False
    changed = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": "U1 SOIC8\nR1 0603\nC1 0402"},
        cursor=result.cursor,
    )
    assert await connector.detect_changes(changed) is True


async def test_missing_export_raises_clear_scaffold_error() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await _FakeEda().sync(_ctx(config={}))
    assert excinfo.value.code == "export_unavailable"


async def test_detect_changes_is_safe_true_when_export_unavailable() -> None:
    assert await _FakeEda().detect_changes(_ctx(config={})) is True


async def test_oversized_export_is_refused() -> None:
    huge = {"export": "U1 X\n" + "A" * (MAX_EXPORT_BYTES + 1)}
    with pytest.raises(ConnectorError) as excinfo:
        await _FakeEda().sync(_ctx(config=huge))
    assert excinfo.value.code == "export_too_large"


async def test_non_text_export_is_refused() -> None:
    ctx = SyncContext(credentials=Credentials(token="x"), config={"export": 123})
    with pytest.raises(ConnectorError) as excinfo:
        await _FakeEda().sync(ctx)
    assert excinfo.value.code == "export_invalid"


async def test_fake_eda_passes_the_conformance_suite() -> None:
    await assert_connector_contract(_FakeEda(), _ctx())
