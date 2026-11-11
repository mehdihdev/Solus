"""SOLUSDEV-322 P6-T2 — `simulation/urdf_writer.py`: a `GeneratedModel` becomes URDF bytes the
scene parser accepts. Pure: no I/O, no engine. Every link frame is world-aligned and sits at the
origin of the joint that moves it, so the placed CAD meshes (assembly frame) are re-expressed
relative to that frame and every joint always carries `<limit lower upper>`.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from solus_api.livebench.scene.parser import parse_model
from solus_api.simulation.urdf_writer import (
    GeneratedJoint,
    GeneratedLink,
    GeneratedModel,
    Inertial,
    stl_bytes,
    uniform_inertia,
    write_urdf,
)

_FACES = (
    (0, 2, 1),
    (0, 3, 2),
    (4, 5, 6),
    (4, 6, 7),
    (0, 1, 5),
    (0, 5, 4),
    (1, 2, 6),
    (1, 6, 5),
    (2, 3, 7),
    (2, 7, 6),
    (3, 0, 4),
    (3, 4, 7),
)


def box_vertices(sx: float, sy: float, sz: float, cz: float = 0.0) -> list[float]:
    """A closed, outward-facing box as the scene's flat triangle soup (metres)."""
    x, y, z0, z1 = sx / 2, sy / 2, cz - sz / 2, cz + sz / 2
    corners = [
        (-x, -y, z0),
        (x, -y, z0),
        (x, y, z0),
        (-x, y, z0),
        (-x, -y, z1),
        (x, -y, z1),
        (x, y, z1),
        (-x, y, z1),
    ]
    return [value for face in _FACES for index in face for value in corners[index]]


def two_link_model() -> tuple[GeneratedModel, dict[str, bytes]]:
    base, arm = box_vertices(0.1, 0.1, 0.05, cz=0.025), box_vertices(0.02, 0.02, 0.2, cz=0.15)
    inertial = uniform_inertia(arm, 0.42)
    assert inertial is not None
    model = GeneratedModel(
        name="two_link",
        links=(
            GeneratedLink(name="base", mesh="meshes/base.stl"),
            GeneratedLink(name="arm", mesh="meshes/arm.stl", inertial=inertial),
        ),
        joints=(
            GeneratedJoint(
                name="elbow",
                type="revolute",
                parent="base",
                child="arm",
                axis=(0.0, 0.0, 1.0),
                origin_m=(0.0, 0.0, 0.05),
                lower=-1.57,
                upper=1.57,
            ),
        ),
    )
    return model, {"meshes/base.stl": stl_bytes(base), "meshes/arm.stl": stl_bytes(arm)}


def test_two_link_fixture_with_mate_frame_yields_one_revolute_joint_urdf_that_parse_model_accepts() -> (  # noqa: E501
    None
):
    model, meshes = two_link_model()

    urdf = write_urdf(model)
    parsed = parse_model(urdf, "urdf", meshes)

    assert [link["name"] for link in parsed["links"]] == ["base", "arm"]
    (joint,) = parsed["joints"]
    assert (joint["name"], joint["type"], joint["parent"], joint["child"]) == (
        "elbow",
        "revolute",
        "base",
        "arm",
    )
    assert joint["axis"] == [0.0, 0.0, 1.0]
    assert joint["xyz"] == [0.0, 0.0, 0.05] and (joint["lower"], joint["upper"]) == (-1.57, 1.57)
    # The arm's mesh is placed in the assembly frame; the link frame sits at the joint, so the
    # visual is shifted back by the joint origin.
    arm = parsed["links"][1]["visuals"][0]
    assert arm["kind"] == "mesh" and arm["xyz"] == pytest.approx([0.0, 0.0, -0.05])
    assert len(parsed["meshes"]) == 2
    assert b"<limit lower=" in urdf and b"<inertial>" in urdf


def test_a_joint_without_limits_cannot_be_written() -> None:
    model, _ = two_link_model()
    joint = model.joints[0]
    with pytest.raises(ValueError, match="limits"):
        GeneratedJoint(**{**joint.__dict__, "lower": 1.0, "upper": -1.0})
    with pytest.raises(ValueError, match="axis"):
        GeneratedJoint(**{**joint.__dict__, "axis": (0.0, 0.0, 0.0)})


