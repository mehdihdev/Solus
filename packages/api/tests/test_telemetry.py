"""Telemetry plumbing: ingest → buffer → read (SOLUS-LNK-06).

Covers the ticket acceptance cases with the in-memory buffer + dict resolver (pure, no DB):
attach a sample stream to an entity and read it back, drop unresolved devices, and serve the
W0-07 `get_telemetry` window-summary shape deterministically.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.agent.interfaces import TelemetrySummaryView, TelemetryWindow
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.packet import RecentValuesView, TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing

_T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def _packet(device: str, offset: float, **values: float) -> TelemetryPacket:
    return TelemetryPacket(
        device_id=device, timestamp=_T0 + timedelta(seconds=offset), values=values
    )


def _plumbing_with(project: uuid.UUID, entity: uuid.UUID, device: str) -> TelemetryPlumbing:
    return TelemetryPlumbing(
        InMemoryTelemetryBuffer(), DictEntityResolver({(project, device): entity})
    )


async def test_ingest_attaches_stream_to_entity_and_reads_back() -> None:
    """Core acceptance: attach a sample stream to an entity, read it back."""
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "motor0")
    for i in range(5):
        result = await plumbing.ingest(project, _packet("motor0", i, current_a=1.0 + i))
        assert result.entity_id == entity
        assert result.accepted == 1
        assert result.signals == ["current_a"]

    view = await plumbing.get_recent_values(project, entity)
    assert isinstance(view, RecentValuesView)
    assert view.entity_id == entity
    series = {s.signal: s for s in view.signals}
    assert [p.value for p in series["current_a"].points] == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_ingest_buffers_every_signal_in_a_packet() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "d")
    result = await plumbing.ingest(project, _packet("d", 0.0, a=1.0, b=2.0, c=3.0))
    assert result.accepted == 3
    assert result.signals == ["a", "b", "c"]


async def test_ingest_drops_packet_for_unresolved_device() -> None:
    project = uuid.uuid4()
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver({}))
    result = await plumbing.ingest(project, _packet("ghost", 0.0, x=1.0))
    assert result.entity_id is None
    assert result.accepted == 0  # dropped, not raised


async def test_get_recent_values_signal_filter() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "d")
    await plumbing.ingest(project, _packet("d", 0.0, a=1.0, b=2.0))
    view = await plumbing.get_recent_values(project, entity, signals=["a"])
    assert [s.signal for s in view.signals] == ["a"]


async def test_recent_values_view_is_foxglove_serializable() -> None:
    """CON-03 (Foxglove) reads the same feed: the view must be JSON-serializable."""
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "d")
    await plumbing.ingest(project, _packet("d", 0.0, a=1.0))
    payload = (await plumbing.get_recent_values(project, entity)).model_dump_json()
    assert '"a"' in payload and str(entity) in payload


async def _seed_progression() -> tuple[TelemetryPlumbing, uuid.UUID]:
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "motor0")
    for i in range(10):
        await plumbing.ingest(project, _packet("motor0", i, current_a=1.0 + i))
    return plumbing, project


async def test_get_telemetry_returns_summary_view_with_stats() -> None:
    plumbing, project = await _seed_progression()
    view = await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=10))
    assert isinstance(view, TelemetrySummaryView)
    assert view.windows  # a progression, not empty
    for w in view.windows:
        assert w.window_start <= w.window_end and w.summary
    stats = view.windows[-1].signals.get("current_a")
    assert stats is not None
    assert set(stats) >= {"mean", "min", "max", "last", "count"}


async def test_get_telemetry_is_a_progression_across_buckets() -> None:
    plumbing, project = await _seed_progression()
    view = await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=10))
    assert len(view.windows) >= 2  # samples spread across sub-windows


async def test_get_telemetry_is_deterministic_anchored_to_latest_sample() -> None:
    plumbing, project = await _seed_progression()
    v1 = await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=10))
    v2 = await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=10))
    assert v1 == v2  # no wall-clock → repeatable


async def test_get_telemetry_signal_filter_narrows_output() -> None:
    plumbing, project = await _seed_progression()
    view = await plumbing.get_telemetry(
        project, TelemetryWindow(duration_seconds=10, signals=["nonexistent"])
    )
    assert view.windows == []  # nothing matches the requested signal


async def test_get_telemetry_empty_buffer_is_empty_progression() -> None:
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver({}))
    view = await plumbing.get_telemetry(uuid.uuid4(), TelemetryWindow(duration_seconds=10))
    assert view.windows == []


def test_plumbing_rejects_non_positive_buckets() -> None:
    with pytest.raises(ValueError):
        TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver({}), summary_buckets=0)


async def test_get_telemetry_stats_are_correct() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = _plumbing_with(project, entity, "d")
    # all within one bucket window (duration large enough to bucket together at the end)
    for i, v in enumerate([2.0, 4.0, 6.0]):
        await plumbing.ingest(project, _packet("d", 100 + i * 0.01, load=v))
    view = await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=1))
    # find the signal stats in whichever bucket holds them
    stats = next(w.signals["load"] for w in view.windows if "load" in w.signals)
    assert stats["min"] == 2.0 and stats["max"] == 6.0
    assert stats["mean"] == 4.0 and stats["last"] == 6.0 and stats["count"] == 3.0
