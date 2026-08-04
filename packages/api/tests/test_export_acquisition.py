"""`ExportAcquirer` seam tests (SOLUSDEV-100 T4a) — the async acquisition chain
in `EdaExportConnector._read_export` (docs/contracts/metadata-extraction.md §2.1).

Proves the seam's invariants at the connector boundary using fakes (never a
real bridge/MCP client — the concrete acquirer is a separate, later ticket):
acquirer-preferred ordering, degrade-and-fall-through on both a declining
(`None`) and a raising acquirer (with a logged degradation line either way),
the unchanged no-acquirer/no-inline failure, `MAX_EXPORT_BYTES` applying
uniformly regardless of source, and content (not transport) determining the
resulting `SyncResult`. Pure unit — no DB, no network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest
from solus_api.connectors.contracts import ConnectorError, Credentials, SyncContext
from solus_api.connectors.eda import MAX_EXPORT_BYTES, Component, EdaExportConnector, Netlist


class _AcquisitionConnector(EdaExportConnector):
    """Minimal EDA connector for these tests: one component per non-blank line."""

    provider = "acqtest"

    def parse(self, text: str) -> Netlist:
        return Netlist(
            components=tuple(
                Component(designator=line.strip()) for line in text.splitlines() if line.strip()
            )
        )


@dataclass
class _StaticAcquirer:
    """A fake `ExportAcquirer` returning fixed text, or `None` to decline."""

    text: str | None

    async def acquire(self, ctx: SyncContext) -> str | None:
        return self.text


@dataclass
class _RaisingAcquirer:
    """A fake `ExportAcquirer` that always raises — proves the caller never lets
    an acquirer's exception escape `_read_export` as anything but a fallback."""

    exc: Exception

    async def acquire(self, ctx: SyncContext) -> str | None:
        raise self.exc


def _ctx(export: str | None) -> SyncContext:
    config = {} if export is None else {"export": export}
    return SyncContext(credentials=Credentials(token="unused"), config=config)


# ------------------------------------------------------------- acquirer preferred


async def test_acquirer_text_is_preferred_over_inline_export() -> None:
    connector = _AcquisitionConnector(acquirer=_StaticAcquirer(text="U1\nR1\nC1"))
    # Inline export differs from the acquirer's text; the acquirer must win.
    result = await connector.sync(_ctx(export="U1"))
    assert {e.source_key for e in result.entities} == {"U1", "R1", "C1"}


# ------------------------------------------------------------- acquirer declines (None)


async def test_acquirer_none_falls_back_to_inline_with_logged_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _AcquisitionConnector(acquirer=_StaticAcquirer(text=None))
    with caplog.at_level(logging.WARNING, logger="solus.connectors.eda"):
        result = await connector.sync(_ctx(export="U1\nR1"))
    assert {e.source_key for e in result.entities} == {"U1", "R1"}
    assert "acqtest" in caplog.text
    assert "export" in caplog.text
    assert "degrad" in caplog.text  # "degraded"/"degradation"


# ------------------------------------------------------------- acquirer raises


async def test_acquirer_exception_never_escapes_and_falls_back_to_inline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _AcquisitionConnector(acquirer=_RaisingAcquirer(exc=RuntimeError("bridge offline")))
    with caplog.at_level(logging.WARNING, logger="solus.connectors.eda"):
        result = await connector.sync(_ctx(export="U1\nR1"))
    assert {e.source_key for e in result.entities} == {"U1", "R1"}
    assert "acqtest" in caplog.text
    assert "RuntimeError" in caplog.text


async def test_acquirer_arbitrary_exception_type_also_degrades_cleanly() -> None:
    class _WeirdError(Exception):
        pass

    connector = _AcquisitionConnector(acquirer=_RaisingAcquirer(exc=_WeirdError("boom")))
    # Never escapes as anything but a ConnectorError — and here it doesn't even
    # escape at all, since the inline fallback text is present and used.
    result = await connector.sync(_ctx(export="U1"))
    assert {e.source_key for e in result.entities} == {"U1"}


async def test_detect_changes_still_treats_acquirer_failure_as_safe_true() -> None:
    # detect_changes' narrow ConnectorError catch (fail-safe) must keep working
    # once an acquirer is involved: acquirer failure + no inline → ConnectorError
    # from the exhausted chain → detect_changes reports True (be safe).
    connector = _AcquisitionConnector(acquirer=_RaisingAcquirer(exc=RuntimeError("offline")))
    assert await connector.detect_changes(_ctx(export=None)) is True


# ------------------------------------------------------------- no acquirer, no inline


async def test_no_acquirer_and_no_inline_raises_export_unavailable() -> None:
    connector = _AcquisitionConnector()
    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(_ctx(export=None))
    assert excinfo.value.code == "export_unavailable"


async def test_acquirer_declines_and_no_inline_raises_export_unavailable() -> None:
    connector = _AcquisitionConnector(acquirer=_StaticAcquirer(text=None))
    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(_ctx(export=None))
    assert excinfo.value.code == "export_unavailable"


# ------------------------------------------------------------- size bound applies uniformly


async def test_oversized_acquirer_text_is_rejected_like_inline() -> None:
    huge = "U1\n" + "A" * (MAX_EXPORT_BYTES + 1)
    connector = _AcquisitionConnector(acquirer=_StaticAcquirer(text=huge))
    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(_ctx(export="U1"))
    assert excinfo.value.code == "export_too_large"


# ------------------------------------------------------------- transport-agnostic equality


async def test_same_text_via_acquirer_or_inline_yields_identical_sync_result() -> None:
    text = "U1\nR1\nC1"
    via_acquirer = await _AcquisitionConnector(acquirer=_StaticAcquirer(text=text)).sync(
        _ctx(export="irrelevant inline placeholder")
    )
    via_inline = await _AcquisitionConnector().sync(_ctx(export=text))
    assert via_acquirer == via_inline


async def test_zero_arg_construction_still_works() -> None:
    # Registry factories construct connectors today with no acquirer arg; the
    # constructor addition must not break that (task acceptance bar).
    connector = _AcquisitionConnector()
    result = await connector.sync(_ctx(export="U1"))
    assert {e.source_key for e in result.entities} == {"U1"}
