"""Mechanical CAD family — IR → graph mapping + the connector scaffold (SOLUS-CAD-00).

No DB, no network, no OCCT: these tests drive the pure mapping layer and the
`CadExportConnector` scaffold. The STEP reader has its own suite
(`test_step_parser.py`), which is the only place OCCT is required.

Governing docs: `docs/contracts/metadata-extraction.md` §5.5 (STEP is the
assembly source), §2.1 (MCP-04 acquisition invariants), W0-05 connector
contract, ADR-027 (free-string kinds/relations).
"""

from __future__ import annotations

import pytest
from fixtures.cad_sample import BRACKET
from solus_api.connectors.conformance import assert_connector_contract
from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)
from solus_api.connectors.mechanical import (
    MAX_CAD_EXPORT_BYTES,
    PART_OF,
    CadExportConnector,
    CadModel,
    CadNode,
    build_mechanical_graph,
)

STEP_TEXT = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


class _FakeCad(CadExportConnector):
    """A CAD connector whose parser ignores the bytes and returns the fixture —
    exercises the family scaffold without OCCT."""

    provider = "fakecad"

    def parse(self, text: str) -> CadModel:
        if "ISO-10303-21" not in text:
            raise ConnectorError("export_unsupported", "not a STEP file")
        return BRACKET


def _ctx(export: str = STEP_TEXT) -> SyncContext:
    return SyncContext(credentials=Credentials(token="unused"), config={"export": export})


# --------------------------------------------------------------- mapping


def test_every_node_becomes_a_mechanical_entity() -> None:
    entities, _, errors = build_mechanical_graph(BRACKET)

    assert errors == []
    assert {e.source_key for e in entities} == {
        "Bracket",
        "Bracket/BasePlate",
        "Bracket/PegPair",
        "Bracket/PegPair/Peg[0]",
        "Bracket/PegPair/Peg[1]",
    }
    assert all(e.domain is Domain.MECHANICAL for e in entities)


def test_assemblies_and_leaves_are_both_parts_flagged_by_property() -> None:
    """W0-08 §5.5 vocabulary: `part` for product-structure nodes. The
    assembly/leaf distinction rides `properties`, not a second kind."""
    by_key = {e.source_key: e for e in build_mechanical_graph(BRACKET)[0]}

    assert by_key["Bracket"].type == "part"
    assert by_key["Bracket"].properties["is_assembly"] is True
    assert by_key["Bracket/PegPair/Peg[0]"].type == "part"
    assert by_key["Bracket/PegPair/Peg[0]"].properties["is_assembly"] is False


def test_hierarchy_becomes_part_of_edges_child_to_parent() -> None:
    _, relations, _ = build_mechanical_graph(BRACKET)

    assert {(r.from_key, r.to_key) for r in relations} == {
        ("Bracket/BasePlate", "Bracket"),
        ("Bracket/PegPair", "Bracket"),
        ("Bracket/PegPair/Peg[0]", "Bracket/PegPair"),
        ("Bracket/PegPair/Peg[1]", "Bracket/PegPair"),
    }
    assert {r.type for r in relations} == {PART_OF}


def test_placement_rides_the_edge_properties() -> None:
    """STEP yields geometric PLACEMENTS, not semantic mates (§5.5). The
    placement belongs to the OCCURRENCE, i.e. the edge, not the product."""
    edges = {r.from_key: r for r in build_mechanical_graph(BRACKET)[1]}

    assert edges["Bracket/PegPair/Peg[0]"].properties["placement"] == [5.0, 8.0, 5.0]
    assert edges["Bracket/PegPair/Peg[1]"].properties["placement"] == [20.0, 8.0, 5.0]


def test_repeated_product_keeps_distinct_occurrence_keys() -> None:
    """Two Peg instances are two graph rows, both naming the same part number —
    the instance-vs-product identity case from §6.1."""
    by_key = {e.source_key: e for e in build_mechanical_graph(BRACKET)[0]}
    pegs = [by_key["Bracket/PegPair/Peg[0]"], by_key["Bracket/PegPair/Peg[1]"]]

    assert all(p.name == "Peg" for p in pegs)
    assert all(p.modality_hints["part_number"] == "DIN-912-M4" for p in pegs)


