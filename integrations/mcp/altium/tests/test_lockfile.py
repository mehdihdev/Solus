"""The fork lockfile is complete and hash-pinned (SOLUSDEV-102 ALT-2).

`requirements.lock.txt` is what the companion install step materializes the
fork-private virtualenv from, with `--require-hashes` semantics — so every
requirement must be exact-pinned (`==`) and carry at least one `--hash=`.
Standalone on purpose: this fork's tests/ gains its conftest in a later task.
"""

import re
from pathlib import Path

FORK_DIR = Path(__file__).resolve().parents[1]
LOCKFILE = FORK_DIR / "requirements.lock.txt"

# Upstream's declared runtime dependencies (upstream/pyproject.toml) — the
# lockfile must cover every one of them.
UPSTREAM_RUNTIME_DEPS = frozenset(
    {"mcp", "pydantic", "psutil", "pywin32", "networkx", "numpy", "olefile"}
)


def _requirement_blocks() -> list[list[str]]:
    """Group physical lines into logical requirement blocks (continuations
    join via trailing backslash; comments and blanks are skipped)."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in LOCKFILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        current.append(line)
        if not line.endswith("\\"):
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def test_lockfile_exists_and_is_nonempty() -> None:
    assert LOCKFILE.is_file(), "requirements.lock.txt is missing"
    assert _requirement_blocks(), "lockfile contains no requirements"


def test_every_requirement_is_exact_pinned() -> None:
    for block in _requirement_blocks():
        head = block[0]
        assert re.match(r"^[A-Za-z0-9._-]+==", head), f"unpinned requirement: {head!r}"


def test_every_requirement_carries_a_hash() -> None:
    for block in _requirement_blocks():
        assert any("--hash=sha256:" in line for line in block), (
            f"requirement without --hash: {block[0]!r}"
        )


def test_upstream_runtime_deps_are_all_covered() -> None:
    pinned = {re.split(r"==", block[0])[0].lower() for block in _requirement_blocks()}
    missing = {dep for dep in UPSTREAM_RUNTIME_DEPS if dep.lower() not in pinned}
    assert not missing, f"lockfile is missing upstream runtime deps: {sorted(missing)}"


def test_pywin32_keeps_its_windows_marker() -> None:
    pywin32_blocks = [b for b in _requirement_blocks() if b[0].startswith("pywin32==")]
    assert len(pywin32_blocks) == 1
    assert "sys_platform == 'win32'" in pywin32_blocks[0][0], (
        "pywin32 must stay marker-scoped to Windows"
    )
