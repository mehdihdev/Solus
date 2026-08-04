"""Canonical repo-root-relative paths of the committed KiCad sample fixture (SOLUSDEV-100 T3).

There is exactly ONE copy of the `solus_sample` project on disk —
`integrations/mcp/kicad/tests/fixtures/solus_sample/` — and every consumer
(this test tree, `packages/api/tests/fixtures/kicad_project.py`) resolves it
through the same convention: walk up from the consuming file to the repo root
(the first directory carrying `.git` — a dir in the main checkout, a file in a
worktree), falling back to the TOPMOST `pyproject.toml` seen (the uv workspace
root) for git-less checkouts such as source archives.
"""

from __future__ import annotations

from pathlib import Path

_FIXTURE_REL = Path("integrations") / "mcp" / "kicad" / "tests" / "fixtures"


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
FIXTURES_DIR: Path = REPO_ROOT / _FIXTURE_REL
SOLUS_SAMPLE_DIR: Path = FIXTURES_DIR / "solus_sample"
SOLUS_SAMPLE_PRO: Path = SOLUS_SAMPLE_DIR / "solus_sample.kicad_pro"
SOLUS_SAMPLE_SCH: Path = SOLUS_SAMPLE_DIR / "solus_sample.kicad_sch"
SOLUS_SAMPLE_NETLIST: Path = SOLUS_SAMPLE_DIR / "solus_sample.net.xml"
SOLUS_SAMPLE_LARGE_NETLIST: Path = SOLUS_SAMPLE_DIR / "solus_sample_large.net.xml"
#: M6-fixture (Phase 4): same design as SOLUS_SAMPLE_NETLIST, with adversarial
#: instruction strings embedded in component value/MPN fields and a net name
#: — a valid, zero-warning kicadxml netlist whose hostile content must land
#: verbatim as inert DATA (tests/test_hostile_fixture.py).
SOLUS_SAMPLE_HOSTILE_NETLIST: Path = SOLUS_SAMPLE_DIR / "solus_sample_hostile.net.xml"