def test_fingerprint_channels_use_the_matcher_key_spellings() -> None:
    """D-D: the matcher reads `part_number` / `cad_model` (`_HINT_KEYS`). A hint
    under any other spelling is a dead channel."""
    by_key = {e.source_key: e for e in build_mechanical_graph(BRACKET)[0]}
    plate = by_key["Bracket/BasePlate"]

    assert plate.modality_hints["part_number"] == "AL-6061-PLATE"
    assert plate.modality_hints["cad_model"] == "Bracket/BasePlate"
    # A node with no MPN must not invent one.
    assert "part_number" not in by_key["Bracket"].modality_hints


def test_material_rides_properties_not_hints() -> None:
    by_key = {e.source_key: e for e in build_mechanical_graph(BRACKET)[0]}

    assert by_key["Bracket/BasePlate"].properties["material"] == "Aluminium 6061"
    assert "material" not in by_key["Bracket/BasePlate"].modality_hints


def test_dangling_parent_is_a_sync_error_not_a_crash() -> None:
    model = CadModel(
        nodes=(CadNode(key="orphan", name="Orphan", is_assembly=False, parent_key="ghost"),)
    )

    entities, relations, errors = build_mechanical_graph(model)

    assert [e.source_key for e in entities] == ["orphan"]
    assert relations == []
    assert len(errors) == 1
    assert "ghost" in errors[0].message


def test_duplicate_keys_are_rejected_rather_than_silently_merged() -> None:
    model = CadModel(
        nodes=(
            CadNode(key="dup", name="A", is_assembly=False),
            CadNode(key="dup", name="B", is_assembly=False),
        )
    )

    entities, _, errors = build_mechanical_graph(model)

    assert len(entities) == 1
    assert any("dup" in e.message for e in errors)


def test_a_dropped_duplicate_never_contributes_a_relation() -> None:
    """Regression (code review HIGH). A duplicate key drops its ENTITY, so it must
    drop its EDGE too. Emitting it anyway produced two `part_of` records with the
    same (from, to, type) but different placements; `_reconcile_relations` keys on
    exactly that tuple, so one silently overwrote the other and a placement could
    be attributed to the wrong occurrence — with no SyncError anywhere."""
    model = CadModel(
        nodes=(
            CadNode(key="Root", name="Root", is_assembly=True),
            CadNode(
                key="Root/Peg",
                name="Peg",
                is_assembly=False,
                parent_key="Root",
                placement=(1.0, 1.0, 1.0),
            ),
            CadNode(
                key="Root/Peg",  # collides with the node above
                name="Peg",
                is_assembly=False,
                parent_key="Root",
                placement=(9.0, 9.0, 9.0),
            ),
        )
    )

    entities, relations, errors = build_mechanical_graph(model)

    assert len(entities) == 2
    assert len(relations) == 1
    assert relations[0].properties["placement"] == [1.0, 1.0, 1.0]
    assert any("duplicate" in e.message for e in errors)


def test_relation_tuples_are_unique_even_under_duplicate_keys() -> None:
    """The conformance suite checks entity-key uniqueness and endpoint membership
    but NOT relation-tuple uniqueness — so this asserts it directly."""
    model = CadModel(
        nodes=(
            CadNode(key="R", name="R", is_assembly=True),
            *(
                CadNode(key="R/C", name="C", is_assembly=False, parent_key="R", placement=(i, 0, 0))
                for i in range(4)
            ),
        )
    )

    _, relations, _ = build_mechanical_graph(model)

    tuples = [(r.from_key, r.to_key, r.type) for r in relations]
    assert len(tuples) == len(set(tuples))


def test_parser_warnings_surface_as_sync_errors() -> None:
    model = CadModel(
        nodes=(CadNode(key="a", name="A", is_assembly=False),),
        warnings=("AP203 file carries no product names",),
    )

    _, _, errors = build_mechanical_graph(model)

    assert any("AP203" in e.message for e in errors)


# --------------------------------------------------------------- connector


