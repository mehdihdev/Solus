"""Real loopback datagram -> existing UDP channel -> existing JSON-lines packet source."""

import asyncio
import socket
import uuid

from livebench.hardware.network import UdpChannel, UdpParams
from livebench.plugins.jsonlines.jsonlines_driver import JsonLinesDriver
from solus_api.hardware.config import (
    FieldProvenance,
    HardwareConfig,
    ProtocolBinding,
    ProvenanceRecord,
    TransportBinding,
    TransportKind,
)
from solus_telemetry.mirror import MethodAdapter, MirrorConfig, mirror


async def test_host_read_reaches_existing_live_packet_source() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.settimeout(0.1)
    binding = TransportBinding(kind=TransportKind.ETHERNET, binding="127.0.0.1")
    channel = UdpChannel(sock, binding, UdpParams(listen_port=port, timeout_s=0.1))
    config = HardwareConfig(
        robot_entity_id=uuid.uuid4(),
        identity=binding,
        protocol=ProtocolBinding(driver_id="json-lines"),
        provenance={
            "identity": ProvenanceRecord(by=FieldProvenance.USER),
            "protocol": ProvenanceRecord(by=FieldProvenance.USER),
        },
    )
    driver = JsonLinesDriver()
    source = driver.open(channel, driver.params_model(), config)

    class Robot:
        def read(self) -> dict[str, float]:
            return {"position": 1.25}

    robot = Robot()
    handle = mirror(
        robot,
        config=MirrorConfig(
            device_id=binding.device_ref,
            port=port,
            methods=(MethodAdapter("read", {"shoulder.position": "position"}),),
            units={"shoulder.position": "rad"},
        ),
    )
    try:
        robot.read()
        packet = await asyncio.wait_for(anext(source.__aiter__()), timeout=2)
        assert packet.device_id == binding.device_ref
        assert packet.values == {"shoulder.position": 1.25}
        assert packet.units == {"shoulder.position": "rad"}
        assert packet.seq == 0
    finally:
        handle.close()
        await source.aclose()
