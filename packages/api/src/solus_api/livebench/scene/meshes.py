"""Explicit STL bytes to bounded triangles; never follows a mesh path or URI."""

import hashlib
import math
import re
import struct
import xml.etree.ElementTree as ET
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
MAX_TRIANGLES = 50_000
_NUMBER = r"[-+]?(?:\d{1,24}(?:\.\d{0,24})?|\.\d{1,24})(?:[eE][-+]?\d{1,4})?"
_VECTOR = rf"({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})"
_FACET = re.compile(
    rf"\s*facet\s+normal\s+{_VECTOR}\s+outer\s+loop\s+vertex\s+{_VECTOR}\s+vertex\s+{_VECTOR}\s+vertex\s+{_VECTOR}\s+endloop\s+endfacet",
    re.IGNORECASE,
)


def _finite(values: list[float]) -> None:
    if any(not math.isfinite(v) or abs(v) > 1e6 for v in values):
        raise ValueError("Invalid STL coordinate")


def stl_vertices(content: bytes) -> list[float]:
    if len(content) > MAX_BYTES:
        raise ValueError("STL exceeds size limit")
    if len(content) >= 84:
        count = struct.unpack_from("<I", content, 80)[0]
        if len(content) == 84 + count * 50:
            if not 0 < count <= MAX_TRIANGLES:
                raise ValueError("Invalid triangle count")
            vertices: list[float] = []
            for index in range(count):
                values = list(struct.unpack_from("<12f", content, 84 + index * 50))
                _finite(values)
                vertices.extend(values[3:])
            return vertices
    return _ascii_vertices(content)


def _ascii_vertices(content: bytes) -> list[float]:
    try:
        text = content.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ValueError("Invalid STL encoding") from None
    first, separator, rest = text.partition("\n")
    if not separator or not first.lower().startswith("solid") or len(first) > 512:
        raise ValueError("Invalid ASCII STL header")
    vertices = []
    cursor = 0
    while True:
        match = _FACET.match(rest, cursor)
        if match is None:
            break
        values = [float(v) for v in match.groups()]
        _finite(values)
        vertices.extend(values[3:])
        if len(vertices) > MAX_TRIANGLES * 9:
            raise ValueError("Too many triangles")
        cursor = match.end()
    if not vertices or not re.fullmatch(r"\s*endsolid[^\r\n]*\s*", rest[cursor:], re.IGNORECASE):
        raise ValueError("Invalid ASCII STL facets")
    return vertices


class MeshCatalog:
    def __init__(self, root: ET.Element, supplied: dict[str, bytes]):
        self.supplied = supplied
        self.used: set[str] = set()
        self.vertex_count = 0
        self.meshes: dict[str, dict[str, list[float]]] = {}
        self.assets: dict[str, ET.Element] = {}
        for asset in root.findall("./asset/mesh"):
            key = asset.get("name")
            if not key or key in self.assets:
                raise ValueError("Ambiguous mesh asset name")
            self.assets[key] = asset

    def visual(self, item: ET.Element, mjcf: bool, warnings: list[str]) -> dict[str, Any]:
        asset = self.assets.get(item.get("mesh", "")) if mjcf else item
        reference = asset.get("file" if mjcf else "filename") if asset is not None else None
        scale = (
            [float(v) for v in asset.get("scale", "1 1 1").split()]
            if asset is not None
            else [1.0, 1.0, 1.0]
        )
        _finite(scale)
        if len(scale) != 3 or any(v <= 0 for v in scale):
            raise ValueError("Invalid mesh scale")
        key = None
        if reference in self.supplied:
            assert reference is not None
            self.used.add(reference)
            key = hashlib.sha256(reference.encode()).hexdigest()
            if key not in self.meshes:
                self.meshes[key] = {"vertices": stl_vertices(self.supplied[reference])}
            self.vertex_count += len(self.meshes[key]["vertices"])
            if self.vertex_count > MAX_TRIANGLES * 9:
                raise ValueError("Model exceeds triangle limit")
        if key is None:
            warnings.append("Mesh geometry unavailable: select its exact referenced STL artifact.")
        return {"mesh_key": key, "scale": scale}

    def finish(self) -> dict[str, dict[str, list[float]]]:
        if self.used != set(self.supplied):
            raise ValueError("Mesh references must match exactly")
        return self.meshes
