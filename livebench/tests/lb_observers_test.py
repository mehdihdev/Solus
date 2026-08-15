"""LB-02: edge observers — rolling threshold, CUSUM change-point, stream-gap watchdog."""

from datetime import UTC, datetime, timedelta

from livebench.anomaly.observers import (
    CusumObserver,
    GapWatchdog,
    ObserverEvent,
    ThresholdObserver,
)
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def packet(
    sec: float, value: float, *, signal: str = "temp", device: str = "dev"
) -> TelemetryPacket:
    return TelemetryPacket(
        device_id=device, timestamp=T0 + timedelta(seconds=sec), values={signal: value}
    )


class TestThresholdObserver:
    def test_breach_fires_with_signal_and_context(self) -> None:
        obs = ThresholdObserver(signal="temp", high=80.0)

        events = obs.add(packet(0.0, 95.0))

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ObserverEvent)
        assert event.kind == "threshold_breach"
        assert event.device_id == "dev"
        assert event.signal == "temp"
        assert event.value == 95.0
        assert event.at == T0
        assert event.detail["high"] == 80.0

    def test_within_bounds_is_silent(self) -> None:
        obs = ThresholdObserver(signal="temp", low=0.0, high=80.0)
        assert obs.add(packet(0.0, 40.0)) == []

    def test_low_bound_fires(self) -> None:
        obs = ThresholdObserver(signal="temp", low=10.0)
        events = obs.add(packet(0.0, 3.0))
        assert [e.kind for e in events] == ["threshold_breach"]

    def test_fires_once_per_excursion_not_per_sample(self) -> None:
        obs = ThresholdObserver(signal="temp", high=80.0)

        fired = []
        for i, value in enumerate([90.0, 91.0, 92.0, 50.0, 95.0]):
            fired.extend(obs.add(packet(float(i), value)))

        # One event entering the first excursion, one entering the second.
        assert len(fired) == 2

    def test_smoothing_window_ignores_a_single_spike(self) -> None:
        obs = ThresholdObserver(signal="temp", high=80.0, smoothing=3)

        fired = []
        for i, value in enumerate([50.0, 200.0, 50.0, 50.0]):  # one spike, mean stays low
            fired.extend(obs.add(packet(float(i), value)))

        assert fired == []

    def test_smoothing_window_catches_a_sustained_shift(self) -> None:
        obs = ThresholdObserver(signal="temp", high=80.0, smoothing=3)

        fired = []
        for i, value in enumerate([50.0, 100.0, 100.0, 100.0]):
            fired.extend(obs.add(packet(float(i), value)))

        assert len(fired) == 1

    def test_other_signals_are_ignored(self) -> None:
        obs = ThresholdObserver(signal="temp", high=80.0)
        assert obs.add(packet(0.0, 500.0, signal="rpm")) == []


class TestCusumObserver:
    def test_baseline_is_silent_then_step_change_fires(self) -> None:
        obs = CusumObserver(signal="temp", baseline_samples=20, slack=0.5, decision=5.0)
        fired: list[ObserverEvent] = []

        # Stationary baseline: deterministic alternating noise around 50.
        for i in range(20):
            fired.extend(obs.add(packet(i * 0.1, 50.0 + (0.1 if i % 2 else -0.1))))
        assert fired == []

        # Step change: mean jumps to 53.
        for i in range(20, 40):
            fired.extend(obs.add(packet(i * 0.1, 53.0 + (0.1 if i % 2 else -0.1))))

        assert len(fired) >= 1
        event = fired[0]
        assert event.kind == "change_point"
        assert event.signal == "temp"
        assert event.detail["direction"] == "up"

    def test_stationary_stream_never_fires(self) -> None:
        obs = CusumObserver(signal="temp", baseline_samples=20, slack=0.5, decision=5.0)
        fired: list[ObserverEvent] = []

        for i in range(200):
            fired.extend(obs.add(packet(i * 0.1, 50.0 + (0.1 if i % 2 else -0.1))))

        assert fired == []

    def test_downward_shift_reports_direction_down(self) -> None:
        obs = CusumObserver(signal="temp", baseline_samples=20, slack=0.5, decision=5.0)
        fired: list[ObserverEvent] = []

        for i in range(20):
            fired.extend(obs.add(packet(i * 0.1, 50.0 + (0.1 if i % 2 else -0.1))))
        for i in range(20, 40):
            fired.extend(obs.add(packet(i * 0.1, 46.0 + (0.1 if i % 2 else -0.1))))

        assert fired and fired[0].detail["direction"] == "down"

    def test_resets_after_firing_and_can_fire_again(self) -> None:
        obs = CusumObserver(signal="temp", baseline_samples=10, slack=0.5, decision=4.0)
        fired: list[ObserverEvent] = []

        for i in range(10):
            fired.extend(obs.add(packet(i * 0.1, 50.0)))
        for i in range(10, 30):
            fired.extend(obs.add(packet(i * 0.1, 55.0)))
        first_count = len(fired)
        for i in range(30, 60):
            fired.extend(obs.add(packet(i * 0.1, 62.0)))

        assert first_count >= 1
        assert len(fired) > first_count  # fired again on the second shift

    def test_constant_baseline_with_zero_variance_does_not_crash(self) -> None:
        obs = CusumObserver(signal="temp", baseline_samples=5, slack=0.5, decision=4.0)
        fired: list[ObserverEvent] = []

        for i in range(5):
            fired.extend(obs.add(packet(i * 0.1, 50.0)))
        fired.extend(obs.add(packet(0.6, 50.0)))  # identical value after baseline

        assert fired == []


class TestGapWatchdog:
    def test_silent_device_fires_a_gap_event_with_attribution(self) -> None:
        dog = GapWatchdog(timeout_seconds=1.0)
        dog.add(packet(0.0, 50.0))

        events = dog.tick(now=T0 + timedelta(seconds=2.5))

        assert len(events) == 1
        assert events[0].kind == "stream_gap"
        assert events[0].device_id == "dev"
        assert events[0].signal == "temp"
        assert events[0].detail["last_seen_seconds"] >= 2.5

    def test_active_device_is_silent(self) -> None:
        dog = GapWatchdog(timeout_seconds=1.0)
        dog.add(packet(0.0, 50.0))

        assert dog.tick(now=T0 + timedelta(seconds=0.5)) == []

    def test_gap_fires_once_until_the_stream_resumes(self) -> None:
        dog = GapWatchdog(timeout_seconds=1.0)
        dog.add(packet(0.0, 50.0))

        first = dog.tick(now=T0 + timedelta(seconds=2.0))
        second = dog.tick(now=T0 + timedelta(seconds=3.0))
        dog.add(packet(4.0, 50.0))  # stream resumes
        third = dog.tick(now=T0 + timedelta(seconds=6.0))

        assert len(first) == 1
        assert second == []
        assert len(third) == 1  # a NEW gap after resumption fires again
