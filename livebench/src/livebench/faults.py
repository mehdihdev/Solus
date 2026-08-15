"""Fault-induction drills (LB-04): prove the detection stack catches real faults.

A drill replays a packet stream with a KNOWN fault at a KNOWN time through the
LB-02 observers and gap watchdog, then reports honestly:

* `detected` + `latency_seconds` + `attribution_ok` — did the right (device,
  signal) fire, and how long after the fault;
* `false_positives` — events before the fault, counted, never discarded;
* `missed` — **a miss is DATA for tuning, not a failure to hide**: the drill
  returns it plainly and the caller decides what to assert.

Event-time throughout (the watchdog ticks on stream timestamps), so a drill is
deterministic and replays identically in CI and against a recorded robot run.

Frequency-mismatch detection derives a `__interval__` pseudo-signal (inter-
arrival seconds per device) and feeds it to a CUSUM observer — a sampling-rate
clash IS a change-point in the arrival intervals.

The physical protocol on a real bench (the repeatable demo script):
run the serial drill against the robot's port, then INDUCE the fault by hand —
unplug the sensor (the pty-teardown test in `lb_faults_test.py` is the same code
path in kernel form). Frequency mismatch: reflash/reconfigure one sensor to a
clashing rate and replay through the same drill.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from solus_api.graph.packet import TelemetryPacket

from livebench.anomaly.observers import CusumObserver, GapWatchdog, ObserverEvent
from livebench.telemetry.observing_source import Observer

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class DrillReport:
    detected: bool
    missed: bool
    latency_seconds: float | None
    attribution_ok: bool
    false_positives: int
    events: list[ObserverEvent]


def sensor_disconnect_stream(
    *,
    device: str,
    signal: str,
    rate_hz: float,
    disconnect_after_seconds: float,
    total_seconds: float,
) -> tuple[list[TelemetryPacket], datetime]:
    """A healthy stream that goes silent at the fault instant (unplugged sensor)."""
    period = 1.0 / rate_hz
    packets = [
        TelemetryPacket(
            device_id=device,
            timestamp=_T0 + timedelta(seconds=i * period),
            values={signal: 0.1 * (i % 7)},
        )
        for i in range(int(disconnect_after_seconds * rate_hz))
    ]
    # A heartbeat device keeps the event-time clock advancing past the fault —
    # in a real robot the OTHER sensors keep streaming while one is unplugged.
    packets += [
        TelemetryPacket(
            device_id="__clock__",
            timestamp=_T0 + timedelta(seconds=disconnect_after_seconds + i * 0.1),
            values={"tick": float(i)},
        )
        for i in range(int((total_seconds - disconnect_after_seconds) * 10))
    ]
    return packets, _T0 + timedelta(seconds=disconnect_after_seconds)


def frequency_mismatch_stream(
    *,
    device: str,
    signal: str,
    rate_hz: float,
    mismatched_rate_hz: float,
    change_after_seconds: float,
    total_seconds: float,
) -> tuple[list[TelemetryPacket], datetime]:
    """A stream whose sampling rate clashes from the fault instant onward."""
    packets: list[TelemetryPacket] = []
    t = 0.0
    i = 0
    while t < total_seconds:
        packets.append(
            TelemetryPacket(
                device_id=device,
                timestamp=_T0 + timedelta(seconds=t),
                values={signal: 0.1 * (i % 5)},
            )
        )
        t += 1.0 / (rate_hz if t < change_after_seconds else mismatched_rate_hz)
        i += 1
    return packets, _T0 + timedelta(seconds=change_after_seconds)


def _interval_packets(packets: Iterable[TelemetryPacket]) -> Iterable[TelemetryPacket]:
    """Derive the `__interval__` pseudo-signal: per-device inter-arrival seconds."""
    last_seen: dict[str, datetime] = {}
    for packet in packets:
        previous = last_seen.get(packet.device_id)
        last_seen[packet.device_id] = packet.timestamp
        yield packet
        if previous is not None:
            interval = (packet.timestamp - previous).total_seconds()
            yield TelemetryPacket(
                device_id=packet.device_id,
                timestamp=packet.timestamp,
                values={"__interval__": interval},
            )


def run_fault_drill(
    packets: Sequence[TelemetryPacket],
    *,
    fault_at: datetime,
    expected_device: str,
    expected_signal: str,
    watchdog: GapWatchdog | None = None,
    observers: Sequence[Observer] = (),
    interval_observer: CusumObserver | None = None,
) -> DrillReport:
    """Replay `packets` through the detection stack and report honestly."""
    events: list[ObserverEvent] = []
    stream = _interval_packets(packets) if interval_observer is not None else iter(packets)
    all_observers: list[Observer] = list(observers)
    if interval_observer is not None:
        all_observers.append(interval_observer)

    for packet in stream:
        for observer in all_observers:
            events.extend(observer.add(packet))
        if watchdog is not None:
            watchdog.add(packet)
            events.extend(watchdog.tick(now=packet.timestamp))

    false_positives = sum(1 for event in events if event.at < fault_at)
    matching = [
        event
        for event in events
        if event.at >= fault_at
        and event.device_id == expected_device
        and (event.signal == expected_signal or event.signal == "__interval__")
    ]
    if not matching:
        return DrillReport(
            detected=False,
            missed=True,
            latency_seconds=None,
            attribution_ok=False,
            false_positives=false_positives,
            events=events,
        )
    first = min(matching, key=lambda event: event.at)
    return DrillReport(
        detected=True,
        missed=False,
        latency_seconds=(first.at - fault_at).total_seconds(),
        attribution_ok=True,
        false_positives=false_positives,
        events=events,
    )
