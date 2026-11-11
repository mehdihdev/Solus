"""SOLUSDEV-322 P6-T2 — the generated URDF compiled into the physics engine's own XML.

`compile_mjcf(urdf, meshes)` writes the URDF and its meshes into a private directory, has a child
process (this interpreter running this module, under `limit_child`'s CPU, memory and file caps,
killed hard at `CHILD_WALL_SECONDS`) build the model and save it back as the engine's XML, then
post-processes that text in the parent until `scene/parser.parse_model` accepts it:

- the compiler element states `angle="radian" coordinate="local" eulerseq="xyz"`;
- every orientation is `pos` + `euler` (intrinsic xyz, the sequence the parser's `mjcf_rpy` reads);
  a saved `quat` is converted, and `axisangle`, `xyaxes`, `zaxis` or `fromto` are refused.

Before the child sees the URDF, two engine hints are appended to it (`_hinted`): keep the visual
meshes and keep the root link as a body, so the saved tree has the identity-posed root body the
parser requires; and the writer's "not enforced" effort sentinel (`-1`, SDF's meaning) becomes the
engine's own "no limit" (`0`), since the engine would read `-1` as a ±1 actuator force clamp. The
stored URDF (`urdf_writer.write_urdf`) never carries them.

Every path here is one the generator made (`meshes/<link>.stl`): a relative path with plain
components or the compile is refused before anything is written. The result is read back as
untrusted bytes, bounded, and nothing but a `MjcfCompileError` with a bounded reason leaves on
any failure. Only the child imports the engine (`ENGINE`), as `providers/mujoco_job.py` does.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

# Parses only text whose DTDs, comments and entities are refused before it is parsed.
from xml.etree import ElementTree as ET  # noqa: S405

from solus_api.livebench.scene.meshes import MAX_BYTES as MAX_MESH_BYTES
from solus_api.livebench.scene.parser import parse_model
from solus_api.simulation.providers.ngspice_provider import limit_child, log_tail

logger = logging.getLogger(__name__)

ENGINE: Final = "mujoco"  # capability-hygiene: allow the engine the child imports and its URDF hint
URDF: Final = "model.urdf"
SAVED: Final = "model.xml"
STATUS: Final = "status.json"
MAX_URDF_BYTES: Final = 1024 * 1024
MAX_RESULT_BYTES: Final = 2 * 1024 * 1024
CHILD_WALL_SECONDS: Final = 60.0
MAX_REASON_CHARS: Final = 500
_PART: Final = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}"
_MESH_PATH: Final = re.compile(rf"^{_PART}(?:/{_PART}){{0,7}}\.stl$")
#: Orientation attributes the parser does not read; a saved model never needs them.
_REFUSED_ORIENTATION: Final = ("axisangle", "xyaxes", "zaxis", "fromto")
#: The compiler attributes the parser pins (`scene/parser._mjcf`).
_COMPILER: Final = {"angle": "radian", "coordinate": "local", "eulerseq": "xyz"}
Quat = tuple[float, float, float, float]


class MjcfCompileError(Exception):
    """The URDF did not become an accepted model; the message is Solus-composed and bounded."""


def _safe_mesh_path(path: str) -> bool:
    return bool(_MESH_PATH.fullmatch(path)) and ".." not in path.split("/")


def _hinted(urdf: bytes) -> bytes:
    """The URDF with the engine's import hints appended: visuals kept, the root link kept as a
    body, mesh paths kept whole."""
    if len(urdf) > MAX_URDF_BYTES or b"<!" in urdf or b"\x00" in urdf:
        raise MjcfCompileError("the URDF is oversized or holds a DTD, a comment or a NUL")
    try:
        root = ET.fromstring(urdf)  # noqa: S314 — DTD/entities refused above
    except ET.ParseError:
        raise MjcfCompileError("the URDF is not well-formed XML") from None
    if root.tag != "robot":
        raise MjcfCompileError("the model is not a URDF")
    hint = ET.SubElement(root, ENGINE)
    ET.SubElement(hint, "compiler", discardvisual="false", fusestatic="false", strippath="false")
    for limit in root.iter("limit"):
        if limit.get("effort", "").startswith("-"):  # SDF's "not enforced" is the engine's 0
            limit.set("effort", "0")
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def quat_to_euler(quat: Quat) -> tuple[float, float, float]:
    """A unit quaternion (w, x, y, z) as intrinsic xyz Euler angles: R = Rx(a)·Ry(b)·Rz(c)."""
    w, x, y, z = quat
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-12:
        raise MjcfCompileError("a saved orientation is not a unit quaternion")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    r00 = 1 - 2 * (y * y + z * z)
    r01 = 2 * (x * y - w * z)
    r02 = 2 * (x * z + w * y)
    r12 = 2 * (y * z - w * x)
    r22 = 1 - 2 * (x * x + y * y)
    r10 = 2 * (x * y + w * z)
    r11 = 1 - 2 * (x * x + z * z)
    pitch = math.asin(max(-1.0, min(1.0, r02)))
    if abs(math.cos(pitch)) < 1e-9:  # gimbal lock: fold the lost angle into the first
        return (math.atan2(r10, r11), pitch, 0.0)
    return (math.atan2(-r12, r22), pitch, math.atan2(-r01, r00))


def _saved_numbers(text: str, count: int) -> tuple[float, ...]:
    try:
        values = tuple(float(v) for v in text.split())
    except ValueError:
        raise MjcfCompileError("a saved number is unreadable") from None
    if len(values) != count or any(not math.isfinite(v) for v in values):
        raise MjcfCompileError(f"a saved attribute must hold {count} finite numbers")
    return values


def _euler_only(element: ET.Element) -> None:
    if any(name in element.attrib for name in _REFUSED_ORIENTATION):
        raise MjcfCompileError("the saved model uses an orientation the scene parser cannot read")
    quat = element.attrib.pop("quat", None)
    if quat is not None:
        w, x, y, z = _saved_numbers(quat, 4)
        euler = quat_to_euler((w, x, y, z))
        if any(abs(v) > 1e-9 for v in euler):
            element.set("euler", " ".join(f"{v:.9g}" for v in euler))


def postprocess(saved: bytes) -> bytes:
    """The engine's saved XML as the parser reads it (module docstring)."""
    if len(saved) > MAX_RESULT_BYTES or b"<!" in saved or b"\x00" in saved:
        raise MjcfCompileError("the saved model is oversized or holds a DTD, a comment or a NUL")
    try:
        root = ET.fromstring(saved)  # noqa: S314 — DTD/entities refused above
    except ET.ParseError:
        raise MjcfCompileError("the saved model is not well-formed XML") from None
    if root.tag != ENGINE:
        raise MjcfCompileError("the saved text is not the engine's model")
    compiler = root.find("compiler")
    if compiler is None:
        compiler = ET.Element("compiler")
        root.insert(0, compiler)
    for name, value in _COMPILER.items():
        compiler.set(name, value)
    for element in root.iter():
        _euler_only(element)
    ET.indent(root)
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _write_inputs(work: Path, urdf: bytes, meshes: Mapping[str, bytes]) -> None:
    for path, data in meshes.items():
        if not _safe_mesh_path(path) or len(data) > MAX_MESH_BYTES:
            raise MjcfCompileError(f"mesh path {path[:64]!r} is not a plain relative STL path")
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (work / URDF).write_bytes(_hinted(urdf))


