"""Ratchet: `GraphEdge(` is constructed in exactly two places (SOLUSDEV-320 T2)."""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "solus_api"
ALLOWED = {"graph/edges.py", "connectors/runtime.py"}
_PATTERN = re.compile(  # the model's own `class` line is the one legitimate `GraphEdge(`
    r"^(?!class ).*(?:\bGraphEdge\s*\(|insert\(\s*GraphEdge\b).*$", re.M
)
_SKIPPED = {"tests", "migrations"}


def edge_offenders(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root)}:{match.group(0).strip()}"
        for path in sorted(root.rglob("*.py"))
        if path.relative_to(root).parts[0] not in _SKIPPED
        and path.relative_to(root).as_posix() not in ALLOWED
        for match in _PATTERN.finditer(path.read_text(encoding="utf-8"))
    ]


def test_only_the_edge_writer_and_connector_runtime_construct_graph_edges() -> None:
    assert all((SRC_ROOT / allowed).is_file() for allowed in ALLOWED)
    assert edge_offenders(SRC_ROOT) == []


def test_ratchet_catches_an_injected_construction(tmp_path: Path) -> None:
    (tmp_path / "graph").mkdir()
    (tmp_path / "graph" / "edges.py").write_text("x = GraphEdge(id=1)\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("y = GraphEdge(id=2)\n")
    (tmp_path / "rogue.py").write_text("row = GraphEdge(\n")
    assert edge_offenders(tmp_path) == ["rogue.py:row = GraphEdge("]


def test_ratchet_matches_spaced_and_insert_constructions(tmp_path: Path) -> None:
    (tmp_path / "contests").mkdir()
    (tmp_path / "contests" / "a.py").write_text("row = GraphEdge (id=1)\n")
    (tmp_path / "b.py").write_text(
        "stmt = insert(GraphEdge).values()\nup = pg_insert( GraphEdge )\n"
    )
    assert edge_offenders(tmp_path) == [
        "b.py:stmt = insert(GraphEdge).values()",
        "b.py:up = pg_insert( GraphEdge )",
        "contests/a.py:row = GraphEdge (id=1)",
    ]
