"""LB-04: fault-induction drills — detection latency, attribution, misses-as-data."""

import os
from datetime import UTC, datetime, timedelta

import serial as pyserial
from livebench.anomaly.observers import CusumObserver, GapWatchdog, ThresholdObserver
from livebench.faults import (
    DrillReport,
    frequency_mismatch_stream,
    run_fault_drill,
    sensor_disconnect_stream,
)
from livebench.telemetry.serial_source import SerialPacketSource
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_sensor_disconnect_is_caught_within_the_latency_bound() -> None:
    packets, fault_at = sensor_disconnect_stream(
        device="imu", signal="ax", rate_hz=50.0, disconnect_after_seconds=2.0, total_seconds=6.0
    )

    report = run_fault_drill(
        packets,
        fault_at=fault_at,
        expected_device="imu",
        expected_signal="ax",
        watchdog=GapWatchdog(timeout_seconds=0.5),
    )

    assert isinstance(report, DrillReport)
    assert report.detected is True
    assert report.latency_seconds is not None and report.latency_seconds <= 1.0
    assert report.attribution_ok is True
    assert report.false_positives == 0


def test_frequency_mismatch_is_caught_by_interval_cusum() -> None:
    packets, fault_at = frequency_mismatch_stream(
        device="lidar",
        signal="range",
        rate_hz=100.0,
        mismatched_rate_hz=20.0,
        change_after_seconds=2.0,
        total_seconds=5.0,
    )

    report = run_fault_drill(
        packets,
        fault_at=fault_at,
        expected_device="lidar",
        expected_signal="range",
        interval_observer=CusumObserver(
            signal="__interval__", baseline_samples=50, slack=0.5, decision=5.0
        ),
    )

    assert report.detected is True
    assert report.latency_seconds is not None and report.latency_seconds <= 1.5
    assert report.attribution_ok is True


def test_a_miss_is_recorded_as_data_not_hidden() -> None:
    packets, fault_at = sensor_disconnect_stream(
        device="imu", signal="ax", rate_hz=50.0, disconnect_after_seconds=2.0, total_seconds=3.0
    )

    # A watchdog slower than the observation window CANNOT catch this — the drill
    # must report the miss plainly, never fail or fabricate a detection.
    report = run_fault_drill(
        packets,
        fault_at=fault_at,
        expected_device="imu",
        expected_signal="ax",
        watchdog=GapWatchdog(timeout_seconds=30.0),
    )

    assert report.detected is False
    assert report.missed is True
    assert report.latency_seconds is None


def test_false_positives_before_the_fault_are_counted() -> None:
    packets, fault_at = sensor_disconnect_stream(
        device="imu", signal="ax", rate_hz=50.0, disconnect_after_seconds=2.0, total_seconds=6.0
    )

    report = run_fault_drill(
        packets,
        fault_at=fault_at,
        expected_device="imu",
        expected_signal="ax",
        watchdog=GapWatchdog(timeout_seconds=0.5),
        # A hair-trigger threshold on healthy data: fires before the fault.
        observers=[ThresholdObserver(signal="ax", high=-1000.0)],
    )

    assert report.detected is True
    assert report.false_positives > 0  # recorded for tuning, not hidden


async def test_real_serial_teardown_is_detected_end_to_end() -> None:
    """A REAL wired-link fault: pyserial on a pty, master closed mid-stream."""
    master, slave = os.openpty()
    port = pyserial.Serial(os.ttyname(slave), baudrate=115200, timeout=0.1)
    os.write(master, b'{"ax": 0.1}\n{"ax": 0.2}\n')

    source = SerialPacketSource(port, max_line_bytes=4096)
    seen: list[TelemetryPacket] = []
    watchdog = GapWatchdog(timeout_seconds=0.5)
    fired = []

    async for packet in source:
        seen.append(packet)
        watchdog.add(packet)
        if len(seen) == 2:
            os.close(master)  # the physical unplug, in kernel form
            os.close(slave)
            await source.aclose()

    last = seen[-1].timestamp
    fired = watchdog.tick(now=last + timedelta(seconds=2.0))

    assert len(seen) == 2
    assert [e.kind for e in fired] == ["stream_gap"]
    assert fired[0].device_id.startswith("serial:")