def _run_child(work: Path) -> int:
    with (work / "stderr.txt").open("wb") as err:
        try:
            done = subprocess.run(  # noqa: S603 — this interpreter and this module, no shell
                [sys.executable, "-I", "-m", __name__],
                cwd=work,
                env={"HOME": str(work), "LC_ALL": "C", "OPENBLAS_NUM_THREADS": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                timeout=CHILD_WALL_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise MjcfCompileError(
                f"the model build went past {CHILD_WALL_SECONDS:g} s of wall time"
            ) from None
        except (OSError, subprocess.SubprocessError) as exc:
            raise MjcfCompileError(f"the model build did not start: {type(exc).__name__}") from None
    return done.returncode


def _child_status(work: Path, code: int) -> None:
    """Raise the child's own refusal, or a bounded failure, unless it reported a build."""
    path, status, reason = work / STATUS, None, None
    if code == 0 and path.is_file() and path.stat().st_size <= MAX_RESULT_BYTES:
        try:
            raw = json.loads(path.read_bytes())
            status, reason = raw.get("status"), str(raw.get("reason", ""))
        except (ValueError, AttributeError):
            status = "malformed"
    if status == "built":
        return
    logger.warning("model build %s (exit %s): %s", status or "stopped", code, log_tail(work))
    detail = f": {reason[:MAX_REASON_CHARS]}" if status == "failed" and reason else ""
    raise MjcfCompileError(f"the physics engine did not build the model{detail}")


def compile_mjcf(urdf: bytes, meshes: Mapping[str, bytes]) -> bytes:
    """The model the engine built from the URDF, as XML the scene parser accepts (module
    docstring); `MjcfCompileError` otherwise, never a partial result."""
    with tempfile.TemporaryDirectory(prefix="solus-model-") as private:
        work = Path(private)
        _write_inputs(work, urdf, meshes)
        code = _run_child(work)
        _child_status(work, code)
        saved = work / SAVED
        if not saved.is_file() or saved.stat().st_size > MAX_RESULT_BYTES:
            raise MjcfCompileError("the physics engine left no model of a readable size")
        result = postprocess(saved.read_bytes())
    try:
        parse_model(result, "mjcf", dict(meshes))
    except ValueError as exc:
        raise MjcfCompileError(f"the built model is not one the scene accepts: {exc}") from None
    return result


def child_build() -> None:
    """The child's whole work, in its private directory: limits first, then the one build."""
    limit_child()
    result: dict[str, Any]
    try:
        engine = importlib.import_module(ENGINE)
        model = engine.MjModel.from_xml_path(URDF)
        engine.mj_saveLastXML(SAVED, model)
        result = {"status": "built"}
    except Exception as exc:  # the engine's own message, bounded; the parent logs its tail
        result = {"status": "failed", "reason": str(exc)[:MAX_REASON_CHARS]}
    Path(STATUS).write_text(json.dumps(result))


if __name__ == "__main__":  # pragma: no cover — the child's entry, which `compile_mjcf` runs
    child_build()
