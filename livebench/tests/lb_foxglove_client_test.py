"""CON-03: Foxglove WS protocol framing (subscribe-only client) against a mock server."""

import asyncio
import json
import struct

import pytest
import websockets
from livebench.telemetry.foxglove_client import (
    SUBPROTOCOL,
    ChannelInfo,
    FoxgloveClient,
    build_subscribe,
    parse_advertise,
    parse_message_data,
)

ADVERTISE = {
    "op": "advertise",
    "channels": [
        {"id": 1, "topic": "/joints", "encoding": "json", "schemaName": "Joints", "schema": "{}"},
        {"id": 2, "topic": "/cam", "encoding": "protobuf", "schemaName": "Img", "schema": ""},
    ],
}


def message_frame(sub_id: int, log_time_ns: int, payload: bytes) -> bytes:
    return b"\x01" + struct.pack("<IQ", sub_id, log_time_ns) + payload


def test_parse_advertise_keeps_only_json_channels() -> None:
    channels = parse_advertise(ADVERTISE)
    assert channels == [ChannelInfo(id=1, topic="/joints", encoding="json", schema_name="Joints")]


def test_parse_advertise_tolerates_garbage_entries() -> None:
    msg = {"op": "advertise", "channels": [{"nope": True}, "junk", None]}
    assert parse_advertise(msg) == []


def test_build_subscribe_maps_subscription_ids_to_channels() -> None:
    channels = [ChannelInfo(id=5, topic="/a", encoding="json", schema_name="A")]

    text, by_sub_id = build_subscribe(channels)
    body = json.loads(text)

    assert body["op"] == "subscribe"
    assert len(body["subscriptions"]) == 1
    sub = body["subscriptions"][0]
    assert sub["channelId"] == 5
    assert by_sub_id[sub["id"]].topic == "/a"


def test_parse_message_data_extracts_topic_time_payload() -> None:
    subs = {3: ChannelInfo(id=1, topic="/joints", encoding="json", schema_name="J")}
    frame = message_frame(3, 1_700_000_000_000_000_000, b'{"v": 1.0}')

    msg = parse_message_data(frame, subs)

    assert msg is not None
    assert msg.topic == "/joints"
    assert msg.log_time_ns == 1_700_000_000_000_000_000
    assert msg.payload == b'{"v": 1.0}'


@pytest.mark.parametrize(
    "frame",
    [
        b"",  # empty
        b"\x02" + b"\x00" * 12,  # wrong opcode (0x02 is TIME)
        b"\x01\x00\x00",  # truncated header
        message_frame(99, 0, b"{}"),  # unknown subscription id
    ],
)
def test_parse_message_data_rejects_malformed_frames(frame: bytes) -> None:
    subs = {3: ChannelInfo(id=1, topic="/joints", encoding="json", schema_name="J")}
    assert parse_message_data(frame, subs) is None


async def test_client_subscribes_and_yields_messages_from_a_live_server() -> None:
    """Integration: a minimal foxglove_bridge imitation on a real websocket."""
    server_saw: dict[str, object] = {}

    async def bridge(ws: websockets.ServerConnection) -> None:
        assert ws.subprotocol == SUBPROTOCOL
        await ws.send(json.dumps({"op": "serverInfo", "name": "mock", "capabilities": []}))
        await ws.send(json.dumps(ADVERTISE))
        sub_request = json.loads(await ws.recv())
        server_saw["subscribe"] = sub_request
        sub_id = sub_request["subscriptions"][0]["id"]
        await ws.send(message_frame(sub_id, 1_700_000_000_000_000_000, b'{"elbow": 0.5}'))
        await ws.send(message_frame(sub_id, 1_700_000_000_100_000_000, b'{"elbow": 0.6}'))
        await asyncio.sleep(3)  # hold the link open; the client closes first

    async with websockets.serve(
        bridge, "127.0.0.1", 0, subprotocols=[websockets.Subprotocol(SUBPROTOCOL)]
    ) as server:
        port = server.sockets[0].getsockname()[1]
        client = FoxgloveClient(f"ws://127.0.0.1:{port}")
        received = []
        async for message in client.messages():
            received.append(message)
            if len(received) == 2:
                break
        await client.close()

    assert [m.payload for m in received] == [b'{"elbow": 0.5}', b'{"elbow": 0.6}']
    assert all(m.topic == "/joints" for m in received)
    sub_body = server_saw["subscribe"]
    assert isinstance(sub_body, dict)
    assert sub_body["subscriptions"][0]["channelId"] == 1  # only the json channel


