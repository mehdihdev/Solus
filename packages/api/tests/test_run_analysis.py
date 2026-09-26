"""Synthetic recordings prove evidence sufficiency, alignment and bounded parsing."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError


def manifest(*, current=True, clamp=90.0):
    from solus_api.livebench.runs.models import RunManifest

    robot, part = uuid4(), uuid4()
    start = datetime(2026, 9, 14, tzinfo=UTC)
    return RunManifest.model_validate(
        {
            "schema_version": 1,
            "robot_id": str(robot),
            "started_at": start,
            "parts": [
                {
                    "entity_id": str(part),
                    "name": "Fixture joint",
                    "device_id": "fixture/joint",
                    "current_signal": "current",
                    "position_signal": "position",
                    "command_signal": "command",
                    "stall_current_a": 2.0,
                    "position_min": -90,
                    "position_max": clamp,
                    "position_unit": "deg",
                    "code_site": "control.py:12",
                    "cad_revision": "fixture-r1",
                }
            ],
            "packets": [
                {
                    "device_id": "fixture/joint",
                    "timestamp": start + timedelta(seconds=n),
                    "values": {
                        "position": 0,
                        "command": 100,
                        **({"current": 2.1} if current else {"load": 99}),
                    },
                    "units": {
                        "position": "deg",
                        "command": "deg",
                        **({"current": "A"} if current else {"load": "%"}),
                    },
                }
                for n in range(3)
            ],
        }
    )


def test_stall_requires_measured_current_and_graph_rating():
    from solus_api.livebench.runs.analysis import findings

    result = findings(manifest())
    assert len(result["findings"]) == 1
    card = result["findings"][0]
    assert "Fixture joint" in card["headline"]
    assert card["evidence"]["stall_current_a"] == 2.0
    assert card["evidence"]["commanded_max"] == 100
    assert card["code_site"] == "control.py:12"
    absent = findings(manifest(current=False))
    assert absent["findings"] == []
    assert absent["insufficient"]


def test_compare_aligns_elapsed_time_and_attributes_supported_clamp():
    from solus_api.livebench.runs.analysis import compare

    before = manifest()
    after = before.model_copy(deep=True)
    after.parts[0].position_max = 45
    after.packets = [
        packet.model_copy(
            update={
                "timestamp": packet.timestamp + timedelta(hours=1),
                "values": {**packet.values, "position": 45},
            }
        )
        for packet in after.packets
    ]
    result = compare(before, after)
    assert result["config_changes"]
    assert result["divergences"]
    assert result["divergences"][0]["aligned_samples"] == 3
    # A changed bound alone is not proof of a clamp: commands exceed both,
    # but baseline measurements at zero did not follow its bound.
    assert result["clamp_attributions"] == []


def test_load_percent_cannot_be_interpreted_as_amperes():
    from solus_api.livebench.runs.analysis import findings

    run = manifest()
    for packet in run.packets:
        packet.units["current"] = "%"
    assert findings(run)["findings"] == []


def test_manifest_rejects_nonfinite_unknown_fields_and_oversized_bytes():
    from solus_api.livebench.runs.models import parse_manifest

    with pytest.raises(ValueError):
        parse_manifest(b" " * (8 * 1024 * 1024 + 1))
    data = manifest().model_dump(mode="json")
    data["surprise"] = True
    from solus_api.livebench.runs.models import RunManifest

    with pytest.raises(ValidationError):
        RunManifest.model_validate(data)
    data.pop("surprise")
    data["packets"][0]["values"]["current"] = float("nan")
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data)


def test_changed_clamp_attribution_requires_both_observed_bounds():
    from solus_api.livebench.runs.analysis import compare

    before = manifest()
    after = before.model_copy(deep=True)
    after.parts[0].position_max = 45
    for packet in before.packets:
        packet.values["position"] = 90
    for packet in after.packets:
        packet.values["position"] = 45
    result = compare(before, after)
    assert len(result["clamp_attributions"]) == 1
    assert result["clamp_attributions"][0]["after_limit"] == 45


def test_compare_different_robots_and_unknown_units_are_honest():
    from solus_api.livebench.runs.analysis import compare

    before = manifest()
    with pytest.raises(ValueError):
        compare(before, manifest())
    after = before.model_copy(deep=True)
    for packet in after.packets:
        packet.units.clear()
    result = compare(before, after)
    assert result["divergences"] == []
    assert result["insufficient"]


def test_parse_deep_json_fails_as_invalid_not_server_crash():
    from solus_api.livebench.runs.models import parse_manifest

    with pytest.raises(ValueError):
        parse_manifest(b"[" * 10000 + b"]" * 10000)


def test_comparison_overflow_is_insufficient_and_never_nonfinite():
    from solus_api.livebench.runs.analysis import compare

    before = manifest()
    after = before.model_copy(deep=True)
    for packet in before.packets:
        packet.values["position"] = -1e308
    for packet in after.packets:
        packet.values["position"] = 1e308
    result = compare(before, after)
    import json

    json.dumps(result, allow_nan=False)
    assert result["insufficient"]


def test_manifest_bounds_distinct_signal_space_before_analysis():
    from solus_api.livebench.runs.models import RunManifest

    data = manifest().model_dump(mode="json")
    data["packets"] = [
        {
            **data["packets"][0],
            "device_id": f"device-{n}",
            "values": {f"signal-{i}": 1 for i in range(256)},
            "units": {},
        }
        for n in range(17)
    ]
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data)


def test_stall_window_survives_normal_lead_in_and_out_and_rejects_repeated_time():
    from solus_api.livebench.runs.analysis import findings

    run = manifest()
    normal = run.packets[0].model_copy(
        update={
            "timestamp": run.started_at - timedelta(seconds=1),
            "values": {"current": 0.2, "position": -10, "command": -10},
        }
    )
    after = normal.model_copy(update={"timestamp": run.started_at + timedelta(seconds=3)})
    run.packets = [normal, *run.packets, after]
    result = findings(run)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["evidence"]["window_start"] == run.started_at.isoformat()
    repeated = manifest()
    repeated.packets = [repeated.packets[0]] * 3
    assert findings(repeated)["findings"] == []


def test_committed_synthetic_pair_has_supported_clamp_evidence():
    from pathlib import Path

    from solus_api.livebench.runs.analysis import compare, findings
    from solus_api.livebench.runs.models import parse_manifest

    root = Path(__file__).parent / "fixtures" / "bench_runs"
    before = parse_manifest((root / "baseline.json").read_bytes())
    after = parse_manifest((root / "clamp.json").read_bytes())
    assert len(compare(before, after)["clamp_attributions"]) == 1
    assert findings(after)["findings"][0]["evidence"]["stall_current_a"] == 2


def test_moving_prismatic_joint_is_not_stationary_in_metre_units():
    from solus_api.livebench.runs.analysis import findings

    run = manifest()
    run.parts[0].position_unit = "m"
    for index, packet in enumerate(run.packets):
        packet.units.update(position="m", command="m")
        packet.values.update(position=index * 0.2, command=1.0)
    assert findings(run)["findings"] == []


def test_unknown_position_dimension_requires_more_evidence():
    from solus_api.livebench.runs.analysis import findings

    run = manifest()
    run.parts[0].position_unit = "count"
    for packet in run.packets:
        packet.units.update(position="count", command="count")
    assert findings(run)["findings"] == []
    assert findings(run)["insufficient"]
