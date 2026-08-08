"""Re-export shim (SOLUSDEV-102 ALT-2, human-approved Option A).

The vendored-tree hasher is shared by every fork and lives in ONE place —
`integrations/mcp/tests/_lib/vendored_tree_hash.py` — so a security-critical
hash never drifts between per-fork copies. This module keeps every existing
`from tree_hash import ...` in the kicad tests working, and does its own
sys.path bootstrap (fork test dirs must NOT ship a conftest.py: a module
literally named `conftest` on sys.path shadows `packages/api/tests/conftest`
for the API tests that import it by bare name).
"""

import sys
from pathlib import Path

_LIB = str(Path(__file__).resolve().parents[2] / "tests" / "_lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from vendored_tree_hash import IGNORED_NAMES, git_tree_hash  # noqa: E402

__all__ = ["IGNORED_NAMES", "git_tree_hash"]
