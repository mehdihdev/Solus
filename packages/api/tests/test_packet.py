"""LB-06 telemetry packet + read-shape validation (SOLUS-LNK-06).

Device input is untrusted (CLAUDE.md §7): the packet boundary rejects empty/oversized/
non-finite readings so a malformed or hostile packet never reaches the buffer. The
`RecentValuesView` must stay JSON-serializable so a Foxglove bridge (CON-03) can read it.
"""

import math
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from solus_api.graph.packet import (
    MAX_SIGNAL_NAME_LEN,
    MAX_SIGNALS_PER_PACKET,
    RecentSample,
    RecentValuesView,
    SignalSeries,
    TelemetryPacket,
)

_T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def test_packet_accepts_a_well_formed_reading() -> None:
    pkt = TelemetryPacket(device_id="imu0", timestamp=_T0, values={"accel_x": 0.1, "temp_c": 31.5})
    assert pkt.device_id == "imu0"
    assert pkt.values == {"accel_x": 0.1, "temp_c": 31.5}


def test_packet_rejects_empty_values() -> None:
    with pytest.raises(ValidationError):
        TelemetryPacket(device_id="imu0", timestamp=_T0, values={})


def test_packet_rejects_too_many_signals() -> None:
    values = {f"s{i}": float(i) for i in range(MAX_SIGNALS_PER_PACKET + 1)}
    with pytest.raises(ValidationError):
        TelemetryPacket(device_id="imu0", timestamp=_T0, values=values)


def test_packet_rejects_overlong_signal_name() -> None:
    with pytest.raises(ValidationError):
        TelemetryPacket(
            device_id="imu0", timestamp=_T0, values={"x" * (MAX_SIGNAL_NAME_LEN + 1): 1.0}
        )


def test_packet_rejects_empty_device_id() -> None:
    with pytest.raises(ValidationError):
        TelemetryPacket(device_id="", timestamp=_T0, values={"x": 1.0})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_packet_rejects_non_finite_values(bad: float) -> None:
    with pytest.raises(ValidationError):
        TelemetryPacket(device_id="imu0", timestamp=_T0, values={"x": bad})


def test_packet_rejects_naive_timestamp() -> None:
    """Regression: a naive timestamp is rejected at the boundary so a naive/aware mix can't
    later crash get_telemetry's window comparisons with a TypeError (§7)."""
    with pytest.raises(ValidationError):
        TelemetryPacket(
            device_id="imu0", timestamp=datetime(2026, 7, 5, 12, 0, 0), values={"x": 1.0}
        )


def test_packet_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TelemetryPacket.model_validate(
            {"device_id": "imu0", "timestamp": _T0, "values": {"x": 1.0}, "evil": "1"}
        )


def test_recent_values_view_is_foxglove_serializable() -> None:
    entity = uuid.uuid4()
    view = RecentValuesView(
        entity_id=entity,
        signals=[SignalSeries(signal="rpm", points=[RecentSample(timestamp=_T0, value=1.5)])],
    )
    payload = view.model_dump_json()
    assert '"rpm"' in payload and str(entity) in payload
    # round-trips back to the same shape
    assert RecentValuesView.model_validate_json(payload) == view
