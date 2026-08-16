"""SOLUSDEV-72: the Isaac direct script's pure parts — LB-06 wire building and
the authenticated batch request. The Isaac-side sampling loop runs only under
Isaac's own python and is exercised by the QA pass, not here."""

import json

from livebench.sim.isaac_direct import batch_request, wire_packet
from solus_api.graph.codec import from_wire


def test_wire_packet_decodes_through_the_ratified_codec() -> None:
    wire = wire_packet(
        "scene/joint1", ts_us=1_750_000_000_000_000, values={"qpos": 0.5, "qvel": 1.25}
    )
    packet = from_wire(wire)
    assert packet.device_id == "scene/joint1"
    assert packet.values == {"qpos": 0.5, "qvel": 1.25}
    assert packet.timestamp.tzinfo is not None


def test_batch_request_carries_token_in_header_never_url() -> None:
    packets = [wire_packet("s/j", ts_us=1, values={"v": 1.0})]
    req = batch_request(
        "http://localhost:8000/api/v1",
        project_id="0000-p",
        token="sekret",
        packets=packets,
    )
    assert req.full_url == "http://localhost:8000/api/v1/projects/0000-p/bench/telemetry"
    assert "sekret" not in req.full_url
    assert req.get_header("Authorization") == "Bearer sekret"
    assert req.get_header("Content-type") == "application/json"
    assert isinstance(req.data, bytes)
    body = json.loads(req.data.decode())
    assert body == {"packets": packets}


def test_batch_request_refuses_non_loopback_http() -> None:
    # The token rides this request; plaintext http may only go to loopback.
    import pytest

    with pytest.raises(ValueError):
        batch_request("http://evil.example/api/v1", project_id="p", token="t", packets=[])
    https_req = batch_request("https://api.solus.dev/api/v1", project_id="p", token="t", packets=[])
    assert https_req.full_url.startswith("https://")
