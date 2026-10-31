"""SOLUSDEV-321 P5 (R104, D7) — `livebench.sim.offscreen`: one offscreen picture of a scene model.

The physics engine's own renderer draws it on EGL, in a child of its own under P4-T3's caps, after
P4-T3's parse-based guard has passed the text (in the caller and again in the child). A second,
segmentation pass of the same camera gives each body's pixel bounds, so labels sit where the parts
are drawn. A face view looks along the named face's inward normal at its target; the bounds view
frames the target; the isometric view frames the whole model.
"""

from __future__ import annotations

import ctypes.util
import subprocess
from typing import Any

import pytest
from livebench.sim import offscreen
from livebench.sim.offscreen import SceneShot, render_scene_png
from solus_api.simulation.providers.mujoco_job import engine_installed
from solus_api.simulation.sim_capability import SimulationFailedError, SimulationRefusedError

#: The fake arm's scene: synthetic, primitive geoms only (Q3; the shared guard admits no file).
FAKE_ARM_MJCF = """<mujoco model="fake_arm">
  <option timestep="0.002"/>
  <worldbody>
    <light pos="0 0 3"/>
    <geom name="floor" type="plane" size="1 1 0.1" rgba="0.9 0.9 0.9 1"/>
    <body name="base" pos="0 0 0.05">
      <geom name="base_geom" type="box" size="0.08 0.08 0.05" rgba="0.4 0.4 0.4 1"/>
      <body name="servo_1_joint_1" pos="0 0 0.05">
        <joint name="joint_1" type="hinge" axis="0 0 1"/>
        <geom name="servo_1_geom" type="cylinder" size="0.03 0.02" rgba="0.2 0.4 0.8 1"/>
        <body name="servo_2_joint_2" pos="0 0 0.02">
          <joint name="joint_2" type="hinge" axis="0 1 0"/>
          <geom name="arm_geom" type="capsule" fromto="0 0 0 0 0 0.3" size="0.02"
                rgba="0.8 0.3 0.2 1"/>
        </body>
      </body>
    </body>
  </worldbody>
</mujoco>
"""

_EGL = engine_installed() and ctypes.util.find_library("EGL") is not None
needs_egl = pytest.mark.skipif(not _EGL, reason="the physics engine or EGL is absent here")


def _boxes(shot: SceneShot) -> dict[str, tuple[int, int, int, int]]:
    return {body.name: body.box for body in shot.bodies}


@needs_egl
def test_a_scene_renders_offscreen_on_egl_with_each_body_at_its_bounds() -> None:
    shot = render_scene_png(FAKE_ARM_MJCF, view="iso", width=320, height=240)

    assert shot.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (shot.width, shot.height) == (320, 240)
    boxes = _boxes(shot)
    assert {"base", "servo_1_joint_1", "servo_2_joint_2"} <= set(boxes)
    for x0, y0, x1, y1 in boxes.values():
        assert 0 <= x0 <= x1 < 320 and 0 <= y0 <= y1 < 240
    joints = {body.name: body.joints for body in shot.bodies}
    assert joints["servo_2_joint_2"] == ("joint_2",) and joints["base"] == ()


@needs_egl
def test_a_face_view_looks_at_its_target() -> None:
    """The target is the body the bound joint moves; the camera looks at its centre along the
    front face's normal, so the target sits at the middle of the picture."""
    shot = render_scene_png(
        FAKE_ARM_MJCF, view="face", side="front", target_joint="joint_2", width=320, height=240
    )

    x0, y0, x1, y1 = _boxes(shot)["servo_2_joint_2"]
    assert x0 <= 160 <= x1 and y0 <= 120 <= y1
    named = render_scene_png(FAKE_ARM_MJCF, view="bounds", target_name="Servo 2 (joint 2)")
    nx0, ny0, nx1, ny1 = _boxes(named)["servo_2_joint_2"]
    assert nx0 <= named.width // 2 <= nx1 and ny0 <= named.height // 2 <= ny1


