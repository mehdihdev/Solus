"""Actual STEP cut geometry and bounded isolated scene tessellation."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from solus_api.connectors.step_parser import parse_step, step_reader_available
from solus_api.connectors.step_tessellation import tessellate_step


@pytest.mark.skipif(not step_reader_available(), reason="OCCT unavailable")
def test_interior_cut_changes_triangles_without_changing_bbox(tmp_path: Path) -> None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    box = BRepPrimAPI_MakeBox(2, 3, 4).Shape()
    cut = BRepAlgoAPI_Cut(box, BRepPrimAPI_MakeBox(gp_Pnt(0.5, 0.5, 0), 1, 1, 4).Shape()).Shape()
    outputs = []
    bounds = []
    for i, shape in enumerate((box, cut)):
        writer = STEPControl_Writer()
        writer.Transfer(shape, STEPControl_AsIs)
        path = tmp_path / f"{i}.step"
        writer.Write(str(path))
        text = path.read_text()
        node = parse_step(text).nodes[0]
        bounds.append(node.properties["geometry"]["dimensions"])
        output = tessellate_step(text, [node.key])
        outputs.append(output[node.key]["vertices"])
    assert bounds[0] == bounds[1]
    assert outputs[0] != outputs[1]
    assert max(outputs[0]) <= 0.004001


@pytest.mark.parametrize("keys", [[], ["a", "a"], ["a"] * 129])
def test_invalid_occurrence_selection_rejected(keys: list[str]) -> None:
    with pytest.raises(ValueError):
        tessellate_step("", keys)


async def test_native_tessellation_deadline_kills_child(monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_api.connectors import step_tessellation as module

    class Process:
        returncode = None
        killed = False

        async def wait(self) -> int:
            if self.killed:
                self.returncode = -9
                return -9
            await asyncio.sleep(60)
            return 0

        def kill(self) -> None:
            self.killed = True

    process = Process()

    async def launch(*args: object, **kwargs: object) -> Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await module.tessellate_isolated("text", ["part"])
    assert process.killed


@pytest.mark.parametrize(
    "token", ["DOCUMENT_FILE", "EXTERNAL_SOURCE", "EXTERNALLY_DEFINED_REPRESENTATION"]
)
def test_external_step_resources_refused_before_native_reader(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    from unittest.mock import Mock

    from solus_api.connectors import step_tessellation as module

    parser = Mock()
    monkeypatch.setattr(module, "parse_step", parser)
    with pytest.raises(ValueError):
        module.tessellate_step(f"#1={token}('outside.step');", ["part"])
    parser.assert_not_called()


def test_adaptive_retry_keeps_all_occurrences_and_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors import step_tessellation as module

    calls: list[tuple[str, float]] = []

    def parse(content: str, *, shape_visitor: Callable[[str, Any, bool], None]) -> None:
        shape_visitor("a", "shape-a", False)
        shape_visitor("b", "shape-b", False)

    def triangles(shape: str, deflection: float, angle: float) -> list[float]:
        calls.append((shape, deflection))
        return [0.0] * (18 if deflection == 0.1 else 9)

    monkeypatch.setattr(module, "parse_step", parse)
    monkeypatch.setattr(module, "_triangles", triangles)
    monkeypatch.setattr(module, "MAX_TRIANGLES", 2)
    result = module.tessellate_step("STEP", ["a", "b"])
    assert set(result) == {"a", "b"}
    assert sum(len(v["vertices"]) for v in result.values()) == 18
    assert calls == [("shape-a", 0.1), ("shape-b", 0.1), ("shape-a", 0.4), ("shape-b", 0.4)]


def test_adaptive_exhaustion_reports_safe_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_api.connectors import step_tessellation as module

    monkeypatch.setattr(
        module, "parse_step", lambda content, shape_visitor: shape_visitor("a", object(), False)
    )
    monkeypatch.setattr(module, "_triangles", lambda *args: [0.0] * 18)
    monkeypatch.setattr(module, "MAX_TRIANGLES", 1)
    with pytest.raises(module.CadGeometryError, match="geometry_limit_exceeded"):
        module.tessellate_step("private STEP content", ["a"])


async def test_isolated_limit_error_is_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from pathlib import Path
    from unittest.mock import AsyncMock

    from solus_api.connectors import step_tessellation as module

    async def launch(*args: object, **kwargs: object) -> AsyncMock:
        Path(str(args[-1])).write_text(json.dumps({"error": "geometry_limit_exceeded"}))
        process = AsyncMock()
        process.returncode = 0
        process.wait.return_value = 0
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with pytest.raises(module.CadGeometryError, match="^geometry_limit_exceeded$"):
        await module.tessellate_isolated("private geometry", ["part"])


def test_adaptive_retry_reserves_final_serialization_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from solus_api.connectors import step_tessellation as module

    monkeypatch.setattr(
        module, "parse_step", lambda content, shape_visitor: shape_visitor("a", object(), False)
    )
    monkeypatch.setattr(
        module, "_triangles", lambda shape, linear, angle: [0.0] * (18 if linear == 0.1 else 9)
    )
    monkeypatch.setattr(
        module, "MESH_BYTES", len(json.dumps({"a": {"vertices": [0.0] * 9}}).encode())
    )
    assert len(module.tessellate_step("STEP", ["a"])["a"]["vertices"]) == 9


def test_resource_limits_tolerate_a_platform_that_refuses_address_space_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS rejects RLIMIT_AS ("current limit exceeds maximum limit"); that must not kill the
    tessellation worker. The remaining limits (CPU) are still applied."""
    import resource

    from solus_api.connectors.step_tessellation import _apply_resource_limits

    applied: list[int] = []

    def setrlimit(kind: int, limits: tuple[int, int]) -> None:
        if kind == resource.RLIMIT_AS:
            raise ValueError("current limit exceeds maximum limit")
        applied.append(kind)

    monkeypatch.setattr(resource, "setrlimit", setrlimit)
    _apply_resource_limits()
    assert applied == [resource.RLIMIT_CPU]
