"""Bounded, non-executing scene geometry normalization."""

import pytest
from solus_api.livebench.scene.parser import parse_model

URDF = (
    b'<robot name="r">'
    b'<link name="base">'
    b"<visual>"
    b"<geometry>"
    b'<box size="1 2 3"/>'
    b"</geometry>"
    b"</visual>"
    b"</link>"
    b'<link name="tip"/>'
    b'<joint name="hinge" type="revolute">'
    b'<parent link="base"/>'
    b'<child link="tip"/>'
    b'<axis xyz="0 1 0"/>'
    b'<limit lower="-1" upper="1"/>'
    b"</joint>"
    b"</robot>"
)


def test_urdf_normalizes_geometry_and_joint():
    result = parse_model(URDF, "urdf")
    assert result["links"][0]["visuals"][0]["size"] == [1, 2, 3]
    assert result["joints"][0]["axis"] == [0, 1, 0]
    assert result["joints"][0]["lower"] == -1


def test_jointless_mesh_is_honest_and_inert():
    result = parse_model(
        (
            b'<robot name="r">'
            b'<link name="base">'
            b"<visual>"
            b"<geometry>"
            b'<mesh filename="file:///private"/>'
            b"</geometry>"
            b"</visual>"
            b"</link>"
            b"</robot>"
        ),
        "urdf",
    )
    assert result["warnings"] and not result["joints"]
    assert "private" not in str(result)


def test_mjcf_nested_bodies():
    result = parse_model(
        (
            b"<mujoco>"
            b'<compiler angle="radian"/>'
            b"<worldbody>"
            b'<body name="base">'
            b'<geom type="sphere" size="0.1"/>'
            b'<body name="tip" pos="0 0 1">'
            b'<joint name="hinge" type="hinge" axis="0 1 0" range="-1 1"/>'
            b"</body>"
            b"</body>"
            b"</worldbody>"
            b"</mujoco>"
        ),
        "mjcf",
    )
    assert result["joints"][0]["child"] == "tip"
    assert result["joints"][0]["xyz"] == [0, 0, 1]


@pytest.mark.parametrize(
    "xml",
    [
        b"<!DOCTYPE robot><robot/>",
        b'<robot><include file="x"/></robot>',
        b'<robot><link name="x"/><link name="x"/></robot>',
        b'<robot><link name="x"/><joint name="j" type="floating"/></robot>',
        (
            b"<robot>"
            b'<link name="x"/>'
            b'<joint name="j" type="fixed">'
            b'<parent link="x"/>'
            b'<child link="x"/>'
            b"</joint>"
            b"</robot>"
        ),
        (
            b"<robot>"
            b'<link name="x">'
            b"<visual>"
            b"<geometry>"
            b'<sphere radius="nan"/>'
            b"</geometry>"
            b"</visual>"
            b"</link>"
            b"</robot>"
        ),
        b"<robot>",
    ],
)
def test_rejects_unsafe_or_malformed(xml):
    with pytest.raises(ValueError):
        parse_model(xml, "urdf")


def test_size_and_depth_caps():
    with pytest.raises(ValueError):
        parse_model(b" " * (1048576 + 1), "urdf")
    with pytest.raises(ValueError):
        parse_model(b"<robot>" + b"<x>" * 40 + b"</x>" * 40 + b"</robot>", "urdf")


@pytest.mark.parametrize(
    "xml",
    [
        (
            b"<mujoco>"
            b'<compiler angle="radian"/>'
            b"<worldbody>"
            b'<body name="base">'
            b'<geom type="cylinder" size="1 2" fromto="0 0 0 1 0 0"/>'
            b"</body>"
            b"</worldbody>"
            b"</mujoco>"
        ),
        (
            b"<mujoco>"
            b'<compiler angle="radian"/>'
            b"<worldbody>"
            b'<body name="base">'
            b'<body name="tip">'
            b'<joint name="j" type="hinge" range="0 1" ref="0.2"/>'
            b"</body>"
            b"</body>"
            b"</worldbody>"
            b"</mujoco>"
        ),
    ],
)
def test_rejects_unimplemented_mjcf_coordinates(xml):
    with pytest.raises(ValueError):
        parse_model(xml, "mjcf")


STL = (
    b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
    b"vertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t"
)


