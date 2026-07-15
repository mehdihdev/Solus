"""KiCad connector tests (SOLUSDEV-100, SOLUS-EDA-01).

v1 parses a committed **KiCad XML netlist** export into the shared electrical
graph shape (components + first-class nets + `connected_to` edges), mirroring the
EDA family exactly as Altium does. The live acquisition path is the family's
clearly-marked scaffold. Proves the fingerprint channels the ticket names
(MPN/value → FP-01) actually flow. Runs the package conformance suite.
Pure unit — no DB, no network.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import KICAD_XML
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)
from solus_api.connectors.kicad import KicadConnector


def _ctx(export: str = KICAD_XML) -> SyncContext:
    return SyncContext(credentials=Credentials(token="unused"), config={"export": export})


def test_provider_metadata() -> None:
    connector = KicadConnector()
    assert connector.provider == "kicad"
    # A committed export carries no tool credential of its own.
    assert connector.auth_kind is AuthKind.NONE
    assert connector.supports_token_connect is False
    assert "export" in connector.config_fields


async def test_sync_maps_components_nets_and_connectivity() -> None:
    result = await KicadConnector().sync(_ctx())
    by_type: dict[str, set[str]] = {}
    for entity in result.entities:
        by_type.setdefault(entity.type, set()).add(entity.source_key)
    assert by_type["component"] == {"U1", "R1", "C1"}
    assert by_type["net"] == {"net:VCC", "net:GND", "net:SIGNAL"}

    # Every entity is electrical; every relation is an intra-source connected_to.
    assert all(e.domain is Domain.ELECTRICAL for e in result.entities)
    vcc = {r.from_key for r in result.relations if r.to_key == "net:VCC"}
    assert vcc == {"U1", "C1"}
    edge = next(r for r in result.relations if r.to_key == "net:VCC" and r.from_key == "U1")
    assert edge.type == "connected_to"
    assert edge.properties == {"net": "VCC", "pins": ["8"]}


async def test_sync_carries_the_fingerprint_channels() -> None:
    # The ticket's acceptance: MPN/value flow so FP-01 can match (W0-08 §5.2).
    result = await KicadConnector().sync(_ctx())
    components = {e.source_key: e for e in result.entities if e.type == "component"}
    u1 = components["U1"]
    assert u1.modality_hints["part_number"] == "LM358DR"
    assert u1.modality_hints["schematic_symbol_name"] == "LM358"
    assert u1.modality_hints["datasheet_ref"] == "https://www.ti.com/lit/ds/symlink/lm358.pdf"
    assert u1.properties["value"] == "LM358"
    # R1's MPN arrives via a <property> alias; C1 has none — absent, not empty.
    assert components["R1"].modality_hints["part_number"] == "RC0603FR-0710KL"
    assert "part_number" not in components["C1"].modality_hints


async def test_passes_connector_conformance_suite() -> None:
    result = await assert_connector_contract(KicadConnector(), _ctx())
    assert result.entities  # produced a graph


async def test_detect_changes_tracks_the_export_content() -> None:
    connector = KicadConnector()
    first = await connector.sync(_ctx())
    unchanged = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": KICAD_XML},
        cursor=first.cursor,
    )
    assert await connector.detect_changes(unchanged) is False
    edited = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": KICAD_XML.replace("10k", "22k")},
        cursor=first.cursor,
    )
    assert await connector.detect_changes(edited) is True


async def test_live_acquisition_is_a_marked_scaffold() -> None:
    # v1 stub: with no committed export content supplied, sync surfaces a clear,
    # stable error instead of pretending to reach the repo.
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(SyncContext(credentials=Credentials(token="x"), config={}))
    assert excinfo.value.code == "export_unavailable"


async def test_validate_credentials_reports_synthetic_identity() -> None:
    account = await KicadConnector().validate_credentials(Credentials(token="x"))
    assert account.login == "kicad-export"


async def test_sexpr_export_fails_sync_with_format_guidance() -> None:
    # XML-only v1 (design review Q2): the S-expr `.net` fails the sync with a
    # stable code so the UI/agent can say "re-export as XML".
    sexpr = '(export (version "E") (components (comp (ref "U1"))))'
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(export=sexpr))
    assert excinfo.value.code == "export_format_unsupported"
