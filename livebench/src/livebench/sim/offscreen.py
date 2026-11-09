"""SOLUSDEV-321 P5 (R104, D7) — one offscreen picture of a scene model, drawn by the physics
engine's own renderer on EGL.

The API reaches this module only through the optional runtime import (solus_api's
`agent/vision/renderers.py`, the way the bench reaches `livebench.local`). The engine's renderer is
called here because `.render()` appears in no `solus_api` file but `context.py`.

The posture is P4-T3's (`solus_api.simulation.providers.mujoco_job`), reused rather than copied:

- the text passes `checked_mjcf`, the parse-based guard (no DTD, comment, NUL, include, plugin,
  file or path, nothing that multiplies the model), before anything compiles it: here, and again
  in the child;
- the scene may not ask the renderer for more than a render's budget (`render_budget_error`, the P5
  security review): a framebuffer past `MAX_OFFSCREEN_PX`, more than `MAX_OFFSAMPLES` samples, a
  shadow map past `MAX_SHADOW_PX`, more than `MAX_TEXTURES` textures or `MAX_TEXTURE_PIXELS`
  texels, or height fields past `MAX_HFIELD_SAMPLES` samples is refused before anything compiles,
  the reason naming what asked — here, and again in the child;
- the engine runs only in a child of its own: this interpreter running this module, in a private
  directory, with a scrubbed environment plus `MUJOCO_GL=egl`, `limit_child`'s CPU, memory and
  file caps set before it reads its request, and a hard wall timeout;
- the child compiles through the empty virtual file system (`compiled`), checks every count
  (`sized`) before any `MjData` exists, and bounds the compiled model for the renderer
  (`bound_for_render`, defence in depth): the offscreen framebuffer is the request's size, the
  samples and the shadow map are clamped, the compiled textures are re-checked;
- what it leaves is read back as untrusted: a PNG of at most `MAX_PNG_BYTES` and a result of at
  most `MAX_RESULT_BYTES`, validated whole.

The camera is a free camera. `iso` frames the whole model; `face` looks at the target along the
named face's inward normal (the scene's own frame: front is the +x face, back −x, left +y, right
−y, top +z, bottom −z); `bounds` frames the target from the isometric side. The target is the body
a named joint moves, else the body whose normalised name is the given one, else the whole model.
A second, segmentation pass of the same camera gives each body's pixel bounds, so a caller can
label each part where it is drawn.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

# Parses only text whose DTDs and entities `checked_mjcf` has already refused.
from xml.etree import ElementTree  # noqa: S405

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from solus_api.agent.vision import body_key
from solus_api.simulation.providers.mujoco_job import (
    MAX_MJCF_BYTES,
    checked_mjcf,
    compiled,
    engine_installed,
    physics_engine,
    sized,
)
from solus_api.simulation.providers.ngspice_provider import limit_child
from solus_api.simulation.sim_capability import SimulationFailedError, SimulationRefusedError

#: The most scene text a picture is drawn from: the trajectory job's own bound.
MAX_SCENE_BYTES: Final = MAX_MJCF_BYTES
WIDTH: Final = 800
HEIGHT: Final = 600
MIN_SIDE_PX: Final = 64
MAX_SIDE_PX: Final = 1600
CHILD_WALL_SECONDS: Final = 30.0
MAX_PNG_BYTES: Final = 2 * 1024 * 1024
MAX_RESULT_BYTES: Final = 256 * 1024
MAX_BODIES: Final = 64
MAX_JOINTS: Final = 16
#: A body drawn in fewer pixels than this gets no bounds: a label there would only be noise.
MIN_BODY_PIXELS: Final = 12
VIEWS: Final = ("face", "bounds", "iso")
#: A face → (azimuth, elevation) of a free camera looking along its inward normal.
SIDES: Final = MappingProxyType(
    {
        "front": (180.0, 0.0),
        "back": (0.0, 0.0),
        "left": (270.0, 0.0),
        "right": (90.0, 0.0),
        "top": (90.0, -89.0),
        "bottom": (90.0, 89.0),
    }
)
ISO: Final = (135.0, -30.0)
#: How far the camera stands back, in half-sizes of what it frames (the default 45° field of view
#: then holds it with a margin).
FRAME_DISTANCE: Final = 4.0
REQUEST: Final = "request.json"
RESULT: Final = "result.json"
PICTURE: Final = "render.png"
STOPPED: Final = "the scene render stopped without a picture: past a limit, or the engine failed"
_NAME: Final = re.compile(r"^[A-Za-z0-9_.\- ()]{1,128}$")

#: A render's budget (P5 security review, the posture of P4-T3's R105–R107 caps): what a scene may
#: ask the renderer for. The GPU allocates from these before the child's memory cap can see them.
MAX_OFFSCREEN_PX: Final = 4096
MAX_OFFSAMPLES: Final = 4
MAX_SHADOW_PX: Final = 4096
MAX_TEXTURES: Final = 16
MAX_TEXTURE_PIXELS: Final = 16 * 1024 * 1024
MAX_HFIELD_SAMPLES: Final = 4 * 1024 * 1024
#: Texture types the engine stores as six faces.
_CUBE_TEXTURES: Final = frozenset({"cube", "skybox"})
#: (`<visual>` child, attribute) → the most a scene may declare.
_VISUAL_CAPS: Final = MappingProxyType(
    {
        ("global", "offwidth"): MAX_OFFSCREEN_PX,
        ("global", "offheight"): MAX_OFFSCREEN_PX,
        ("quality", "offsamples"): MAX_OFFSAMPLES,
        ("quality", "shadowsize"): MAX_SHADOW_PX,
    }
)


class BodyBox(BaseModel):
    """One body drawn in the picture: its name, the joints that move it, its pixel bounds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    joints: tuple[str, ...] = Field(default=(), max_length=MAX_JOINTS)
    box: tuple[int, int, int, int]


