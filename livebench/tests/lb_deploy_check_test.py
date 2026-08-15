"""LB-03: post-deploy telemetry check — the loop from flashed code back to the graph."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from livebench.deploy.check import await_post_deploy_telemetry
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class ListSource:
    def __init__(self, device_ids: list[str]) -> None:
        self._ids = device_ids
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        for i, device in enumerate(self._ids):
            yield TelemetryPacket(
                device_id=device, timestamp=T0 + timedelta(seconds=i), values={"v": 1.0}
            )

    async def aclose(self) -> None:
        self.closed = True


async def test_all_expected_devices_seen() -> None:
    source = ListSource(["motor-1", "imu", "motor-1"])

    report = await await_post_deploy_telemetry(
        source, expected_devices=["motor-1", "imu"], max_packets=10
    )

    assert report.ok is True
    assert report.seen == {"motor-1", "imu"}
    assert report.missing == set()


async def test_missing_devices_are_named_not_hidden() -> None:
    source = ListSource(["imu"])

    report = await await_post_deploy_telemetry(
        source, expected_devices=["imu", "motor-2"], max_packets=5
    )

    assert report.ok is False
    assert report.missing == {"motor-2"}
