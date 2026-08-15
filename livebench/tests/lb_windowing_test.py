"""CON-03: event-time window aggregation into W0-07 TelemetryWindowSummary."""

from datetime import UTC, datetime, timedelta

from livebench.telemetry.windowing import WindowAggregator
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def packet(sec: float, values: dict[str, float], device: str = "dev") -> TelemetryPacket:
    return TelemetryPacket(device_id=device, timestamp=T0 + timedelta(seconds=sec), values=values)


def test_window_closes_when_a_packet_crosses_the_boundary() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))

    assert agg.add(packet(0.0, {"v": 1.0})) is None
    assert agg.add(packet(0.5, {"v": 3.0})) is None
    summary = agg.add(packet(1.2, {"v": 9.0}))

    assert isinstance(summary, TelemetryWindowSummary)
    assert summary.window_start == T0
    assert summary.window_end == T0 + timedelta(seconds=1.0)
    stats = summary.signals["v"]
    assert stats == {"mean": 2.0, "min": 1.0, "max": 3.0, "last": 3.0, "count": 2.0}


def test_boundary_packet_opens_the_next_window() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    agg.add(packet(0.0, {"v": 1.0}))
    agg.add(packet(1.5, {"v": 5.0}))  # closed window one, now accumulating

    summary = agg.add(packet(3.0, {"v": 7.0}))

    assert summary is not None
    assert summary.window_start == T0 + timedelta(seconds=1.5)
    assert summary.signals["v"]["last"] == 5.0


def test_last_is_by_timestamp_not_arrival_order() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=2.0))
    agg.add(packet(1.0, {"v": 10.0}))
    agg.add(packet(0.5, {"v": 99.0}))  # out of order within the window

    summary = agg.flush()

    assert summary is not None
    assert summary.signals["v"]["last"] == 10.0
    assert summary.signals["v"]["count"] == 2.0


def test_late_packet_from_a_closed_window_is_dropped() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    agg.add(packet(0.0, {"v": 1.0}))
    agg.add(packet(1.5, {"v": 2.0}))  # window [0,1) closed, new anchor 1.5

    agg.add(packet(0.7, {"v": 50.0}))  # late straggler — belongs to a closed window
    summary = agg.flush()

    assert summary is not None
    assert summary.signals["v"] == {
        "mean": 2.0,
        "min": 2.0,
        "max": 2.0,
        "last": 2.0,
        "count": 1.0,
    }


def test_signal_filter_keeps_only_requested_signals() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0, signals=["rpm"]))
    agg.add(packet(0.0, {"rpm": 100.0, "temp": 40.0}))

    summary = agg.flush()

    assert summary is not None
    assert set(summary.signals) == {"rpm"}


def test_packet_with_no_matching_signals_does_not_open_a_window() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0, signals=["rpm"]))

    assert agg.add(packet(0.0, {"temp": 40.0})) is None
    assert agg.flush() is None


def test_flush_on_empty_aggregator_returns_none() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    assert agg.flush() is None


def test_flush_resets_state() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    agg.add(packet(0.0, {"v": 1.0}))

    assert agg.flush() is not None
    assert agg.flush() is None


def test_summary_text_is_deterministic_and_says_what_it_is() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    agg.add(packet(0.0, {"a": 1.0, "b": 2.0}))
    agg.add(packet(0.5, {"a": 3.0}))

    summary = agg.flush()

    assert summary is not None
    assert summary.summary == "2 signals, 3 samples in 1.0s window"
    assert summary.anomalies is None
    assert summary.raw_ref is None


def test_multi_device_packets_share_the_window() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=2.0))
    agg.add(packet(0.0, {"v": 1.0}, device="a"))
    agg.add(packet(0.5, {"w": 2.0}, device="b"))

    summary = agg.flush()

    assert summary is not None
    assert set(summary.signals) == {"v", "w"}


def test_backward_reanchor_never_excludes_folded_samples() -> None:
    # Review finding (HIGH): re-anchoring backward after a later sample was folded
    # could emit a window whose [start, end) excluded that sample. A reorder that
    # cannot fit in one window with what's already there is dropped instead.
    agg = WindowAggregator(TelemetryWindow(duration_seconds=1.0))
    assert agg.add(packet(0.9, {"v": 1.0})) is None
    assert agg.add(packet(1.5, {"v": 2.0})) is None  # inside [0.9, 1.9)
    assert agg.add(packet(0.2, {"v": 99.0})) is None  # cannot coexist with 1.5 → dropped
    assert agg.add(packet(1.3, {"v": 3.0})) is None

    summary = agg.add(packet(2.0, {"v": 4.0}))

    assert summary is not None
    assert summary.window_start == T0 + timedelta(seconds=0.9)
    assert summary.window_end == T0 + timedelta(seconds=1.9)
    assert summary.signals["v"]["count"] == 3.0  # 0.9, 1.5, 1.3 — never the 0.2
    assert summary.signals["v"]["last"] == 2.0


def test_unsubscribe_worthy_partial_data_survives_via_flush() -> None:
    agg = WindowAggregator(TelemetryWindow(duration_seconds=10.0))
    agg.add(packet(0.0, {"v": 42.0}))
    summary = agg.flush()
    assert summary is not None
    assert summary.signals["v"]["last"] == 42.0


def test_distinct_signal_names_per_window_are_capped() -> None:
    # Security C3: novel names must not grow state without bound within one window.
    from livebench.telemetry.windowing import MAX_SIGNALS_PER_WINDOW

    agg = WindowAggregator(TelemetryWindow(duration_seconds=60.0))
    for i in range(MAX_SIGNALS_PER_WINDOW + 500):
        agg.add(packet(0.001 * i, {f"sig{i:05d}": 1.0}))

    summary = agg.flush()

    assert summary is not None
    assert len(summary.signals) == MAX_SIGNALS_PER_WINDOW


def test_frozen_timestamp_cannot_hold_a_window_open_forever() -> None:
    # Security C3: timestamps are attacker-supplied; a constant timestamp must
    # still force a flush once the sample budget is spent.
    from livebench.telemetry.windowing import MAX_SAMPLES_PER_WINDOW

    agg = WindowAggregator(TelemetryWindow(duration_seconds=60.0))
    closed = []
    for _ in range(MAX_SAMPLES_PER_WINDOW + 10):
        summary = agg.add(packet(0.0, {"v": 1.0}))
        if summary is not None:
            closed.append(summary)

    assert closed  # at least one forced flush happened


def test_absurd_window_durations_are_rejected_at_construction() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="duration"):
        WindowAggregator(TelemetryWindow(duration_seconds=float("inf")))
