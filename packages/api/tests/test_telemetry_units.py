"""Packet units survive raw recent reads before and after graph resolution."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing


@pytest.mark.parametrize("resolved", [False, True])
async def test_packet_units_are_per_signal_and_per_sample(resolved: bool) -> None:
    project, entity = uuid4(), uuid4()
    resolver = DictEntityResolver({(project, "device"): entity} if resolved else {})
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), resolver)
    for units in [{"position": "rad", "temperature": "degC"}, {"position": "deg"}, {}]:
        await plumbing.ingest(
            project,
            TelemetryPacket(
                device_id="device",
                timestamp=datetime.now(UTC),
                values={"position": 1.0, "temperature": 2.0},
                units=units,
            ),
        )
    view = await plumbing.get_device_recent(project, "device")
    by_signal = {s.signal: s.points for s in view.signals}
    assert [s.unit for s in by_signal["position"]] == ["rad", "deg", None]
    assert [s.unit for s in by_signal["temperature"]] == ["degC", None, None]
    assert [s.value for s in by_signal["position"]] == [1.0, 1.0, 1.0]
    assert view.resolved_entity_id == (entity if resolved else None)
    assert (await plumbing.get_device_recent(uuid4(), "device")).signals == []
    if resolved:
        recent = await plumbing.get_recent_values(project, entity)
        assert recent.signals == view.signals
    limited = await plumbing.get_device_recent(project, "device", limit=1)
    assert all(len(s.points) == 1 and s.points[0].unit is None for s in limited.signals)
    empty = await plumbing.get_device_recent(project, "device", limit=0)
    assert all(s.points == [] for s in empty.signals)


@pytest.mark.parametrize("resolved", [False, True])
async def test_device_recent_rejects_negative_limit_even_without_samples(resolved: bool) -> None:
    project, entity = uuid4(), uuid4()
    plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(),
        DictEntityResolver({(project, "device"): entity} if resolved else {}),
    )
    with pytest.raises(ValueError, match="limit must be non-negative"):
        await plumbing.get_device_recent(project, "device", limit=-1)
