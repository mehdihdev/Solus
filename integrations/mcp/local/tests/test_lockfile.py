"""SOLUSDEV-249 — `requirements.lock.txt` is the hash-pinned closure of `mcp`
and nothing else (derived from the altium lock's `# via` graph; the shell had
no outbound network to `uv pip compile`)."""

import re

from .local_paths import LOCKFILE  # isort: skip

# Only reachable from eda-agent (the altium fork), never from `mcp`.
ALTIUM_ONLY_DEPS = frozenset({"numpy", "networkx", "olefile", "psutil", "eda-agent"})

# `mcp`'s direct runtime dependencies at the pinned version — every one must
# be present (mirrors what `# via mcp` names in the source lock).
MCP_DIRECT_DEPS = frozenset(
    {
        "anyio",
        "httpx",
        "httpx-sse",
        "jsonschema",
        "pydantic",
        "pydantic-settings",
        "pyjwt",
        "python-multipart",
        "pywin32",
        "sse-starlette",
        "starlette",
        "typing-extensions",
        "typing-inspection",
        "uvicorn",
    }
)


def _logical_lines() -> list[str]:
    joined: list[str] = []
    pending = ""
    for raw in LOCKFILE.read_text(encoding="utf-8").splitlines():
        line = pending + raw.strip()
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        pending = ""
        if line:
            joined.append(line)
    return joined


def _requirements() -> list[str]:
    return [line for line in _logical_lines() if not line.startswith("#")]


def _names() -> set[str]:
    return {line.split("==", 1)[0].lower().replace("_", "-") for line in _requirements()}


def test_lockfile_exists_and_every_requirement_is_hash_pinned() -> None:
    assert LOCKFILE.is_file()
    requirement_re = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;\\]+"
        r"(?:\s*;[^-][^\\]*?)?"
        r"(?:\s+--hash=sha256:[0-9a-f]{64})+$"
    )
    lines = _requirements()
    assert lines, "requirements.lock.txt has no requirement lines"
    for line in lines:
        assert not line.startswith("-"), f"option/editable line in lockfile: {line!r}"
        assert requirement_re.match(line), f"not fully hash-pinned: {line!r}"


def test_lockfile_pins_mcp_and_its_direct_dependencies() -> None:
    names = _names()
    assert "mcp" in names
    missing = MCP_DIRECT_DEPS - names
    assert not missing, f"lockfile is missing mcp dependencies {sorted(missing)}"


def test_lockfile_carries_nothing_outside_the_mcp_closure() -> None:
    leaked = _names() & ALTIUM_ONLY_DEPS
    assert not leaked, f"altium-only packages leaked into the local lock: {sorted(leaked)}"


def test_pywin32_keeps_its_windows_marker() -> None:
    pywin32 = [line for line in _requirements() if line.startswith("pywin32==")]
    assert len(pywin32) == 1
    assert "sys_platform == 'win32'" in pywin32[0]


def test_lockfile_header_states_its_derivation() -> None:
    header = "\n".join(line for line in _logical_lines() if line.startswith("#"))
    assert "altium" in header and "mcp" in header, (
        "the header must say the lock was derived from the altium lock's mcp closure"
    )
