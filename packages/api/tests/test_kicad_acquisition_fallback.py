"""Acquisition-chain fallback proofs for the KiCad connector (SOLUSDEV-100 T5):
bridge-offline/declining and raising acquirers both degrade to the committed
inline export with a logged degradation (docs/contracts/metadata-extraction.md
§2.1 invariant 3), and an oversize acquired export fails the sync outright
rather than silently falling back (invariant 4 — untrusted either way).
"""

from __future__ import annotations

import logging

import pytest
from fixtures.kicad_project import SOLUS_SAMPLE_NETLIST
from solus_api.connectors.contracts import ConnectorError, Credentials, SyncContext
from solus_api.connectors.eda import MAX_EXPORT_BYTES
from solus_api.connectors.kicad import KicadConnector

NETLIST_TEXT = SOLUS_SAMPLE_NETLIST.read_text()
_EDA_LOGGER = "solus.connectors.eda"


class _DecliningAcquirer:
    """Bridge-offline stand-in: declines every acquisition by returning `None`."""

    async def acquire(self, ctx: SyncContext) -> str | None:
        return None


class _RaisingAcquirer:
    """A companion/bridge failure mid-acquisition."""

    async def acquire(self, ctx: SyncContext) -> str | None:
        raise RuntimeError("bridge exploded")


class _OversizeAcquirer:
    """Returns export text over `MAX_EXPORT_BYTES` — a successful acquisition
    of an oversized/adversarial export, distinct from a decline or a raise."""

    async def acquire(self, ctx: SyncContext) -> str | None:
        return "x" * (MAX_EXPORT_BYTES + 1)


async def test_declining_acquirer_falls_back_to_inline_with_logged_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=_EDA_LOGGER):
        result = await KicadConnector(acquirer=_DecliningAcquirer()).sync(
            SyncContext(credentials=Credentials(token=""), config={"export": NETLIST_TEXT})
        )

    # The committed inline export landed the full graph — the sync succeeded.
    assert {e.type for e in result.entities} == {"component", "net"}
    assert any(
        "falling back to inline export" in record.getMessage()
        and "reason=acquirer returned None (declined/unavailable)" in record.getMessage()
        for record in caplog.records
    )


async def test_raising_acquirer_falls_back_and_sync_still_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=_EDA_LOGGER):
        result = await KicadConnector(acquirer=_RaisingAcquirer()).sync(
            SyncContext(credentials=Credentials(token=""), config={"export": NETLIST_TEXT})
        )

    assert {e.type for e in result.entities} == {"component", "net"}
    assert any(
        "falling back to inline export" in record.getMessage()
        and "reason=acquirer raised RuntimeError: bridge exploded" in record.getMessage()
        for record in caplog.records
    )


async def test_oversize_acquired_export_fails_the_sync_outright() -> None:
    """An oversize export the acquirer actually PRODUCED is neither a decline
    nor a raise — `_read_export` size-checks it exactly like an inline export
    (invariant 4) and fails the sync rather than silently falling back to the
    (perfectly valid) inline `config.export`, per `eda.py`'s own contract."""
    connector = KicadConnector(acquirer=_OversizeAcquirer())
    with pytest.raises(ConnectorError) as exc_info:
        await connector.sync(
            SyncContext(credentials=Credentials(token=""), config={"export": NETLIST_TEXT})
        )
    assert exc_info.value.code == "export_too_large"
