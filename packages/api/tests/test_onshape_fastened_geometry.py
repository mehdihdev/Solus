"""Rigid mate alignment must preserve full observed bases, not only Z axes."""

import math

import pytest
from solus_api.connectors import onshape_fastened_geometry as subject
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_circle_geometry import _connector_frame
from test_onshape_mate_offsets import IDENTITY, root


@pytest.mark.parametrize(
    "angle,expected",
    [(0, "PLUS_X"), (math.pi, "MINUS_X"), (-math.pi / 2, "MINUS_Y"), (math.pi / 2, "PLUS_Y")],
)
def test_selects_only_pose_preserving_secondary_axis(angle, expected):
    value = root(0)
    cs = value["features"][1]["featureData"]["mateConnectorCS"]
    cs["xAxis"] = [math.cos(angle), math.sin(angle), 0]
    cs["yAxis"] = [math.sin(angle), -math.cos(angle), 0]
    result = subject.measure_fastened(value, "first", "second")
    assert result["secondary_axis_alignment"] == expected
    assert result["first_frame"]["x_axis"] == [1, 0, 0]
    assert result["second_occurrence_path"] == ["second"]


def test_existing_frame_shape_is_unchanged_without_opt_in():
    assert set(_connector_frame(root(0), "first", "first")) == {"origin", "axis"}
    assert set(_connector_frame(root(0), "first", "first", include_basis=True)) == {
        "origin",
        "axis",
        "x_axis",
        "y_axis",
    }


@pytest.mark.parametrize(
    "fault",
    ["rotation", "offset", "parallel", "reflected", "nonfinite", "same_leaf", "nonleaf", "missing"],
)
def test_unverified_rigid_pose_refuses(fault):
    value = root(0)
    cs = value["features"][1]["featureData"]["mateConnectorCS"]
    if fault == "rotation":
        angle = 0.3
        cs["xAxis"] = [math.cos(angle), math.sin(angle), 0]
        cs["yAxis"] = [math.sin(angle), -math.cos(angle), 0]
    elif fault == "offset":
        cs["origin"][2] = 0.001
    elif fault == "parallel":
        cs["zAxis"] = [0, 0, 1]
        cs["yAxis"] = [0, 1, 0]
    elif fault == "reflected":
        cs["yAxis"] = [0, 1, 0]
    elif fault == "nonfinite":
        cs["xAxis"][0] = float("nan")
    elif fault == "same_leaf":
        value["features"][1]["featureData"]["occurrence"] = ["first"]
    elif fault == "nonleaf":
        value["occurrences"].append({"path": ["first", "child"], "transform": IDENTITY[:]})
    else:
        del cs["xAxis"]
    with pytest.raises(ConnectorError):
        subject.measure_fastened(value, "first", "second")


def test_common_world_rotation_preserves_alignment_selection():
    value = root(0)
    transform = [0, -1, 0, 0.1, 1, 0, 0, 0.2, 0, 0, 1, 0.3, 0, 0, 0, 1]
    for occurrence in value["occurrences"]:
        occurrence["transform"] = transform[:]
    result = subject.measure_fastened(value, "first", "second")
    assert result["secondary_axis_alignment"] == "PLUS_X"
    assert result["first_frame"]["x_axis"] == [0, 1, 0]
