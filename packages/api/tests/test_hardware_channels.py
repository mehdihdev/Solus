"""SOLUSDEV-326 P1-T3: a telemetry channel may name its display range and how it is drawn.

`range {min,max}` is a DISPLAY range (finite, min < max) — never a motion bound — and `display`
is one of plot|angle|orientation|video|scan|points|state|text (default plot, never null). Both
are optional and additive: a default channel dumps exactly as before, so it asks for no new
provenance.
"""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.hardware.config import EntityHardwareConfig, HardwareConfig, TelemetryChannel
from test_hardware_identity_list import USER, _created, _url

PART = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
RANGE = {"min": -90.0, "max": 90.0}


def _component_doc(channel: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "entity_id": str(PART),
        "component": {"telemetry": [channel], "lifecycle": "installed"},
        "provenance": {
            "component.telemetry.0.name": USER,
            "component.lifecycle": USER,
            **provenance,
        },
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"min": 1.0, "max": 1.0},
        {"min": 2.0, "max": 1.0},
        {"min": float("nan"), "max": 1.0},
        {"min": 0.0, "max": float("inf")},
        {"min": 0.0},
        {"min": 0.0, "max": 1.0, "step": 0.1},
    ],
)
def test_a_channel_range_is_finite_and_ordered(bad: dict[str, Any]) -> None:
    good = TelemetryChannel.model_validate({"name": "j.position", "range": RANGE})
    assert good.model_dump(mode="json")["range"] == RANGE
    with pytest.raises(ValidationError):
        TelemetryChannel.model_validate({"name": "j.position", "range": bad})


def test_display_is_one_of_the_known_ways_to_draw_a_channel() -> None:
    for display in ("plot", "angle", "orientation", "video", "scan", "points", "state", "text"):
        assert TelemetryChannel(name="j", display=display).display == display
    for bad in ("sparkline", None):
        with pytest.raises(ValidationError):
            TelemetryChannel.model_validate({"name": "j", "display": bad})
    published = TelemetryChannel.model_json_schema()["properties"]["display"]
    assert published["default"] == "plot" and "anyOf" not in published  # never nullable


def test_a_default_channel_dumps_as_before_and_asks_no_provenance() -> None:
    default = TelemetryChannel(name="j.position", unit="deg")
    assert default.display == "plot" and default.range is None
    assert default.model_dump(mode="json") == {"name": "j.position", "unit": "deg"}
    assert default.presentation() == {}
    explicit = TelemetryChannel(name="j.position", unit="deg", display="plot")
    assert explicit == default and explicit.presentation() == {}
    for channel in ({"name": "j.position"}, {"name": "j.position", "display": "plot"}):
        config = EntityHardwareConfig.model_validate(_component_doc(channel, {}))
        assert config.component is not None
        assert config.component.telemetry[0] == TelemetryChannel(name="j.position")


def test_a_set_display_and_range_need_their_records_and_round_trip() -> None:
    channel = {"name": "j.position", "display": "angle", "range": RANGE}
    with pytest.raises(ValidationError, match="component.telemetry.0.display"):
        EntityHardwareConfig.model_validate(_component_doc(channel, {}))
    records = {
        "component.telemetry.0.display": USER,
        "component.telemetry.0.range": {"by": "library", "source": "def:servo"},
    }
    config = EntityHardwareConfig.model_validate(_component_doc(channel, records))
    assert config.provenance_of("component.telemetry.0.range.min").by.value == "library"
    dumped = config.model_dump(mode="json")
    assert dumped["component"]["telemetry"][0] == {**channel, "unit": None}
    assert EntityHardwareConfig.model_validate(dumped) == config
    assert config.component is not None
    (read,) = config.component.telemetry
    assert read.presentation() == {"display": "angle", "range": RANGE}


def test_the_driver_document_carries_a_parts_channel_display() -> None:
    """The v1 driver input keeps the part's channels whole (the Live Bench reads them there)."""
    document = HardwareConfig.model_validate(
        {
            "robot_entity_id": str(uuid.uuid4()),
            "parts": {
                str(PART): {
                    "telemetry": [{"name": "j.position", "display": "angle", "range": RANGE}]
                }
            },
            "provenance": {"parts": USER},
        }
    )
    assert document.parts[str(PART)].telemetry[0].presentation() == {
        "display": "angle",
        "range": RANGE,
    }


async def test_channel_display_round_trips_through_the_config_route_for_its_team_only(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    part = await _created(client, alice_headers, project, kind="part", name="Wrist")
    channel = {"name": "wrist.position", "unit": "deg", "display": "angle", "range": RANGE}
    document = _component_doc(channel, {"component.telemetry": USER})
    document["entity_id"] = part
    url = _url(project, f"entities/{part}/config")
    current = (await client.get(url, headers=alice_headers)).json()["data"]
    version = str(current["version"])
    for headers, status in (({}, 401), (bob_headers, 404)):
        put = await client.put(
            url, headers={**headers, "If-Match": version}, json={"config": document}
        )
        assert put.status_code == status, put.text
        assert (await client.get(url, headers=headers)).status_code == status
    saved = await client.put(
        url, headers={**alice_headers, "If-Match": version}, json={"config": document}
    )
    assert saved.status_code == 200, saved.text
    read = (await client.get(url, headers=alice_headers)).json()["data"]["config"]
    assert read["component"]["telemetry"] == [channel]
    bad = {**channel, "range": {"min": 5, "max": 5}}
    refused = await client.put(
        url,
        headers={**alice_headers, "If-Match": str(int(version) + 1)},
        json={"config": _component_doc(bad, {"component.telemetry": USER}) | {"entity_id": part}},
    )
    assert refused.status_code == 422, refused.text
