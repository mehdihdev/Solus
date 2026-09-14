"""Measured revolute offsets preserve poses for the verified antiparallel case."""

import copy

import pytest
from solus_api.connectors import onshape_mate_offsets as subject
from solus_api.connectors.contracts import ConnectorError

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def root(separation=0.0019):
    result = {"features": [], "occurrences": []}
    for name, z, sign in (("first", 0, 1), ("second", separation, -1)):
        result["occurrences"].append({"path": [name], "transform": IDENTITY[:]})
        result["features"].append(
            {
                "id": name,
                "featureType": "mateConnector",
                "suppressed": False,
                "featureData": {
                    "occurrence": [name],
                    "mateConnectorCS": {
                        "origin": [0, 0, z],
                        "xAxis": [1, 0, 0],
                        "yAxis": [0, sign, 0],
                        "zAxis": [0, 0, sign],
                    },
                },
            }
        )
    return result


@pytest.mark.parametrize("separation", [-0.01, -0.00188, 0.0019, 0.01])
def test_measured_offset_sign_and_reversed_order(separation):
    value = root(separation)
    forward = subject.measure_revolute_offset(value, "first", "second", -separation)
    assert forward["measured_offset_m"] == -separation
    assert forward["applied_offset_m"] == -separation
    assert forward["first_occurrence_path"] == ["first"]
    assert forward["second_frame"]["axis"] == [0, 0, -1]
    # Reversing order also reverses first Z: the signed scalar stays the same.
    reverse = subject.measure_revolute_offset(value, "second", "first", -separation)
    assert reverse["applied_offset_m"] == -separation


def test_rotated_occurrences_use_actual_world_frames():
    value = root()
    transform = [1, 0, 0, 0.1, 0, 0, -1, 0.2, 0, 1, 0, 0.3, 0, 0, 0, 1]
    for occurrence in value["occurrences"]:
        occurrence["transform"] = transform[:]
    result = subject.measure_revolute_offset(value, "first", "second", -0.0019)
    assert result["first_frame"]["origin"] == pytest.approx([0.1, 0.2, 0.3])
    assert result["second_frame"]["origin"] == pytest.approx([0.1, 0.1981, 0.3])
    assert result["applied_offset_m"] == pytest.approx(-0.0019)


def test_none_preserves_zero_offset_contract():
    assert (
        subject.measure_revolute_offset(root(0), "first", "second", None)["applied_offset_m"] == 0
    )
    with pytest.raises(ConnectorError):
        subject.measure_revolute_offset(root(), "first", "second", None)


@pytest.mark.parametrize(
    "requested", [True, False, float("nan"), float("inf"), -501, 501, "0.0019", 0.0019]
)
def test_invalid_or_disagreeing_requested_offset_refuses(requested):
    with pytest.raises(ConnectorError):
        subject.measure_revolute_offset(root(), "first", "second", requested)


@pytest.mark.parametrize("fault", ["perpendicular", "lateral", "missing", "self", "nonleaf"])
def test_unverified_geometry_refuses(fault):
    value = root()
    data = value["features"][1]["featureData"]
    if fault == "perpendicular":
        data["mateConnectorCS"]["yAxis"] = [0, 0, 1]
        data["mateConnectorCS"]["zAxis"] = [0, -1, 0]
    elif fault == "lateral":
        data["mateConnectorCS"]["origin"][0] = 0.001
    elif fault == "missing":
        del data["mateConnectorCS"]
    elif fault == "self":
        data["occurrence"] = ["first"]
    else:
        value["occurrences"].append({"path": ["first", "child"], "transform": IDENTITY[:]})
    with pytest.raises(ConnectorError):
        subject.measure_revolute_offset(value, "first", "second", -0.0019)


@pytest.mark.parametrize("separation", [-0.009, 0, 0.009])
def test_same_direction_axes_require_no_primary_flip(separation):
    value = root(separation)
    cs = value["features"][1]["featureData"]["mateConnectorCS"]
    cs.update(yAxis=[0, 1, 0], zAxis=[0, 0, 1])
    result = subject.measure_revolute_offset(value, "first", "second", -separation)
    assert result["primary_axis_alignment"] is False
    assert result["applied_offset_m"] == -separation
    reverse = subject.measure_revolute_offset(value, "second", "first", separation)
    assert reverse["applied_offset_m"] == separation


def test_opposite_axes_require_primary_flip():
    result = subject.measure_revolute_offset(root(), "first", "second", -0.0019)
    assert result["primary_axis_alignment"] is True


@pytest.mark.parametrize("fault", ["pose", "missing", "added", "invalid"])
def test_postwrite_pose_mismatch_is_uncertain(fault):
    before = root()
    after = copy.deepcopy(before)
    if fault == "pose":
        after["occurrences"][1]["transform"][3] += 0.001
    elif fault == "missing":
        after["occurrences"].pop()
    elif fault == "added":
        after["occurrences"].append({"path": ["third"], "transform": IDENTITY[:]})
    else:
        after["occurrences"][0]["transform"][0] = float("nan")
    with pytest.raises(ConnectorError) as error:
        subject.verify_revolute_poses(before, after)
    assert error.value.code == "mutation_unverified"


def test_unchanged_complete_pose_set_passes():
    before = root()
    assert subject.verify_revolute_poses(before, copy.deepcopy(before)) is None


@pytest.mark.parametrize("fault", ["features", "duplicate", "path"])
def test_missing_or_ambiguous_connector_identity_refuses(fault):
    value = root()
    if fault == "features":
        value["features"] = None
    elif fault == "duplicate":
        value["features"].append(copy.deepcopy(value["features"][0]))
    else:
        value["features"][0]["featureData"]["occurrence"] = None
    with pytest.raises(ConnectorError):
        subject.measure_revolute_offset(value, "first", "second", -0.0019)


def test_matching_request_uses_exact_measurement_not_requested_approximation():
    result = subject.measure_revolute_offset(root(), "first", "second", -0.001900000001)
    assert result["applied_offset_m"] == -0.0019


@pytest.mark.parametrize("separation", [-500, 500])
def test_native_offset_boundary_is_supported(separation):
    assert (
        subject.measure_revolute_offset(root(separation), "first", "second", -separation)[
            "applied_offset_m"
        ]
        == -separation
    )


def test_nested_leaf_paths_are_returned_without_losing_ancestors():
    value = root()
    for row in value["occurrences"]:
        row["path"] = ["assembly", *row["path"]]
    for row in value["features"]:
        row["featureData"]["occurrence"] = ["assembly", *row["featureData"]["occurrence"]]
    result = subject.measure_revolute_offset(value, "first", "second", -0.0019)
    assert result["first_occurrence_path"] == ["assembly", "first"]
    assert result["second_occurrence_path"] == ["assembly", "second"]