def test_provider_metadata_is_a_credential_free_export_connector() -> None:
    connector = _FakeCad()

    assert connector.provider == "fakecad"
    assert connector.auth_kind is AuthKind.NONE
    assert connector.supports_token_connect is False
    assert connector.config_fields == ("export",)


async def test_sync_maps_the_export_into_entities_and_relations() -> None:
    result = await _FakeCad().sync(_ctx())

    assert len(result.entities) == 5
    assert len(result.relations) == 4
    assert result.cursor["content_sha"]


async def test_passes_connector_conformance_suite() -> None:
    await assert_connector_contract(_FakeCad(), _ctx())


async def test_detect_changes_tracks_the_export_content() -> None:
    connector = _FakeCad()
    cursor = (await connector.sync(_ctx())).cursor

    unchanged = SyncContext(
        credentials=Credentials(token="unused"),
        config={"export": STEP_TEXT},
        cursor=cursor,
    )
    changed = SyncContext(
        credentials=Credentials(token="unused"),
        config={"export": STEP_TEXT + "/* edited */"},
        cursor=cursor,
    )

    assert await connector.detect_changes(unchanged) is False
    assert await connector.detect_changes(changed) is True


async def test_missing_export_is_a_marked_scaffold_error() -> None:
    ctx = SyncContext(credentials=Credentials(token="unused"), config={})

    with pytest.raises(ConnectorError) as excinfo:
        await _FakeCad().sync(ctx)

    assert excinfo.value.code == "export_unavailable"


async def test_detect_changes_fails_safe_when_the_export_cannot_be_read() -> None:
    """An unreadable export must mean "assume changed", never a raised sync."""
    ctx = SyncContext(credentials=Credentials(token="unused"), config={})

    assert await _FakeCad().detect_changes(ctx) is True


async def test_oversized_export_is_refused_before_parsing() -> None:
    ctx = _ctx("x" * (MAX_CAD_EXPORT_BYTES + 1))

    with pytest.raises(ConnectorError) as excinfo:
        await _FakeCad().sync(ctx)

    assert excinfo.value.code == "export_too_large"


async def test_validate_credentials_reports_a_synthetic_identity() -> None:
    account = await _FakeCad().validate_credentials(Credentials(token="unused"))

    assert account.external_id == "fakecad"
    assert account.login


# ------------------------------------------------- key scoping (multi-document)


def test_a_scope_prefixes_every_key_so_two_documents_cannot_collide() -> None:
    """An account-level source spans many documents, and STEP occurrence paths
    carry no document context — two documents with a part named `Bracket` would
    otherwise upsert onto ONE graph row (a false merge the fingerprint can never
    see, since it happens at the ingestion key). The scope is what keeps them
    distinct."""
    a_entities, a_relations, _ = build_mechanical_graph(BRACKET, scope="docA:elem1")
    b_entities, _, _ = build_mechanical_graph(BRACKET, scope="docB:elem1")

    assert "docA:elem1:Bracket" in {e.source_key for e in a_entities}
    assert not {e.source_key for e in a_entities} & {e.source_key for e in b_entities}
    # Relations must move with the entities or they'd dangle.
    assert all(r.from_key.startswith("docA:elem1:") for r in a_relations)
    assert all(r.to_key.startswith("docA:elem1:") for r in a_relations)


def test_the_scope_also_scopes_the_cad_model_hint() -> None:
    entities, _, _ = build_mechanical_graph(BRACKET, scope="docA:elem1")

    hints = [e.modality_hints["cad_model"] for e in entities]
    assert all(h.startswith("docA:elem1:") for h in hints)


def test_provenance_rides_properties_so_an_entity_names_its_document() -> None:
    entities, _, _ = build_mechanical_graph(
        BRACKET, scope="docA:elem1", provenance={"document_id": "docA", "element_id": "elem1"}
    )

    assert all(e.properties["document_id"] == "docA" for e in entities)
    assert all(e.properties["element_id"] == "elem1" for e in entities)


def test_no_scope_leaves_keys_untouched() -> None:
    """Single-scope connectors (the committed-export CAD family) are unchanged."""
    entities, _, _ = build_mechanical_graph(BRACKET)

    assert "Bracket" in {e.source_key for e in entities}
