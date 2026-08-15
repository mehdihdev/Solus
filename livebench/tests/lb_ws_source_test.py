"""LB-02: WS packet source — a robot pushing LB-06 frames (msgpack binary / JSON text)."""

import json
from datetime import UTC, datetime

import websockets
from livebench.telemetry.ws_source import WsPacketSource
from solus_api.graph.codec import encode, encode_json
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def test_receives_msgpack_and_json_lb06_frames() -> None:
    p1 = TelemetryPacket(device_id="motor-1", timestamp=T0, values={"rpm": 900.0}, seq=1)
    p2 = TelemetryPacket(device_id="imu", timestamp=T0, values={"ax": 0.25})

    async def robot(ws: websockets.ServerConnection) -> None:
        await ws.send(encode(p1))  # msgpack binary — the throughput form
        await ws.send(encode_json(p2))  # JSON text — the debug form
        await ws.send(b"\x00garbage")  # hostile binary
        await ws.send(json.dumps({"not": "a packet"}))  # non-LB-06 text is dropped here
        await ws.send(encode(p1))

    async with websockets.serve(robot, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        source = WsPacketSource(f"ws://127.0.0.1:{port}")
        received = []
        async for packet in source:
            received.append(packet)
            if len(received) == 3:
                await source.aclose()

    assert received == [p1, p2, p1]


async def test_url_scheme_is_validated() -> None:
    import pytest

    with pytest.raises(ValueError, match="scheme"):
        WsPacketSource("http://robot:1234")
    with pytest.raises(ValueError, match="secret_ref"):
        WsPacketSource("ws://user:pass@robot:1234")