def test_explicit_mesh_bytes_only_and_normalized_output():
    xml = (
        b'<robot name="r">'
        b'<link name="x">'
        b"<visual>"
        b"<geometry>"
        b'<mesh filename="package://arm/a.stl" scale="1 2 3"/>'
        b"</geometry>"
        b"</visual>"
        b"</link>"
        b"</robot>"
    )
    result = parse_model(xml, "urdf", {"package://arm/a.stl": STL})
    visual = result["links"][0]["visuals"][0]
    assert visual["scale"] == [1, 2, 3]
    assert result["meshes"][visual["mesh_key"]]["vertices"] == [0, 0, 0, 1, 0, 0, 0, 1, 0]
    assert "package://" not in str(result)


@pytest.mark.parametrize(
    "content",
    [b"garbage", STL.replace(b"vertex 1", b"vertex nan"), b" " * (8 * 1024 * 1024 + 1)],
    ids=["invalid", "nonfinite", "oversized"],
)
def test_mesh_rejects_malformed_or_excessive(content):
    xml = (
        b'<robot name="r">'
        b'<link name="x">'
        b"<visual>"
        b"<geometry>"
        b'<mesh filename="a.stl"/>'
        b"</geometry>"
        b"</visual>"
        b"</link>"
        b"</robot>"
    )
    with pytest.raises(ValueError):
        parse_model(xml, "urdf", {"a.stl": content})


def test_mesh_does_not_guess_basename():
    xml = (
        b'<robot name="r">'
        b'<link name="x">'
        b"<visual>"
        b"<geometry>"
        b'<mesh filename="package://arm/a.stl"/>'
        b"</geometry>"
        b"</visual>"
        b"</link>"
        b"</robot>"
    )
    with pytest.raises(ValueError):
        parse_model(xml, "urdf", {"a.stl": STL})


def test_binary_stl_and_mjcf_asset_reference():
    import struct

    binary = b"\0" * 80 + struct.pack("<I12fH", 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    xml = (
        b'<mujoco><compiler angle="radian"/><asset>'
        b'<mesh name="shape" file="body.stl" scale="0.1 0.1 0.1"/></asset>'
        b'<worldbody><body name="base"><geom type="mesh" mesh="shape"/>'
        b"</body></worldbody></mujoco>"
    )
    result = parse_model(xml, "mjcf", {"body.stl": binary})
    visual = result["links"][0]["visuals"][0]
    assert visual["scale"] == [0.1, 0.1, 0.1]
    assert len(result["meshes"][visual["mesh_key"]]["vertices"]) == 9


def test_repeated_mesh_instances_respect_triangle_cap(monkeypatch):
    from solus_api.livebench.scene import meshes

    monkeypatch.setattr(meshes, "MAX_TRIANGLES", 1)
    xml = (
        b'<robot name="r"><link name="base">'
        b'<visual><geometry><mesh filename="a.stl"/></geometry></visual>'
        b'<visual><geometry><mesh filename="a.stl"/></geometry></visual>'
        b"</link></robot>"
    )
    with pytest.raises(ValueError):
        parse_model(xml, "urdf", {"a.stl": STL})


def test_mjcf_mixed_axis_rotations_are_normalized_to_urdf_convention():
    import math

    result = parse_model(
        b'<mujoco><compiler angle="radian"/><worldbody><body name="base">'
        b'<body name="tip" euler="0.4 0.5 0.6"><geom type="box" size="1 1 1" '
        b'euler="0.4 0.5 0.6"/></body></body></worldbody></mujoco>',
        "mjcf",
    )
    # MJCF intrinsic xyz is Rx(roll) Ry(pitch) Rz(yaw), unlike URDF fixed axes.
    a, b, c = 0.4, 0.5, 0.6
    expected = [
        math.atan2(
            math.sin(a) * math.cos(c) + math.cos(a) * math.sin(b) * math.sin(c),
            math.cos(a) * math.cos(b),
        ),
        math.asin(math.cos(a) * math.sin(b) * math.cos(c) - math.sin(a) * math.sin(c)),
        math.atan2(
            math.cos(a) * math.sin(c) + math.sin(a) * math.sin(b) * math.cos(c),
            math.cos(b) * math.cos(c),
        ),
    ]
    assert result["joints"][0]["rpy"] == pytest.approx(expected)
    assert result["links"][1]["visuals"][0]["rpy"] == pytest.approx(expected)
