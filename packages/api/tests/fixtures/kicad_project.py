"""Canonical paths of the committed KiCad sample project (SOLUSDEV-100 T3) — API side.

The `solus_sample` fixture lives ONCE on disk, under
`integrations/mcp/kicad/tests/fixtures/solus_sample/`. This module re-exports
the SAME canonical paths for `packages/api` tests: it finds the repo root with
the same convention as `integrations/mcp/kicad/tests/paths.py` (walk up to
`.git`, falling back to the topmost `pyproject.toml` — never the nearest one,
which here would be `packages/api/pyproject.toml`), then loads that module by
path and re-exports its constants, so the two resolvers cannot drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Repo root above *start* (default: this file); same convention as paths.py."""
    origin = (start or Path(__file__)).resolve()
    topmost_pyproject: Path | None = None
    for directory in (origin, *origin.parents):
        if (directory / ".git").exists():
            return directory
        if (directory / "pyproject.toml").is_file():
            topmost_pyproject = directory
    if topmost_pyproject is None:
        raise FileNotFoundError(f"no .git or pyproject.toml above {origin}")
    return topmost_pyproject


def _load_canonical_paths() -> object:
    module_path = find_repo_root() / "integrations" / "mcp" / "kicad" / "tests" / "paths.py"
    spec = importlib.util.spec_from_file_location("_solus_kicad_fixture_paths", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load canonical fixture paths from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_paths = _load_canonical_paths()

REPO_ROOT: Path = _paths.REPO_ROOT  # type: ignore[attr-defined]
FIXTURES_DIR: Path = _paths.FIXTURES_DIR  # type: ignore[attr-defined]
SOLUS_SAMPLE_DIR: Path = _paths.SOLUS_SAMPLE_DIR  # type: ignore[attr-defined]
SOLUS_SAMPLE_PRO: Path = _paths.SOLUS_SAMPLE_PRO  # type: ignore[attr-defined]
SOLUS_SAMPLE_SCH: Path = _paths.SOLUS_SAMPLE_SCH  # type: ignore[attr-defined]
SOLUS_SAMPLE_NETLIST: Path = _paths.SOLUS_SAMPLE_NETLIST  # type: ignore[attr-defined]
SOLUS_SAMPLE_LARGE_NETLIST: Path = _paths.SOLUS_SAMPLE_LARGE_NETLIST  # type: ignore[attr-defined]
