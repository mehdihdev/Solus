"""Bootstrap + canonical paths for the `local` server's tests (SOLUSDEV-249).

* repo-root discovery mirrors the kicad fork's tests/paths.py convention:
  walk up to the first directory carrying `.git` (a dir in the main checkout,
  a file in a worktree), falling back to the TOPMOST `pyproject.toml` seen;
* the server's Solus-authored `solus/` package is importable under the UNIQUE
  name `local_solus` via `overlay_module()` — never as bare `solus` — because
  the kicad fork's tests import THEIR overlay as `solus` in the same pytest
  session and one sys.modules slot cannot hold two forks' packages. The
  package's internal imports are relative, so it works under any name
  (`solus` at runtime under bin/launch, `local_solus` here);
* bytecode writing is disabled so importing overlay code never litters the
  tree.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: The sys.modules name the server's `solus/` package is imported under in
#: tests — unique across forks (see module docstring).
OVERLAY_PACKAGE_NAME = "local_solus"


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
FORK_DIR: Path = MCP_ROOT / "local"
SOLUS_DIR: Path = FORK_DIR / "solus"
LAUNCH: Path = FORK_DIR / "bin" / "launch"
ALLOWLIST_YAML: Path = FORK_DIR / "allowlist.yaml"
PROVENANCE: Path = FORK_DIR / "PROVENANCE.md"
SECURITY_REVIEW: Path = FORK_DIR / "SECURITY_REVIEW.md"
LOCKFILE: Path = FORK_DIR / "requirements.lock.txt"
FORK_README: Path = FORK_DIR / "README.md"
ENV_ALLOW: Path = SOLUS_DIR / "env.allow"
PROVENANCE_TEMPLATE: Path = MCP_ROOT / "PROVENANCE.template.md"

# Importing overlay code must never write bytecode into the tree.
sys.dont_write_bytecode = True


def load_overlay_package() -> ModuleType:
    """The server's `solus/` package, imported under `local_solus` (unique
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
    """`solus/<name>.py`, imported as `local_solus.<name>`."""
    load_overlay_package()
    return importlib.import_module(f"{OVERLAY_PACKAGE_NAME}.{name}")