def test_uniform_inertia_of_a_box_matches_the_closed_form() -> None:
    sx, sy, sz, mass = 0.2, 0.1, 0.05, 2.0
    inertial = uniform_inertia(box_vertices(sx, sy, sz, cz=0.3), mass)
    assert isinstance(inertial, Inertial)
    assert inertial.mass_kg == mass
    assert inertial.com_m == pytest.approx((0.0, 0.0, 0.3), abs=1e-9)
    expected = (
        mass / 12 * (sy**2 + sz**2),
        mass / 12 * (sx**2 + sz**2),
        mass / 12 * (sx**2 + sy**2),
    )
    assert inertial.inertia[:3] == pytest.approx(expected, rel=1e-6)
    assert inertial.inertia[3:] == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    # An open or degenerate surface is no solid: no mass distribution is invented.
    assert uniform_inertia([0.001, 0, 0] * 3, 1.0) is None
    assert uniform_inertia(box_vertices(0.1, 0.1, 0.1), 0.0) is None


def test_stl_bytes_round_trip_through_the_scene_catalog() -> None:
    from solus_api.livebench.scene.meshes import stl_vertices

    vertices = box_vertices(0.1, 0.2, 0.3)
    data = stl_bytes(vertices)
    assert struct.unpack_from("<I", data, 80)[0] == 12
    assert stl_vertices(data) == pytest.approx(vertices)
    with pytest.raises(ValueError):
        stl_bytes([0.0, 0.0])


def test_a_fixed_attachment_keeps_the_child_where_cad_placed_it() -> None:
    """A mate whose frame or limits are a gap, or a part no mate moves, is a fixed joint: no axis,
    no limit, the child's mesh re-expressed from the parent's frame."""
    model, meshes = two_link_model()
    tip = box_vertices(0.02, 0.02, 0.02, cz=0.26)
    fixed = GeneratedModel(
        name=model.name,
        links=(*model.links, GeneratedLink(name="tip", mesh="meshes/tip.stl")),
        joints=(*model.joints, GeneratedJoint(name="Fm2", type="fixed", parent="arm", child="tip")),
    )

    urdf = write_urdf(fixed)
    parsed = parse_model(urdf, "urdf", {**meshes, "meshes/tip.stl": stl_bytes(tip)})

    _, second = parsed["joints"]
    assert (second["name"], second["type"], second["parent"], second["child"]) == (
        "Fm2",
        "fixed",
        "arm",
        "tip",
    )
    # The tip's frame is the assembly origin: the joint sits back at the arm's frame.
    assert second["xyz"] == pytest.approx([0.0, 0.0, -0.05])
    assert parsed["links"][2]["visuals"][0]["xyz"] == [0.0, 0.0, 0.0]
    assert urdf.count(b"<collision>") == 3 and urdf.count(b"<limit ") == 1


def test_every_limit_carries_effort_and_velocity_sentinels_when_unknown() -> None:
    """urdfdom refuses a `<limit>` without `effort` and `velocity`; when no actuator limit is
    known the SDF "not enforced" sentinel (a negative value) is written: nothing is invented."""
    model, _ = two_link_model()

    urdf = write_urdf(model)

    assert b'<limit lower="-1.57" upper="1.57" effort="-1" velocity="-1" />' in urdf
    assert model.joints[0].effort_nm is None and model.joints[0].velocity_rad_s is None


def test_known_actuator_limits_are_written() -> None:
    model, _ = two_link_model()
    joint = model.joints[0]
    known = GeneratedJoint(**{**joint.__dict__, "effort_nm": 1.2, "velocity_rad_s": 3.5})

    urdf = write_urdf(GeneratedModel(model.name, model.links, (known,)))

    assert b'<limit lower="-1.57" upper="1.57" effort="1.2" velocity="3.5" />' in urdf
    for bad in ({"effort_nm": 0.0}, {"velocity_rad_s": -2.0}, {"effort_nm": float("nan")}):
        with pytest.raises(ValueError, match="actuator"):
            GeneratedJoint(**{**joint.__dict__, **bad})


