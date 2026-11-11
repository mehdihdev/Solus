"""SOLUSDEV-322 P6-T2 — `simulation/mjcf_compile.py`: the generated URDF compiled by the physics
engine in a child process, saved back as MJCF and post-processed (compiler attrs, `pos` + `euler`
only) until `scene/parser.parse_model` accepts it. The engine tests skip where it is not installed;
the post-processing is pure and always runs.
"""

from __future__ import annotations

import math

import pytest
from solus_api.livebench.scene.parser import parse_model
from solus_api.simulation.mjcf_compile import (
    MjcfCompileError,
    compile_mjcf,
    postprocess,
    quat_to_euler,
)
from test_urdf_writer import two_link_model

SAVED = b"""<mujoco model="two_link">
  <compiler angle="radian"/>
  <asset>
    <mesh name="base" content_type="model/stl" file="meshes/base.stl"/>
    <mesh name="arm" content_type="model/stl" file="meshes/arm.stl"/>
  </asset>
  <worldbody>
    <body name="base">
      <geom type="mesh" contype="0" conaffinity="0" group="1" density="0" mesh="base"/>
      <body name="arm" pos="0 0 0.05" quat="0.988771 0 0 0.149438">
        <inertial pos="0 0 0.1" mass="0.42" diaginertia="0.001 0.001 0.0005"/>
        <joint name="elbow" pos="0 0 0" axis="0 0 1" range="-1.57 1.57"/>
        <geom type="mesh" contype="0" conaffinity="0" group="1" density="0" mesh="arm"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


def test_mjcf_compiles_from_urdf_and_parse_model_accepts_it() -> None:
    pytest.importorskip("mujoco")
    model, meshes = two_link_model()
    from solus_api.simulation.urdf_writer import write_urdf

    mjcf = compile_mjcf(write_urdf(model), meshes)

    assert b"quat=" not in mjcf and b'angle="radian"' in mjcf
    parsed = parse_model(mjcf, "mjcf", meshes)
    assert [link["name"] for link in parsed["links"]] == ["base", "arm"]
    (joint,) = parsed["joints"]
    assert (joint["name"], joint["type"], joint["parent"], joint["child"]) == (
        "elbow",
        "revolute",
        "base",
        "arm",
    )
    assert joint["xyz"] == pytest.approx([0.0, 0.0, 0.05])
    assert (joint["lower"], joint["upper"]) == (-1.57, 1.57)
    assert len(parsed["meshes"]) == 2


def test_a_urdf_the_engine_cannot_build_is_a_compile_error_not_a_crash() -> None:
    pytest.importorskip("mujoco")
    with pytest.raises(MjcfCompileError, match="elbow|limit|joint|link"):
        compile_mjcf(
            b'<robot name="r"><link name="a"/><link name="b"/>'
            b'<joint name="elbow" type="revolute"><parent link="a"/><child link="nowhere"/>'
            b'<axis xyz="0 0 1"/><limit lower="-1" upper="1"/></joint></robot>',
            {},
        )


def test_postprocess_turns_quat_into_euler_and_pins_the_compiler_attrs() -> None:
    _, meshes = two_link_model()

    result = postprocess(SAVED)

    assert b"quat=" not in result
    parsed = parse_model(result, "mjcf", meshes)
    (joint,) = parsed["joints"]
    # 0.3 rad about z in the saved quaternion; URDF rpy of the body's pose.
    assert joint["rpy"] == pytest.approx([0.0, 0.0, 0.3], abs=1e-5)
    assert parsed["links"][1]["visuals"][0]["kind"] == "mesh"
    assert b'coordinate="local"' in result and b'eulerseq="xyz"' in result


def test_postprocess_refuses_what_it_cannot_express() -> None:
    with pytest.raises(MjcfCompileError):
        postprocess(SAVED.replace(b'quat="0.988771 0 0 0.149438"', b'axisangle="0 0 1 0.3"'))
    with pytest.raises(MjcfCompileError):
        postprocess(b"<!DOCTYPE x><mujoco/>")
    with pytest.raises(MjcfCompileError):
        compile_mjcf(b"<robot/>", {"../escape.stl": b""})


def test_quat_to_euler_is_the_intrinsic_xyz_the_parser_reads() -> None:
    half = 0.3 / 2
    assert quat_to_euler((math.cos(half), 0.0, 0.0, math.sin(half))) == pytest.approx(
        (0.0, 0.0, 0.3)
    )
    assert quat_to_euler((math.cos(half), math.sin(half), 0.0, 0.0)) == pytest.approx(
        (0.3, 0.0, 0.0)
    )
    assert quat_to_euler((math.cos(half), 0.0, math.sin(half), 0.0)) == pytest.approx(
        (0.0, 0.3, 0.0)
    )
    assert quat_to_euler((1.0, 0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)


def test_the_unknown_effort_sentinel_leaves_no_actuator_force_range_in_the_mjcf() -> None:
    """URDF's `effort="-1"` is SDF's "not enforced"; the engine would read it as a ±1 clamp, so the
    hint pass hands the engine its own "no limit" (0). A known effort stays a real range."""
    pytest.importorskip("mujoco")
    model, meshes = two_link_model()
    from solus_api.simulation.urdf_writer import GeneratedJoint, GeneratedModel, write_urdf

    assert b"actuatorfrcrange" not in compile_mjcf(write_urdf(model), meshes)
    known = GeneratedJoint(**{**model.joints[0].__dict__, "effort_nm": 10.0})
    mjcf = compile_mjcf(write_urdf(GeneratedModel(model.name, model.links, (known,))), meshes)
    assert b'actuatorfrcrange="-10 10"' in mjcf
