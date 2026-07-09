"""Altium connector tests (SOLUSDEV-102, SOLUS-EDA-03).

v1 parses a committed Altium **Protel netlist** export into the shared electrical
graph shape (components + first-class nets + `connected_to` edges), mirroring the
EDA family. The proprietary/live acquisition path is a clearly-marked scaffold —
this suite proves the parse+map+interface are real and that the scaffold boundary
is explicit. Runs the package conformance suite. Pure unit — no DB, no network.
"""

from __future__ import annotations

import pytest
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.altium import AltiumConnector
from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)

# A committed Protel netlist: an op-amp, a resistor, a decoupling cap across
# VCC / GND / a signal net.
PROTEL_EXPORT = """[
U1
SOIC-8
LM358
]
[
R1
0603
10k
]
[
C1
0603
100nF
]
(
VCC
U1-8
C1-1
)
(
GND
U1-4
C1-2
)
(
SIGNAL
U1-1
R1-2
)
"""


def _ctx(export: str = PROTEL_EXPORT) -> SyncContext:
    return SyncContext(credentials=Credentials(token="unused"), config={"export": export})


def test_provider_metadata() -> None:
    connector = AltiumConnector()
    assert connector.provider == "altium"
    # A committed export carries no tool credential of its own.
    assert connector.auth_kind is AuthKind.NONE
    assert connector.supports_token_connect is False
    assert "export" in connector.config_fields


async def test_sync_maps_components_nets_and_connectivity() -> None:
    result = await AltiumConnector().sync(_ctx())
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


async def test_passes_connector_conformance_suite() -> None:
    result = await assert_connector_contract(AltiumConnector(), _ctx())
    assert result.entities  # produced a graph


async def test_detect_changes_tracks_the_export_content() -> None:
    connector = AltiumConnector()
    first = await connector.sync(_ctx())
    unchanged = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": PROTEL_EXPORT},
        cursor=first.cursor,
    )
    assert await connector.detect_changes(unchanged) is False
    edited = SyncContext(
        credentials=Credentials(token="x"),
        config={"export": PROTEL_EXPORT + "(\nNEW\nR1-1\n)\n"},
        cursor=first.cursor,
    )
    assert await connector.detect_changes(edited) is True


async def test_live_acquisition_is_a_marked_scaffold() -> None:
    # v1 stub: with no committed export content supplied, sync surfaces a clear,
    # stable error instead of pretending to reach Altium / the repo.
    with pytest.raises(ConnectorError) as excinfo:
        await AltiumConnector().sync(SyncContext(credentials=Credentials(token="x"), config={}))
    assert excinfo.value.code == "export_unavailable"


async def test_validate_credentials_reports_synthetic_identity() -> None:
    account = await AltiumConnector().validate_credentials(Credentials(token="x"))
    assert account.login == "altium-export"


async def test_protel_has_no_native_mpn_so_modality_hints_are_empty() -> None:
    # W0-08 §5.4 flag: stock Protel carries value/comment but no native MPN, so
    # the supply-chain fingerprint channel is empty in v1.
    result = await AltiumConnector().sync(_ctx())
    components = [e for e in result.entities if e.type == "component"]
    assert all(e.modality_hints == {} for e in components)
