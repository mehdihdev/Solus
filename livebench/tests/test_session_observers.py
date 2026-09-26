from datetime import UTC, datetime, timedelta

from livebench.anomaly.session import SessionObservers
from solus_api.graph.packet import TelemetryPacket


def packet(
    n: int, value: float = 1, *, device: str = "d", unit: str = "rad", seq: int | None = None
) -> TelemetryPacket:
    return TelemetryPacket(
        device_id=device,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n),
        values={"q": value},
        units={"q": unit},
        seq=seq,
    )


def baseline(observer: SessionObservers, device: str = "d") -> None:
    for n in range(50):
        assert observer.add(packet(n, device=device)) == []


def test_emits_existing_change_point_after_warmup_and_relearns() -> None:
    observer = SessionObservers()
    baseline(observer)
    events = observer.add(packet(50, 5))
    assert len(events) == 1
    assert events[0]["kind"] == "change_point"
    assert events[0]["device_id"] == "d"
    assert events[0]["detail"]["baseline_mean"] == 1
    assert observer.add(packet(51, 5)) == []


def test_devices_sessions_and_units_never_share_baselines() -> None:
    observer = SessionObservers()
    baseline(observer)
    assert observer.add(packet(50, 5, device="other")) == []
    assert SessionObservers().add(packet(50, 5)) == []
    assert observer.add(packet(50, 5, unit="deg")) == []


def test_duplicate_reordered_packets_do_not_change_baseline() -> None:
    observer = SessionObservers()
    for n in range(50):
        observer.add(packet(n, seq=n))
    assert observer.add(packet(51, 999, seq=48)) == []
    assert len(observer.add(packet(52, 5, seq=50))) == 1
    fresh = SessionObservers()
    baseline(fresh)
    assert fresh.add(packet(10, 999)) == []


def test_memory_is_bounded_and_numeric_extremes_do_not_break_ingest() -> None:
    observer = SessionObservers(max_signals=1)
    baseline(observer)
    for n in range(60):
        assert observer.add(packet(n, 5, device="other")) == []
    assert len(observer.add(packet(60, 5))) == 1
    extreme = SessionObservers()
    for n in range(100):
        assert extreme.add(packet(n, 1e308 if n % 2 else -1e308)) == []
