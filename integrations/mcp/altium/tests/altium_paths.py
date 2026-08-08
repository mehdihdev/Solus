"""Bootstrap + canonical paths for the altium fork's tests (SOLUSDEV-102 ALT-3).

Fork test dirs must NOT ship a conftest.py (a module literally named
`conftest` on sys.path shadows `packages/api/tests/conftest` for the API
tests that import it by bare name), so this module carries the import
bootstrap instead, and every sibling test module imports it FIRST:

* repo-root discovery mirrors the kicad fork's tests/paths.py convention:
  walk up to the first directory carrying `.git` (a dir in the main checkout,
  a file in a worktree), falling back to the TOPMOST `pyproject.toml` seen
  (the uv workspace root) for git-less checkouts such as source archives;
* `integrations/mcp/tests/_lib` (the shared vendored-tree hasher) goes on
  sys.path;
* the fork's Solus overlay package is importable under the UNIQUE name
  `altium_solus` via `overlay_module()` — never as bare `solus` — because the
  kicad fork's tests import THEIR overlay as `solus` in the same pytest
  session and one sys.modules slot cannot hold both forks' packages. The
  overlay's internal imports are relative, so the package works under any
  name (`solus` at runtime under bin/launch, `altium_solus` here);
* bytecode writing is disabled so importing vendored/overlay code never
  litters the tree (the PROVENANCE tree hash covers a byte-pristine
  `upstream/`).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: The sys.modules name the fork's `solus/` package is imported under in
#: tests — unique across forks (see module docstring).
OVERLAY_PACKAGE_NAME = "altium_solus"


def find_repo_root(start: Path | None = None) -> Path:
    """Repo root above *start* (default: this file). See module docstring."""
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


REPO_ROOT: Path = find_repo_root()
MCP_ROOT: Path = REPO_ROOT / "integrations" / "mcp"
FORK_DIR: Path = MCP_ROOT / "altium"
UPSTREAM_DIR: Path = FORK_DIR / "upstream"
UPSTREAM_SRC: Path = UPSTREAM_DIR / "src"
SOLUS_DIR: Path = FORK_DIR / "solus"
LAUNCH: Path = FORK_DIR / "bin" / "launch"
LAUNCH_CMD: Path = FORK_DIR / "bin" / "launch.cmd"
PROVENANCE: Path = FORK_DIR / "PROVENANCE.md"

# Importing vendored/overlay code must never write bytecode into the tree.
sys.dont_write_bytecode = True

_LIB = str(MCP_ROOT / "tests" / "_lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)


def load_overlay_package() -> ModuleType:
    """The fork's `solus/` package, imported under `altium_solus` (unique
    across forks; see module docstring). Idempotent."""
    existing = sys.modules.get(OVERLAY_PACKAGE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        OVERLAY_PACKAGE_NAME,
        SOLUS_DIR / "__init__.py",
        submodule_search_locations=[str(SOLUS_DIR)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the overlay package from {SOLUS_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[OVERLAY_PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def overlay_module(name: str) -> ModuleType:
    """`solus/<name>.py`, imported as `altium_solus.<name>`."""
    load_overlay_package()
    return importlib.import_module(f"{OVERLAY_PACKAGE_NAME}.{name}")
