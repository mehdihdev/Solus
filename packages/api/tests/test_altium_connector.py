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


def test_config_fields_declare_live_acquisition_project_path() -> None:
    # SOLUSDEV-102 ALT-8: `BridgeExportAcquirer` reads the additive
    # `project_path` config key (mcp_acquire.py's documented config-key
    # decision) — the connector's declared config shape must advertise it.
    # The committed export stays first: it remains sufficient on its own
    # (ADR-030 / §2.1 invariant 3).
    assert AltiumConnector.config_fields == ("export", "project_path")


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


# A minimal, distinct acquired export (one part, one net) so the acquirer-wins
# test can tell the two sources apart by the graph they produce.
ACQUIRED_EXPORT = """[
D1
SOD-123
1N4148
]
(
NETA
D1-1
)
"""


class _RecordingAcquirer:
    """Fake `ExportAcquirer`: records every `SyncContext` it is handed and
    returns a canned answer (text, or `None` to decline)."""

    def __init__(self, result: str | None) -> None:
        self._result = result
        self.contexts: list[SyncContext] = []

    async def acquire(self, ctx: SyncContext) -> str | None:
        self.contexts.append(ctx)
        return self._result


async def test_inline_export_fallback_without_project_path() -> None:
    # §2.1 invariant 3 (ADR-030): a source configured with ONLY the committed
    # export — no project_path, no acquirer — syncs exactly as today.
    result = await AltiumConnector().sync(
        SyncContext(credentials=Credentials(token="x"), config={"export": PROTEL_EXPORT})
    )
    by_type: dict[str, set[str]] = {}
    for entity in result.entities:
        by_type.setdefault(entity.type, set()).add(entity.source_key)
    assert by_type["component"] == {"U1", "R1", "C1"}
    assert by_type["net"] == {"net:VCC", "net:GND", "net:SIGNAL"}
    assert result.errors == []


async def test_declining_acquirer_falls_back_to_inline_export() -> None:
    # A configured acquirer returning None degrades to config["export"]
    # (§2.1 invariant 3) — identical result to the acquirer-less path.
    acquirer = _RecordingAcquirer(result=None)
    result = await AltiumConnector(acquirer=acquirer).sync(_ctx())
    components = {e.source_key for e in result.entities if e.type == "component"}
    assert components == {"U1", "R1", "C1"}
    assert len(acquirer.contexts) == 1  # the acquirer WAS consulted first


async def test_acquired_export_wins_and_project_path_reaches_the_acquirer() -> None:
    # An acquirer that returns text wins outright over the inline export, and
    # the connector hands the acquirer its SyncContext with the config —
    # including project_path — untouched.
    acquirer = _RecordingAcquirer(result=ACQUIRED_EXPORT)
    config = {"export": PROTEL_EXPORT, "project_path": "/work/board"}
    ctx = SyncContext(credentials=Credentials(token="x"), config=config)
    result = await AltiumConnector(acquirer=acquirer).sync(ctx)
    components = {e.source_key for e in result.entities if e.type == "component"}
    assert components == {"D1"}  # the acquired text, not the inline export
    assert len(acquirer.contexts) == 1
    seen = acquirer.contexts[0]
    assert seen is ctx
    assert seen.config == {"export": PROTEL_EXPORT, "project_path": "/work/board"}


async def test_validate_credentials_reports_synthetic_identity() -> None:
    account = await AltiumConnector().validate_credentials(Credentials(token="x"))
    assert account.login == "altium-export"


async def test_protel_has_no_native_mpn_so_modality_hints_are_empty() -> None:
    # W0-08 §5.4 flag: stock Protel carries value/comment but no native MPN, so
    # the supply-chain fingerprint channel is empty in v1.
    result = await AltiumConnector().sync(_ctx())
    components = [e for e in result.entities if e.type == "component"]
    assert all(e.modality_hints == {} for e in components)