async def test_client_ignores_unknown_ops_and_binary_junk() -> None:
    async def bridge(ws: websockets.ServerConnection) -> None:
        await ws.send(json.dumps({"op": "serverInfo", "name": "mock", "capabilities": []}))
        await ws.send(json.dumps({"op": "someFutureThing", "data": 1}))
        await ws.send(b"\x7f\x00\x00")  # unknown binary opcode
        await ws.send(json.dumps(ADVERTISE))
        sub_request = json.loads(await ws.recv())
        sub_id = sub_request["subscriptions"][0]["id"]
        await ws.send(message_frame(sub_id, 42, b'{"v": 1.0}'))
        await asyncio.sleep(3)

    async with websockets.serve(
        bridge, "127.0.0.1", 0, subprotocols=[websockets.Subprotocol(SUBPROTOCOL)]
    ) as server:
        port = server.sockets[0].getsockname()[1]
        client = FoxgloveClient(f"ws://127.0.0.1:{port}")
        received = []
        async for message in client.messages():
            received.append(message)
            break
        await client.close()

    assert received[0].payload == b'{"v": 1.0}'


def test_advertise_flood_is_capped() -> None:
    # Security C4: a hostile bridge advertising endless channels must not grow
    # client state without bound.
    from livebench.telemetry.foxglove_client import MAX_CHANNELS

    channels = [
        {"id": i, "topic": f"/t{i}", "encoding": "json", "schemaName": "S", "schema": ""}
        for i in range(MAX_CHANNELS + 5000)
    ]
    parsed = parse_advertise({"op": "advertise", "channels": channels})

    assert len(parsed) == MAX_CHANNELS


def test_advertise_bounds_topic_length_and_channel_id() -> None:
    msg = {
        "op": "advertise",
        "channels": [
            {"id": 2**40, "topic": "/big-id", "encoding": "json", "schemaName": "S"},
            {"id": 1, "topic": "x" * 600, "encoding": "json", "schemaName": "S"},
            {"id": 2, "topic": "/ok", "encoding": "json", "schemaName": "S"},
        ],
    }
    parsed = parse_advertise(msg)
    assert [c.topic for c in parsed] == ["/ok"]


async def test_deep_nested_control_frame_does_not_kill_the_client() -> None:
    # Security H1: json.loads raises RecursionError (not ValueError) on deep nesting.
    async def bridge(ws: websockets.ServerConnection) -> None:
        await ws.send(b"[" * 100_000)  # hostile text frame
        await ws.send(json.dumps(ADVERTISE))
        sub_request = json.loads(await ws.recv())
        sub_id = sub_request["subscriptions"][0]["id"]
        await ws.send(message_frame(sub_id, 42, b'{"v": 1.0}'))
        await asyncio.sleep(3)

    async with websockets.serve(
        bridge, "127.0.0.1", 0, subprotocols=[websockets.Subprotocol(SUBPROTOCOL)], max_size=None
    ) as server:
        port = server.sockets[0].getsockname()[1]
        client = FoxgloveClient(f"ws://127.0.0.1:{port}", max_frame_bytes=None)
        received = []
        async for message in client.messages():
            received.append(message)
            break
        await client.close()

    assert received[0].payload == b'{"v": 1.0}'
