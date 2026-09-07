"""The suffix→tool table, skip list, and caps (docs/api/local-folder.md §1/§4).

Suffix matching is case-insensitive (`.STEP`, `.PY`) — the table is stored
lowercase and the probe lowercases the candidate. Python dependency files
(`requirements*.txt`, `pyproject.toml`, `environment.yml` —
docs/api/code-environment.md §3) are matched by NAME and belong to the
`python` tool, so an edit to one changes the digest.
"""

from pathlib import PurePath

#: Dependency declaration files matched by exact (lower-cased) name …
DEPENDENCY_FILE_NAMES: frozenset[str] = frozenset({"pyproject.toml", "environment.yml"})
#: … plus the `requirements*.txt` family (prefix + suffix).
_REQUIREMENTS_PREFIX = "requirements"
_REQUIREMENTS_SUFFIX = ".txt"
DEPENDENCY_TOOL = "python"


def is_dependency_file(path: str | PurePath) -> bool:
    """True for `requirements*.txt`, `pyproject.toml`, `environment.yml`
    (case-insensitive on the file name)."""
    name = PurePath(path).name.lower()
    return name in DEPENDENCY_FILE_NAMES or (
        name.startswith(_REQUIREMENTS_PREFIX) and name.endswith(_REQUIREMENTS_SUFFIX)
    )


TOOL_SUFFIXES: dict[str, frozenset[str]] = {
    "kicad": frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb"}),
    "altium": frozenset({".prjpcb", ".schdoc", ".pcbdoc"}),
    "cad": frozenset({".step", ".stp", ".sldprt", ".sldasm", ".iges", ".igs", ".f3d"}),
    "arduino": frozenset({".ino"}),
    "python": frozenset({".py"}),
}

_SUFFIX_TO_TOOL: dict[str, str] = {
    suffix: tool for tool, suffixes in TOOL_SUFFIXES.items() for suffix in suffixes
}

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", "solus-artifacts"}
)

#: Scan ceiling: past this many tool-relevant files the result is `truncated`.
MAX_FILES = 2000
#: Files larger than this report `hash: null` (the digest uses the size).
MAX_HASH_BYTES = 32 * 1024 * 1024
#: Streaming read size for the per-file blake2b-128 hash.
HASH_CHUNK_BYTES = 1024 * 1024


def tool_for(path: str | PurePath) -> str | None:
    """The tool a file belongs to by suffix (or by dependency-file name), or
    None when it is not relevant."""
    if is_dependency_file(path):
        return DEPENDENCY_TOOL
    return _SUFFIX_TO_TOOL.get(PurePath(path).suffix.lower())