@pytest.mark.parametrize(
    "refused",
    [
        FAKE_ARM_MJCF.replace("<worldbody>", "<!-- a comment --><worldbody>"),
        FAKE_ARM_MJCF.replace("<worldbody>", '<include file="other.xml"/><worldbody>'),
        FAKE_ARM_MJCF.replace(
            "<worldbody>", '<asset><mesh name="m" file="arm.stl"/></asset><worldbody>'
        ),
        '<robot name="fake"><link name="base"/></robot>',
        "<mujoco>" + " " * offscreen.MAX_SCENE_BYTES + "</mujoco>",
    ],
)
def test_the_guard_refuses_before_any_child_runs(
    refused: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no child may start for a refused scene")

    monkeypatch.setattr(subprocess, "run", never)
    with pytest.raises(SimulationRefusedError):
        render_scene_png(refused, view="iso")


@pytest.mark.parametrize(
    "arguments",
    [
        {"view": "sideways"},
        {"view": "face", "side": "diagonal"},
        {"view": "bounds", "target_name": "../etc/passwd"},
        {"view": "iso", "width": 10_000},
    ],
)
def test_arguments_outside_the_views_are_refused(
    arguments: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no child may start"))
    with pytest.raises(SimulationRefusedError):
        render_scene_png(FAKE_ARM_MJCF, **arguments)


def test_a_child_that_stops_is_a_failure_never_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def times_out(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="child", timeout=1)

    monkeypatch.setattr(subprocess, "run", times_out)
    with pytest.raises(SimulationFailedError, match="wall time"):
        render_scene_png(FAKE_ARM_MJCF, view="iso")

    def dies(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=-9)

    monkeypatch.setattr(subprocess, "run", dies)
    with pytest.raises(SimulationFailedError):
        render_scene_png(FAKE_ARM_MJCF, view="iso")


# --- P5 security review (R105–R107's posture): what a scene may ask the renderer for ----------


def _with_visual(visual: str) -> str:
    return FAKE_ARM_MJCF.replace("<worldbody>", f"<visual>{visual}</visual><worldbody>")


def _with_assets(assets: str) -> str:
    return FAKE_ARM_MJCF.replace("<worldbody>", f"<asset>{assets}</asset><worldbody>")


@pytest.mark.parametrize(
    ("visual", "named"),
    [
        ('<global offwidth="16384"/>', "offwidth"),
        ('<global offheight="16384"/>', "offheight"),
        ('<quality offsamples="64"/>', "offsamples"),
        ('<quality shadowsize="65536"/>', "shadowsize"),
        ('<quality shadowsize="lots"/>', "shadowsize"),
    ],
)
def test_a_scene_asking_for_a_large_framebuffer_is_refused_naming_it(
    visual: str, named: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The framebuffer, its samples and the shadow map are the scene's to ask for and the
    renderer's to allow: past a cap the scene is refused before any child starts, and the reason
    names what asked."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no child may start"))
    with pytest.raises(SimulationRefusedError, match=named):
        render_scene_png(_with_visual(visual), view="iso")


@needs_egl
def test_a_modest_framebuffer_request_still_draws_at_the_requests_size() -> None:
    """Under the caps a scene's own framebuffer size is overruled, not obeyed: the picture is the
    request's size (the child overwrites the model's offscreen size with it)."""
    shot = render_scene_png(
        _with_visual('<global offwidth="1920" offheight="1080"/>'),
        view="iso",
        width=320,
        height=240,
    )
    assert (shot.width, shot.height) == (320, 240)


@pytest.mark.parametrize(
    ("assets", "named"),
    [
        (
            "".join(
                f'<texture name="t{n}" type="2d" builtin="flat" width="8" height="8"/>'
                for n in range(offscreen.MAX_TEXTURES + 1)
            ),
            "textures",
        ),
        (
            '<texture name="big" type="2d" builtin="checker" width="8192" height="8192"/>',
            "textures",
        ),
        ('<texture name="sky" type="skybox" builtin="gradient" width="2048"/>', "textures"),
        ('<texture name="odd" type="2d" builtin="flat" width="many" height="8"/>', "textures"),
        ('<hfield name="h" nrow="4096" ncol="4096" size="1 1 1 1"/>', "height fields"),
    ],
)
def test_a_scene_whose_textures_exceed_the_budget_is_refused(
    assets: str, named: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A few bytes of text can ask the engine for gigabytes of texels or height samples: past the
    render's budget the scene is refused before it compiles, the reason naming what asked."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no child may start"))
    with pytest.raises(SimulationRefusedError, match=named):
        render_scene_png(_with_assets(assets), view="iso")


@pytest.mark.skipif(not engine_installed(), reason="the physics engine is absent here")
def test_the_child_bounds_what_reaches_the_renderer() -> None:
    """Defence in depth behind the guard: in the child, the compiled model's offscreen size is the
    request's, its samples and shadow map are clamped, and its compiled textures are re-checked."""
    import mujoco

    model = mujoco.MjModel.from_xml_string(FAKE_ARM_MJCF)
    model.vis.global_.offwidth, model.vis.global_.offheight = 16384, 16384
    model.vis.quality.offsamples, model.vis.quality.shadowsize = 64, 65536

    bounded = offscreen.bound_for_render(model, 320, 240)

    assert (bounded.vis.global_.offwidth, bounded.vis.global_.offheight) == (320, 240)
    assert bounded.vis.quality.offsamples == offscreen.MAX_OFFSAMPLES
    assert bounded.vis.quality.shadowsize == offscreen.MAX_SHADOW_PX

    textured = mujoco.MjModel.from_xml_string(
        _with_assets(
            "".join(
                f'<texture name="t{n}" type="2d" builtin="flat" width="8" height="8"/>'
                for n in range(offscreen.MAX_TEXTURES + 1)
            )
        )
    )
    with pytest.raises(SimulationRefusedError, match="textures"):
        offscreen.bound_for_render(textured, 320, 240)
