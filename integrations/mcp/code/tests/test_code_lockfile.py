"""SOLUSDEV-250 — `requirements.lock.txt` is the hash-pinned `mcp` closure,
byte-identical (below the header) to the local fork's lock it was copied from."""

import re

from code_paths import LOCAL_LOCKFILE, LOCKFILE  # isort: skip

ALTIUM_ONLY_DEPS = frozenset({"numpy", "networkx", "olefile", "psutil", "eda-agent"})


def _logical_lines(path: object = None) -> list[str]:
    source = LOCKFILE if path is None else path
    assert hasattr(source, "read_text")
    joined: list[str] = []
    pending = ""
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = pending + raw.strip()
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        pending = ""
        if line:
            joined.append(line)
    return joined


def _requirements(path: object = None) -> list[str]:
    return [line for line in _logical_lines(path) if not line.startswith("#")]


def test_lockfile_exists_and_every_requirement_is_hash_pinned() -> None:
    assert LOCKFILE.is_file()
    requirement_re = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;\\]+"
        r"(?:\s*;[^-][^\\]*?)?"
        r"(?:\s+--hash=sha256:[0-9a-f]{64})+$"
    )
    lines = _requirements()
    assert lines
    for line in lines:
        assert not line.startswith("-"), line
        assert requirement_re.match(line), line


def test_lockfile_body_is_identical_to_the_local_forks() -> None:
    """Same server SDK, same closure, same hashes — one review covers both."""
    assert _requirements() == _requirements(LOCAL_LOCKFILE)


def test_lockfile_carries_mcp_and_nothing_altium_only() -> None:
    names = {line.split("==", 1)[0].lower() for line in _requirements()}
    assert "mcp" in names
    assert not (names & ALTIUM_ONLY_DEPS)


def test_lockfile_header_names_this_fork_and_its_derivation() -> None:
    header = "\n".join(line for line in _logical_lines() if line.startswith("#"))
    assert "integrations/mcp/code/" in header
    assert "altium" in header and "mcp" in header
