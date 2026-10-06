"""Exact XCAF occurrence tessellation; isolated execution has a hard kill deadline."""

from __future__ import annotations

import asyncio
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from solus_api.connectors.step_parser import parse_step

MAX_BYTES = 8 * 1024 * 1024
MAX_TRIANGLES = 50_000
# Reserve space for transformed coordinate serialization and normalized metadata.
MESH_BYTES = 6 * 1024 * 1024
TIMEOUT_SECONDS = 25
_EXTERNAL = re.compile(
    r"\b(?:DOCUMENT_FILE|EXTERNAL_SOURCE|EXTERNALLY_DEFINED_[A-Z_]+)\b", re.IGNORECASE
)


class CadGeometryError(ValueError):
    """Allowlisted geometry failure safe for an API status reason."""

    def __init__(self) -> None:
        super().__init__("geometry_limit_exceeded")


def _triangles(shape: Any, deflection: float, angle: float) -> list[float]:
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepTools.Clean_s(shape)
    mesher = BRepMesh_IncrementalMesh(shape, deflection, False, angle, False)
    if not mesher.IsDone():
        raise ValueError("CAD tessellation unavailable")
    vertices: list[float] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None:
            raise ValueError("CAD face has no triangulation")
        if len(vertices) + mesh.NbTriangles() * 9 > MAX_TRIANGLES * 9:
            raise CadGeometryError()
        for index in range(1, mesh.NbTriangles() + 1):
            indices = list(mesh.Triangle(index).Get())
            if face.Orientation() == TopAbs_REVERSED:
                indices.reverse()
            for node_index in indices:
                point = mesh.Node(node_index).Transformed(location.Transformation())
                values = [point.X() / 1000, point.Y() / 1000, point.Z() / 1000]
                if any(not math.isfinite(v) or abs(v) > 1e6 for v in values):
                    raise ValueError("Invalid CAD coordinate")
                vertices.extend(values)
        explorer.Next()
    if not vertices:
        raise ValueError("CAD occurrence has no triangles")
    return vertices


def tessellate_step(content: str, occurrence_keys: list[str]) -> dict[str, Any]:
    if (
        not occurrence_keys
        or len(occurrence_keys) > 128
        or len(set(occurrence_keys)) != len(occurrence_keys)
        or any(not key or len(key) > 2048 for key in occurrence_keys)
        or len(content.encode()) > MAX_BYTES
        or _EXTERNAL.search(content) is not None
    ):
        raise ValueError("Invalid CAD scene selection")
    wanted = set(occurrence_keys)
    shapes: dict[str, Any] = {}

    def observe(key: str, shape: Any, is_assembly: bool) -> None:
        if key not in wanted:
            return
        if key in shapes or is_assembly:
            raise ValueError("Ambiguous CAD occurrence")
        shapes[key] = shape

    parse_step(content, shape_visitor=observe)
    if set(shapes) != wanted:
        raise ValueError("CAD occurrence missing")
    return _bounded_meshes(shapes)


def _bounded_meshes(shapes: dict[str, Any]) -> dict[str, Any]:
    for deflection, angle in ((0.1, 0.5), (0.4, 0.8), (2.0, 1.5)):
        try:
            output: dict[str, Any] = {}
            count = 0
            for key, shape in shapes.items():
                vertices = _triangles(shape, deflection, angle)
                count += len(vertices)
                if count > MAX_TRIANGLES * 9:
                    raise CadGeometryError()
                output[key] = {"vertices": vertices}
            if len(json.dumps(output).encode()) > min(MAX_BYTES, MESH_BYTES):
                raise CadGeometryError()
            return output
        except CadGeometryError:
            continue
    raise CadGeometryError()


async def tessellate_isolated(content: str, keys: list[str]) -> dict[str, Any]:
    """Kill native OCCT on timeout/cancellation; paths are generated, never user supplied."""
    if len(content.encode()) > MAX_BYTES:
        raise ValueError("CAD export exceeds scene limit")
    with tempfile.TemporaryDirectory(prefix="solus-scene-") as directory:
        source = Path(directory) / "input.json"
        target = Path(directory) / "output.json"
        source.write_text(json.dumps({"content": content, "keys": keys}))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "solus_api.connectors.step_tessellation",
            str(source),
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                code = await process.wait()
            if code or not target.is_file() or target.stat().st_size > MAX_BYTES:
                raise ValueError("CAD tessellation failed or exceeds limits")
            result: dict[str, Any] = json.loads(target.read_text())
            if result == {"error": "geometry_limit_exceeded"}:
                raise CadGeometryError()
            return result
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


def _apply_resource_limits() -> None:
    """Best-effort child caps. macOS refuses `RLIMIT_AS` ("current limit exceeds maximum
    limit"), which previously killed the worker on every Mac. Where a cap cannot be set the
    wall-clock timeout, input/output size bounds and triangle limits still apply."""
    import resource

    for kind, limit in (
        (resource.RLIMIT_AS, 2 * 1024**3),
        (resource.RLIMIT_CPU, 20),
    ):
        try:
            resource.setrlimit(kind, (limit, limit))
        except (ValueError, OSError):
            continue


def _main() -> None:
    _apply_resource_limits()
    source, target = map(Path, sys.argv[1:])
    if source.stat().st_size > MAX_BYTES * 2:
        raise ValueError("Oversized process input")
    payload = json.loads(source.read_text())
    try:
        result = tessellate_step(payload["content"], payload["keys"])
    except CadGeometryError:
        result = {"error": "geometry_limit_exceeded"}
    target.write_text(json.dumps(result))


if __name__ == "__main__":
    _main()