def test_a_massless_root_or_moving_link_gets_a_minimal_inertial() -> None:
    """Gazebo's urdfdom drops a root link, or a link a non-fixed joint moves, that has no
    `<inertial>` (and every joint under it); fixing the root to a `world` link does not help
    (urdf2sdf lumps it into the world and drops it). A placeholder keeps the link; a massless
    link under a fixed joint is lumped into its parent and gets none. The report's `<link>.mass`
    gap still names the missing mass. The placeholder weighs as much as the heaviest known link
    (P9-T6: a 1 g root under a 0.42 kg arm diverged in Harmonic's DART and aborted the server with
    an ODE AABB assertion; a 1:1 mass ratio ran) and 1 g when no mass is known at all."""
    model, meshes = two_link_model()
    tip = box_vertices(0.02, 0.02, 0.02, cz=0.26)
    three = GeneratedModel(
        name=model.name,
        links=(*model.links, GeneratedLink(name="tip", mesh="meshes/tip.stl")),
        joints=(*model.joints, GeneratedJoint(name="Fm2", type="fixed", parent="arm", child="tip")),
    )

    urdf = write_urdf(three)
    parsed = parse_model(urdf, "urdf", {**meshes, "meshes/tip.stl": stl_bytes(tip)})

    assert [link["name"] for link in parsed["links"]] == ["base", "arm", "tip"]
    base, arm, tip_link = urdf.split(b"<link ")[1:]
    assert b'<mass value="0.42" />' in base  # the heaviest known link's mass (the arm's)
    assert b'ixx="0.00042" iyy="0.00042" izz="0.00042"' in base  # 3 cm radius of gyration
    assert b'<origin xyz="0 0 0" rpy="0 0 0" />' in base.split(b"</inertial>")[0]
    assert b'<mass value="0.42" />' in arm and b"<inertial>" not in tip_link
    # A massless link a revolute joint moves is kept the same way, at its own (joint) frame.
    moving = GeneratedModel(
        name=model.name,
        links=(*model.links, GeneratedLink(name="tip", mesh="meshes/tip.stl")),
        joints=(
            *model.joints,
            GeneratedJoint(
                name="wrist",
                type="revolute",
                parent="arm",
                child="tip",
                origin_m=(0.0, 0.0, 0.25),
                lower=-1.0,
                upper=1.0,
            ),
        ),
    )
    assert write_urdf(moving).count(b'<mass value="0.42" />') == 3  # base, arm, tip
    # Nothing known at all: every kept link weighs the 1 g floor (a 1:1 ratio, nothing to blow up).
    unknown = GeneratedModel(
        name=model.name,
        links=tuple(GeneratedLink(name=link.name, mesh=link.mesh) for link in model.links),
        joints=model.joints,
    )
    assert write_urdf(unknown).count(b'<mass value="0.001" />') == 2


_HARMONIC_GZ = "/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz"
_CLASSIC_GZ = "/home/beeboss/miniconda3/envs/solus-gz-classic/bin/gz"


def _ros_env() -> dict[str, str]:
    """The ROS shell's environment, which the Harmonic `gz` needs to find its commands."""
    import os
    import subprocess

    out = subprocess.run(  # noqa: S603 — a fixed argv in a test, no user input
        ["/bin/bash", "-lc", "source /opt/ros/jazzy/setup.bash; env -0"],
        capture_output=True,
        timeout=20,
        check=True,
    ).stdout
    env = dict(item.split(b"=", 1) for item in out.split(b"\0") if b"=" in item)
    keep = (
        "GZ_CONFIG_PATH",
        "GZ_SIM_SYSTEM_PLUGIN_PATH",
        "GZ_SIM_RESOURCE_PATH",
        "LD_LIBRARY_PATH",
    )
    base = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    return {**base, **{k: env[k.encode()].decode() for k in keep if k.encode() in env}}


@pytest.mark.parametrize(
    ("binary", "env"),
    [
        pytest.param(_HARMONIC_GZ, "ros", id="harmonic"),
        pytest.param(_CLASSIC_GZ, "classic", id="classic"),
    ],
)
def test_two_link_urdf_converts_with_gz_sdf_p(binary: str, env: str, tmp_path: Path) -> None:
    """The real converter (urdfdom + urdf2sdf) accepts the writer's output: every link and the
    joint survive. Skipped where that Gazebo is not installed; never resolved through PATH."""
    import os
    import subprocess
    from pathlib import Path

    if not Path(binary).is_file():
        pytest.skip(f"{binary} is not installed here")
    model, meshes = two_link_model()
    (tmp_path / "meshes").mkdir()
    for path, data in meshes.items():
        (tmp_path / path).write_bytes(data)
    (tmp_path / "two_link.urdf").write_bytes(write_urdf(model))
    environ = (
        _ros_env()
        if env == "ros"
        else {
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": "C.UTF-8",
            "LD_LIBRARY_PATH": str(Path(binary).parents[1] / "lib"),
        }
    )

    done = subprocess.run(  # noqa: S603 — a fixed binary path and a file this test wrote
        [binary, "sdf", "-p", "two_link.urdf"],
        cwd=tmp_path,
        env=environ,
        capture_output=True,
        timeout=20,
        check=False,
    )

    text = done.stdout.decode(errors="replace")
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
    assert "Error" not in done.stderr.decode(errors="replace")
    assert "<link name='base'>" in text and "<link name='arm'>" in text
    assert "<joint name='elbow' type='revolute'>" in text
    assert "<effort>-1</effort>" in text and "<velocity>-1</velocity>" in text