class _ShotResult(BaseModel):
    """What the child hands back, read as untrusted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ran"]
    width: int = Field(ge=MIN_SIDE_PX, le=MAX_SIDE_PX)
    height: int = Field(ge=MIN_SIDE_PX, le=MAX_SIDE_PX)
    bodies: tuple[BodyBox, ...] = Field(max_length=MAX_BODIES)


@dataclass(frozen=True)
class SceneShot:
    """The picture, its size, and each drawn body's bounds."""

    png: bytes
    width: int
    height: int
    bodies: tuple[BodyBox, ...]


def render_scene_png(
    mjcf: str,
    *,
    view: str,
    side: str | None = None,
    target_joint: str | None = None,
    target_name: str | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> SceneShot:
    """One picture of the scene `mjcf` (module docstring). `SimulationRefusedError` for arguments
    or a scene the guards refuse, before any child starts; `SimulationFailedError` when the
    engine is absent or the child stops without a picture."""
    request = _request(mjcf, view, side, target_joint, target_name, width, height)
    checked_mjcf(mjcf, importlib.import_module("livebench.local"))
    _refuse_past_budget(mjcf)
    if not engine_installed():
        raise SimulationFailedError("the physics engine is not available on this machine")
    with tempfile.TemporaryDirectory(prefix="solus-shot-") as private:
        work = Path(private)
        (work / REQUEST).write_text(json.dumps(request))
        with (work / "stderr.txt").open("wb") as err:
            try:
                done = subprocess.run(  # noqa: S603 — this interpreter and this module, no shell
                    [sys.executable, "-I", "-m", __name__],
                    cwd=work,
                    env={
                        "HOME": private,
                        "LC_ALL": "C",
                        "MUJOCO_GL": "egl",
                        "OPENBLAS_NUM_THREADS": "1",
                    },
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=err,
                    timeout=CHILD_WALL_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise SimulationFailedError(
                    f"the scene render went past {CHILD_WALL_SECONDS:g} s of wall time"
                ) from None
            except (OSError, subprocess.SubprocessError) as exc:
                raise SimulationFailedError(
                    f"the scene render did not start: {type(exc).__name__}"
                ) from None
        return _shot_of(work, done.returncode)


def render_budget_error(mjcf: str) -> str | None:
    """Why a render refuses `mjcf`, naming what asked, or None (module docstring). It runs after
    `checked_mjcf`, which has refused every DTD and entity, so the text is safe to parse; a value
    no number can be read from is refused. It refuses a DTD itself too, so it is safe on its own:
    without one, no entity (and no external or recursive one) can reach the parser."""
    if "<!" in mjcf:
        return "the scene may hold no DTD, comment or entity"
    root = ElementTree.fromstring(mjcf)  # noqa: S314 — no DTD, so no entity, reaches the parser
    return _visual_error(root) or _texture_error(root)


def bound_for_render(model: Any, width: int, height: int) -> Any:
    """The compiled model, bounded for one picture (defence in depth behind
    `render_budget_error`): its offscreen framebuffer is the request's size, its samples and shadow
    map are clamped, and its compiled textures and height fields must be within the budget, else
    `SimulationRefusedError`."""
    import numpy as np

    texels = int((np.asarray(model.tex_height, dtype=np.int64) * model.tex_width).sum())
    if int(model.ntex) > MAX_TEXTURES or texels > MAX_TEXTURE_PIXELS:
        raise SimulationRefusedError("the scene's textures are past what a render reads")
    samples = int((np.asarray(model.hfield_nrow, dtype=np.int64) * model.hfield_ncol).sum())
    if samples > MAX_HFIELD_SAMPLES:
        raise SimulationRefusedError("the scene's height fields are past what a render reads")
    model.vis.global_.offwidth, model.vis.global_.offheight = int(width), int(height)
    quality = model.vis.quality
    quality.offsamples = min(int(quality.offsamples), MAX_OFFSAMPLES)
    quality.shadowsize = min(int(quality.shadowsize), MAX_SHADOW_PX)
    return model


def _refuse_past_budget(mjcf: str) -> None:
    why = render_budget_error(mjcf)
    if why is not None:
        raise SimulationRefusedError(why)


def _declared(element: ElementTree.Element, name: str) -> float:
    """An attribute's number: 0 when it is absent, NaN (refused) when it is no number."""
    raw = element.get(name)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return math.nan


def _visual_error(root: ElementTree.Element) -> str | None:
    for visual in root.iter("visual"):
        for (tag, name), cap in _VISUAL_CAPS.items():
            for element in visual.iter(tag):
                if not _declared(element, name) <= cap:
                    return f"the scene's `{tag}` `{name}` is past what a render allows ({cap})"
    return None


def _texels(texture: ElementTree.Element) -> float:
    """What one texture asks the engine to store: six square faces for a cube or a skybox."""
    width, height = _declared(texture, "width"), _declared(texture, "height")
    if texture.get("type") in _CUBE_TEXTURES:
        return 6 * width * max(width, height)
    return width * (height or width)


def _texture_error(root: ElementTree.Element) -> str | None:
    textures = list(root.iter("texture"))
    if len(textures) > MAX_TEXTURES:
        return f"the scene declares {len(textures)} textures; a render reads at most {MAX_TEXTURES}"
    if not sum(_texels(texture) for texture in textures) <= MAX_TEXTURE_PIXELS:
        return (
            f"the scene's textures hold more than the {MAX_TEXTURE_PIXELS:,} texels a render reads"
        )
    samples = sum(_declared(f, "nrow") * _declared(f, "ncol") for f in root.iter("hfield"))
    if not samples <= MAX_HFIELD_SAMPLES:
        return (
            f"the scene's height fields hold more than the {MAX_HFIELD_SAMPLES:,} samples a "
            "render reads"
        )
    return None


def _request(
    mjcf: str,
    view: str,
    side: str | None,
    target_joint: str | None,
    target_name: str | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    """The child's request, every argument checked first."""
    if view not in VIEWS or (side is not None and side not in SIDES):
        raise SimulationRefusedError("a scene picture is a face, bounds or isometric view")
    names = [name for name in (target_joint, target_name) if name is not None]
    if any(_NAME.fullmatch(name) is None or ".." in name for name in names):
        raise SimulationRefusedError("a target names a joint or a body, nothing else")
    if not all(MIN_SIDE_PX <= side_px <= MAX_SIDE_PX for side_px in (width, height)):
        raise SimulationRefusedError(f"a scene picture is {MIN_SIDE_PX}-{MAX_SIDE_PX} px a side")
    if len(mjcf.encode("utf-8", "surrogatepass")) > MAX_SCENE_BYTES:
        raise SimulationRefusedError(f"the scene exceeds {MAX_SCENE_BYTES // 1024} KiB")
    return {
        "mjcf": mjcf,
        "view": view,
        "side": side,
        "target_joint": target_joint,
        "target_name": target_name,
        "width": width,
        "height": height,
    }


def _shot_of(work: Path, code: int) -> SceneShot:
    """What the child left, read back as untrusted (module docstring)."""
    path, picture, raw = work / RESULT, work / PICTURE, None
    if code == 0 and path.is_file() and path.stat().st_size <= MAX_RESULT_BYTES:
        with contextlib.suppress(ValueError, RecursionError):
            raw = json.loads(path.read_bytes())
    status = raw.get("status") if isinstance(raw, dict) else None
    if status in ("refused", "failed") and isinstance(raw, dict):
        error = SimulationRefusedError if status == "refused" else SimulationFailedError
        raise error(str(raw.get("reason"))[:500])
    try:
        result = _ShotResult.model_validate(raw)
    except ValidationError:
        raise SimulationFailedError(STOPPED) from None
    if not picture.is_file() or picture.stat().st_size > MAX_PNG_BYTES:
        raise SimulationFailedError(STOPPED)
    for body in result.bodies:
        x0, y0, x1, y1 = body.box
        if not (0 <= x0 <= x1 < result.width and 0 <= y0 <= y1 < result.height):
            raise SimulationFailedError(STOPPED)
    return SceneShot(picture.read_bytes(), result.width, result.height, result.bodies)


def _target_body(engine: Any, model: Any, request: dict[str, Any]) -> int | None:
    """The body a named joint moves, else the body whose name is the target's under the API's one
    name rule (`solus_api.agent.vision.body_key`, which also places the labels)."""
    joint, name = request.get("target_joint"), request.get("target_name")
    if isinstance(joint, str):
        found = engine.mj_name2id(model, engine.mjtObj.mjOBJ_JOINT, joint)
        if found >= 0:
            return int(model.jnt_bodyid[found])
    if isinstance(name, str):
        wanted = body_key(name)
        for body in range(1, model.nbody):
            body_name = engine.mj_id2name(model, engine.mjtObj.mjOBJ_BODY, body)
            if body_name and body_key(body_name) == wanted:
                return body
    return None


def _framing(engine: Any, model: Any, data: Any, target: int | None) -> tuple[Any, float]:
    """The point to look at and the half-size to frame: the bounds of the target's geoms, or of
    every drawn part's (planes excluded: a floor has no bounds), else the model's own extent."""
    import numpy as np

    geoms = [
        geom
        for geom in range(model.ngeom)
        if (target is None or int(model.geom_bodyid[geom]) == target)
        and int(model.geom_type[geom]) != int(engine.mjtGeom.mjGEOM_PLANE)
    ]
    if not geoms:
        where = model.stat.center if target is None else data.xpos[target]
        return np.array(where), float(model.stat.extent) * (1.0 if target is None else 0.25)
    points, radii = data.geom_xpos[geoms], model.geom_rbound[geoms][:, None]
    low, high = (points - radii).min(axis=0), (points + radii).max(axis=0)
    return (low + high) / 2, max(float((high - low).max()) / 2, 1e-3)


def _scene_camera(engine: Any, model: Any, data: Any, request: dict[str, Any]) -> Any:
    target = _target_body(engine, model, request) if request["view"] != "iso" else None
    center, extent = _framing(engine, model, data, target)
    camera = engine.MjvCamera()
    camera.lookat[:] = center
    camera.distance = extent * FRAME_DISTANCE
    face = request["view"] == "face"
    camera.azimuth, camera.elevation = SIDES[request["side"] or "front"] if face else ISO
    return camera


def _body_boxes(engine: Any, model: Any, segmentation: Any) -> list[dict[str, Any]]:
    """Each drawn body's pixel bounds, from the segmentation pass's geom ids (the world is no
    part), at most `MAX_BODIES`."""
    import numpy as np

    geoms = np.where(
        segmentation[..., 1] == int(engine.mjtObj.mjOBJ_GEOM), segmentation[..., 0], -1
    )
    owner = np.where(geoms >= 0, model.geom_bodyid[np.clip(geoms, 0, None)], -1)
    found: list[dict[str, Any]] = []
    for body in range(1, model.nbody):
        rows, columns = np.nonzero(owner == body)
        name = engine.mj_id2name(model, engine.mjtObj.mjOBJ_BODY, body)
        if len(columns) < MIN_BODY_PIXELS or not name:
            continue
        joints = [
            engine.mj_id2name(model, engine.mjtObj.mjOBJ_JOINT, int(joint))
            for joint in np.flatnonzero(model.jnt_bodyid == body)
        ]
        box = [int(columns.min()), int(rows.min()), int(columns.max()), int(rows.max())]
        found.append(
            {"name": name[:128], "joints": [j for j in joints if j][:MAX_JOINTS], "box": box}
        )
        if len(found) >= MAX_BODIES:
            break
    return found


def _shoot(engine: Any, model: Any, request: dict[str, Any], work: Path) -> dict[str, Any]:
    """The child's picture and segmentation pass of one camera; the picture is written beside
    the request."""
    from PIL import Image

    data = engine.MjData(model)
    engine.mj_forward(model, data)
    camera = _scene_camera(engine, model, data, request)
    renderer = engine.Renderer(model, request["height"], request["width"])
    try:
        renderer.update_scene(data, camera=camera)
        pixels = renderer.render()
        renderer.enable_segmentation_rendering()
        renderer.update_scene(data, camera=camera)
        segmentation = renderer.render()
    finally:
        renderer.close()
    Image.fromarray(pixels, "RGB").save(work / PICTURE, format="PNG")
    return {
        "status": "ran",
        "width": int(pixels.shape[1]),
        "height": int(pixels.shape[0]),
        "bodies": _body_boxes(engine, model, segmentation),
    }


def _shot_child() -> None:
    """The child `render_scene_png` starts, in its private directory: its limits before anything
    else, then the one request beside it, and one result."""
    limit_child()
    work = Path.cwd()
    request = json.loads((work / REQUEST).read_bytes())
    result: dict[str, Any]
    try:
        engine = physics_engine()
        if engine is None:
            raise SimulationFailedError("the physics engine is not available on this machine")
        xml = str(request["mjcf"])
        checked_mjcf(xml, importlib.import_module("livebench.local"))
        _refuse_past_budget(xml)
        model = bound_for_render(
            sized(compiled(engine, xml)), int(request["width"]), int(request["height"])
        )
        result = _shoot(engine, model, request, work)
    except SimulationRefusedError as exc:
        result = {"status": "refused", "reason": str(exc)}
    except SimulationFailedError as exc:
        result = {"status": "failed", "reason": str(exc)}
    (work / RESULT).write_text(json.dumps(result))


if __name__ == "__main__":  # pragma: no cover — the child's entry, which `render_scene_png` runs
    _shot_child()
