"""External producers are discoverable only from real, validated project traffic."""

from datetime import UTC, datetime
from uuid import uuid4

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.codec import to_wire
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing


def packet(device: str) -> TelemetryPacket:
    return TelemetryPacket(
        device_id=device, timestamp=datetime(2099, 1, 1, tzinfo=UTC), values={"position": 1.0}
    )


async def test_observed_devices_expire_by_server_clock_and_are_isolated() -> None:
    now = [10.0]
    project, other, entity = uuid4(), uuid4(), uuid4()
    plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(),
        DictEntityResolver({(project, "resolved"): entity}),
        clock=lambda: now[0],
    )
    await plumbing.ingest(project, packet("unresolved"))
    await plumbing.ingest(project, packet("resolved"))
    assert plumbing.observed_device_ids(project) == ["resolved", "unresolved"]
    assert plumbing.observed_device_ids(other) == []
    now[0] = 24.0
    await plumbing.ingest(project, packet("resolved"))
    now[0] = 25.0
    assert plumbing.observed_device_ids(project) == ["resolved"]
    now[0] = 39.0
    assert plumbing.observed_device_ids(project) == []


async def test_observed_device_and_project_caps_recover_after_expiry() -> None:
    now = [0.0]
    plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(), DictEntityResolver({}), clock=lambda: now[0]
    )
    project = uuid4()
    for i in range(130):
        await plumbing.ingest(project, packet(f"device-{i:03}"))
    assert len(plumbing.observed_device_ids(project)) == 128
    assert "device-129" not in plumbing.observed_device_ids(project)
    for _ in range(255):
        await plumbing.ingest(uuid4(), packet("device"))
    overflow = uuid4()
    await plumbing.ingest(overflow, packet("device"))
    assert plumbing.observed_device_ids(overflow) == []
    now[0] = 15.0
    await plumbing.ingest(overflow, packet("device"))
    assert plumbing.observed_device_ids(overflow) == ["device"]
    assert plumbing.observed_device_ids(project) == []


async def test_discovery_route_validates_packets_and_project_access(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    base = f"/api/v1/projects/{project['id']}/bench"
    response = await client.post(
        f"{base}/telemetry",
        headers=alice_headers,
        json={"packets": [to_wire(packet("leader")), {"device_id": "bad"}]},
    )
    assert response.json()["data"]["rejected"] == 1
    response = await client.get(f"{base}/telemetry-devices", headers=alice_headers)
    assert response.status_code == 200
    assert response.json()["data"] == {"device_ids": ["leader"]}
    assert (await client.get(f"{base}/telemetry-devices", headers=bob_headers)).status_code == 404
    assert (await client.get(f"{base}/telemetry-devices")).status_code == 401
