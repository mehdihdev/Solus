"""SOLUSDEV-320 — the relation vocabulary contract (`solus_contracts.relations`).

Every edge type says which class it belongs to and which way it runs; the TypeScript twin
(`packages/shared-types/src/relations.ts`) is checked against the `_values.json` manifest
this test writes, the same regenerate-and-fail loop `test_field_manifest.py` uses.
"""

import json
from pathlib import Path

import pytest
from solus_contracts import relations as r

FIXTURE = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "relations"

SPEC_TYPES: dict[str, set[str]] = {
    "identity": {"same_as"},
    "structure": {"contains", "part_of"},
    "dependency": {
        "commands",
        "reads",
        "wires",
        "powers",
        "drives",
        "mounts",
        "mates_with",
        "limits",
        "depends_on",
        "requires",
        "hosts",
        "publishes",
        "subscribes",
    },
    "outcome": {"measured_by", "observed", "fixed_by", "verified_by"},
    "legacy": {
        "connected_to",
        "configures",
        "binds",
        "hardware_connected_to",
        "hardware_topology_member",
        "hardware_evidence_for",
        "presence_prepared_for",
        "wiring_proposed_for",
        "deployment_for_target",
        "cad_visual_for",
        "clone_of",
        "references",
        "reads_from",
    },
}


def test_every_relation_type_has_exactly_the_spec_class() -> None:
    by_class: dict[str, set[str]] = {}
    for member in r.RelationType:
        by_class.setdefault(r.relation_class(member.value).value, set()).add(member.value)
    assert by_class == SPEC_TYPES
    assert {c.value for c in r.RelationClass} == set(SPEC_TYPES)


def test_every_relation_type_documents_its_direction() -> None:
    for member in r.RelationType:
        assert member.value in r.RELATION_DOCS, member
        assert "→" in r.RELATION_DOCS[member.value] or "↔" in r.RELATION_DOCS[member.value], member


def test_origins_matrix_cells_and_evidence_kinds_are_the_spec_values() -> None:
    assert [o.value for o in r.EdgeOrigin] == [
        "connector",
        "manual",
        "inferred",
        "fingerprint",
        "system",
    ]
    assert len(r.MatrixCell) == 9
    assert r.MatrixCell.SOFTWARE_ELECTRICAL.value == "software->electrical"
    assert {k.value for k in r.EvidenceKind} == {
        "netlist",
        "firmware_symbol",
        "bus_enumeration",
        "mate",
        "manifest",
        "config",
        "fingerprint",
        "user_confirmed",
        "checker",
        "telemetry_routing",
        "run",
        "sim",
    }


def test_relation_class_rejects_unknown_types() -> None:
    with pytest.raises(ValueError):
        r.relation_class("teleports")
    assert r.is_legacy("connected_to") and not r.is_legacy("powers")


def test_normalize_domain_pair_is_alphabetical_and_strict() -> None:
    assert r.normalize_domain_pair("electrical", "code") == "code<->electrical"
    assert r.normalize_domain_pair("code", "electrical") == "code<->electrical"
    assert r.normalize_domain_pair("runtime", "runtime") == "runtime<->runtime"
    with pytest.raises(ValueError):
        r.normalize_domain_pair("software", "code")


def test_matrix_cell_maps_code_to_software_and_direction_survives() -> None:
    assert r.matrix_cell("code", "electrical") is r.MatrixCell.SOFTWARE_ELECTRICAL
    assert r.matrix_cell("electrical", "code") is r.MatrixCell.ELECTRICAL_SOFTWARE
    assert r.matrix_cell("mechanical", "mechanical") is r.MatrixCell.MECHANICAL_MECHANICAL
    assert r.matrix_cell("project", "code") is None


def test_edge_evidence_is_closed_and_bounded() -> None:
    item = r.EdgeEvidence(kind=r.EvidenceKind.NETLIST, ref="+3V3")
    assert item.detail is None
    with pytest.raises(ValueError):
        r.EdgeEvidence(kind="netlist", ref="+3V3", extra="no")  # type: ignore[call-arg,arg-type]
    with pytest.raises(ValueError):
        r.EdgeEvidence(kind="gossip", ref="x")  # type: ignore[arg-type]
    assert r.evidence_key(
        [{"kind": "netlist", "ref": "a"}, {"kind": "netlist", "ref": "a", "detail": "d"}]
    ) == {("netlist", "a")}


def test_the_values_manifest_is_current() -> None:
    expected = r.values_manifest()
    path = FIXTURE / "_values.json"
    committed = json.loads(path.read_text()) if path.is_file() else None
    if committed != expected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert committed == expected, (
        f"{path} was stale and has been regenerated; commit it — "
        "shared-types/src/relations.test.ts checks its constants against it."
    )
