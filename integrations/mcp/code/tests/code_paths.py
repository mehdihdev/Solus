"""Bootstrap + canonical paths for the `code` server's tests (SOLUSDEV-250).

Same trick as `integrations/mcp/local/tests/local_paths.py`, with two
deliberate differences:

* the server's Solus-authored `solus/` package is importable under the UNIQUE
  name `code_solus` via `overlay_module()` — never as bare `solus` (the kicad
  fork's tests own that sys.modules slot in the same pytest session);
* this `tests/` directory is ROOTLESS (no `__init__.py`, and none at the fork
  root either) with `test_code_*` file names: a package named `code` would
  shadow the stdlib `code` module for the whole session (pdb, `breakpoint()`),
  and a bare `tests` package is already taken by other trees. This helper is
  therefore imported by bare name (`from code_paths import …`).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

OVERLAY_PACKAGE_NAME = "code_solus"


def find_repo_root(start: Path | None = None) -> Path:
    """Repo root above *start*: the first directory carrying `.git`, else the
    topmost `pyproject.toml` seen."""
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
FORK_DIR: Path = MCP_ROOT / "code"
SOLUS_DIR: Path = FORK_DIR / "solus"
LAUNCH: Path = FORK_DIR / "bin" / "launch"
ALLOWLIST_YAML: Path = FORK_DIR / "allowlist.yaml"
PROVENANCE: Path = FORK_DIR / "PROVENANCE.md"
SECURITY_REVIEW: Path = FORK_DIR / "SECURITY_REVIEW.md"
LOCKFILE: Path = FORK_DIR / "requirements.lock.txt"
LOCAL_LOCKFILE: Path = MCP_ROOT / "local" / "requirements.lock.txt"
FORK_README: Path = FORK_DIR / "README.md"
ENV_ALLOW: Path = SOLUS_DIR / "env.allow"
PROVENANCE_TEMPLATE: Path = MCP_ROOT / "PROVENANCE.template.md"

sys.dont_write_bytecode = True


def load_overlay_package() -> ModuleType:
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
    """`solus/<name>.py`, imported as `code_solus.<name>`."""
    load_overlay_package()
    return importlib.import_module(f"{OVERLAY_PACKAGE_NAME}.{name}")
