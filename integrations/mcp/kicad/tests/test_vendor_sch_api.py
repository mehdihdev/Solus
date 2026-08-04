"""SOLUSDEV-100 T2a — the second vendored tree: `circuit-synth/kicad-sch-api`.

Locks the vendored library subset under `integrations/mcp/kicad/vendor/`
(ADR-031 fork model; human-ratified two-tree layout, F7):

- the pure library package `vendor/kicad_sch_api/` is importable with
  `vendor/` on sys.path, WITHOUT the stripped `mcp`/`fastmcp`/`jinja2`
  dependencies ever loading (the bundled `mcp_server/` subpackage and the
  jinja2-dependent exporter are NOT vendored — the fork must not gain a
  second MCP server);
- the retained modules' only third-party import root is `sexpdata`
  (BSD-2-Clause — human-approved ACCEPTED LICENSE EXCEPTION, 2026-08-03);
- `vendor/LICENSE` is upstream's MIT text, verbatim;
- `PROVENANCE.md` carries the pinned SHA, the vendor tree hash (recomputed
  here on every run), one row per exclusion/strip, and the BSD-2 exception;
- `requirements.lock.txt` pins `sexpdata` with hashes;
- the byte-stable round-trip PROMISE is measured against OUR fixture:
  upstream's format preservation does NOT reproduce the Solus sample
  byte-for-byte (strict xfail below documents the exact deviation — the
  load-bearing truth for T2b's write-guard design).
"""

import ast
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tree_hash import git_tree_hash  # isort: skip
from paths import SOLUS_SAMPLE_SCH

REPO_ROOT = Path(__file__).resolve().parents[4]
FORK = REPO_ROOT / "integrations" / "mcp" / "kicad"
VENDOR = FORK / "vendor"
PACKAGE = VENDOR / "kicad_sch_api"
PROVENANCE = FORK / "PROVENANCE.md"
LOCKFILE = FORK / "requirements.lock.txt"

PINNED_SHA = "505bca23e91cf3fa6e3b66976e529e775eada3ba"
UPSTREAM_REPO = "https://github.com/circuit-synth/kicad-sch-api"
VENDOR_SECTION_HEADING = "## Vendored library tree"

# Stripped at vendoring time: the fork must not gain a second MCP server, and
# the retained subset must not need mcp/fastmcp/jinja2 (PROVENANCE rows).
BANNED_IMPORT_ROOTS = ("mcp", "fastmcp", "jinja2")

# Paths that must NOT exist under vendor/ (each is a PROVENANCE row).
EXCLUDED_VENDOR_PATHS = (
    "mcp_server",  # bundled MCP server subpackage — the strip's core
    "CLAUDE.md",
    ".claude",
    "agents",
    ".mcp.json",
    ".github",  # F6 exclusion pattern (all five existed at the pinned SHA)
    "kicad_sch_api/exporters",  # jinja2/black-dependent Python-code generator
    "kicad_sch_api/cli/kicad_to_python.py",  # imports the excluded exporter
    "tests",  # upstream development material — not part of the library
    "docs",
    "examples",
    "scripts",
)

_IMPORT_PROBE = textwrap.dedent(
    """
    import json
    import sys

    sys.dont_write_bytecode = True
    sys.path.insert(0, sys.argv[1])
    import kicad_sch_api

    banned = [name for name in ("mcp", "fastmcp", "jinja2") if name in sys.modules]
    print(json.dumps({"banned": banned, "version": kicad_sch_api.__version__}))
    """
)

_ROUNDTRIP_PROBE = textwrap.dedent(
    """
    import json
    import sys

    sys.dont_write_bytecode = True
    sys.path.insert(0, sys.argv[1])
    import sexpdata

    import kicad_sch_api

    schematic = kicad_sch_api.Schematic.load(sys.argv[2])
    schematic.save_as(sys.argv[3], preserve_format=True)

    def tag_counts(path):
        with open(path, encoding="utf-8") as handle:
            tree = sexpdata.loads(handle.read())
        counts = {}
        for element in tree[1:]:
            if isinstance(element, list) and element:
                tag = str(element[0])
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    print(json.dumps({"src": tag_counts(sys.argv[2]), "out": tag_counts(sys.argv[3])}))
    """
)


def _interpreter_with_sexpdata() -> str:
    """The vendored library genuinely needs `sexpdata` (deliberately NOT a uv
    workspace dependency — it lives in the fork's hash-pinned lockfile). Use
    the fork's materialized private venv when present, else the test env."""
    candidates = []
    fork_venv_python = FORK / ".venv" / "bin" / "python3"
    if fork_venv_python.is_file():
        candidates.append(str(fork_venv_python))
    candidates.append(sys.executable)
    for interpreter in candidates:
        probe = subprocess.run(
            [interpreter, "-c", "import sexpdata"], capture_output=True, timeout=60
        )
        if probe.returncode == 0:
            return interpreter
    pytest.skip(
        "no interpreter with sexpdata: materialize integrations/mcp/kicad/.venv "
        "from requirements.lock.txt (companion install step) to arm these tests"
    )


def _run_probe(script: str, *args: str) -> str:
    interpreter = _interpreter_with_sexpdata()
    result = subprocess.run(
        [interpreter, "-c", script, str(VENDOR), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    return result.stdout.strip().splitlines()[-1]


# --- layout, license, exclusions ---------------------------------------------


def test_vendor_tree_has_the_ratified_two_tree_layout() -> None:
    assert (PACKAGE / "__init__.py").is_file(), "vendor/kicad_sch_api is not the package itself"
    assert (PACKAGE / "core" / "schematic.py").is_file()
    assert (VENDOR / "LICENSE").is_file(), "upstream LICENSE must ship with the vendored tree"
    assert (VENDOR / "pyproject.toml").is_file(), "dependency/entry-point declarations must ship"
    assert (VENDOR / "uv.lock").is_file(), "upstream lock is the pin source for sexpdata"


def test_vendor_license_is_mit_verbatim() -> None:
    text = (VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Copyright (c) 2025 Circuit-Synth" in text
    assert "Permission is hereby granted, free of charge" in text


def test_every_excluded_path_is_absent_from_the_vendor_tree() -> None:
    for excluded in EXCLUDED_VENDOR_PATHS:
        assert not (VENDOR / excluded).exists(), f"excluded path vendor/{excluded} was vendored"


def test_retained_modules_import_only_sexpdata_beyond_stdlib() -> None:
    """AST-level dependency truth: the vendored subset's only third-party
    import root is sexpdata — no mcp/fastmcp/jinja2/pydantic/black anywhere,
    guarded or not (upstream's pyproject still DECLARES more; PROVENANCE
    records that discrepancy instead of editing the verbatim file)."""
    roots: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name not in sys.stdlib_module_names and name != "kicad_sch_api":
                    roots.setdefault(name, set()).add(str(path.relative_to(VENDOR)))
    assert set(roots) <= {"sexpdata"}, f"unexpected third-party imports: {roots}"


# --- PROVENANCE ---------------------------------------------------------------


def _provenance_text() -> str:
    return PROVENANCE.read_text(encoding="utf-8")


def _vendor_section() -> str:
    text = _provenance_text()
    assert VENDOR_SECTION_HEADING in text, (
        f"PROVENANCE.md is missing the {VENDOR_SECTION_HEADING!r} section"
    )
    return text.split(VENDOR_SECTION_HEADING, 1)[1]


def _recomputed_vendor_tree_hash() -> str:
    """The git tree hash of the CURRENT vendor/ worktree state, computed in pure
    Python (`tree_hash.git_tree_hash`) — the CI python image ships no `git`
    binary, and this ADR-031 guard must run there most of all. Gitignored
    artifacts (__pycache__, caches) are skipped by name, so tool litter can
    never void the hash. Cross-checked against real git in test_tree_hash.py."""
    return git_tree_hash(REPO_ROOT / "integrations" / "mcp" / "kicad" / "vendor")


def test_provenance_pins_both_upstream_shas() -> None:
    text = _provenance_text()
    assert "98c9ea41cb393393a8bafd157a93e84431e00afb" in text, "T1a upstream SHA lost"
    assert PINNED_SHA in text, "kicad-sch-api pinned SHA missing"
    assert UPSTREAM_REPO in text, "kicad-sch-api canonical repo URL missing"


def test_provenance_vendor_tree_hash_matches_a_recompute() -> None:
    match = re.search(r"Vendor tree hash[^`]*`([0-9a-f]{40})`", _vendor_section())
    assert match, "vendor section must record its tree hash as a 40-hex `code` span"
    assert match.group(1) == _recomputed_vendor_tree_hash(), (
        "PROVENANCE vendor tree hash is stale — vendor/ changed without updating it "
        "(this mechanically voids the sign-offs)"
    )


def test_provenance_logs_every_vendor_exclusion_and_strip() -> None:
    section = _vendor_section()
    for marker in ("mcp_server/", ".github/", "exporters/", "kicad_to_python.py"):
        assert marker in section, f"vendor section is missing the {marker} exclusion/strip row"
    assert "sexpdata" in section, "the dependency-truth row (sexpdata only) is missing"


def test_provenance_records_the_bsd2_license_exception() -> None:
    section = _vendor_section()
    assert "BSD-2-Clause" in section, "sexpdata's BSD-2-Clause license must be recorded"
    assert "ACCEPTED LICENSE EXCEPTION" in section, (
        "the human-approved exception row (ADR-031 says MIT/Apache-2.0 only) is missing"
    )


def test_provenance_vendor_section_defers_to_the_shared_sign_off() -> None:
    assert "Security review sign-off" in _vendor_section(), (
        "the vendor section must point at the fork's shared sign-off section"
    )


# --- requirements.lock.txt ------------------------------------------------------


def test_lockfile_pins_sexpdata_with_hashes() -> None:
    text = LOCKFILE.read_text(encoding="utf-8")
    assert "sexpdata==1.0.2" in text, "sexpdata must be pinned for the vendored library"
    block = text.split("sexpdata==1.0.2", 1)[1].split("==", 1)[0]
    assert re.search(r"--hash=sha256:[0-9a-f]{64}", block), "sexpdata pin is not hash-pinned"


# --- runtime: import isolation and the round-trip truth ------------------------


def test_vendored_package_imports_without_mcp_fastmcp_or_jinja2() -> None:
    payload = json.loads(_run_probe(_IMPORT_PROBE))
    assert payload["banned"] == [], (
        f"stripped dependencies loaded on plain import: {payload['banned']}"
    )
    assert payload["version"], "kicad_sch_api imported but exposes no __version__"


def test_roundtrip_preserves_schematic_structure_on_the_solus_fixture(tmp_path: Path) -> None:
    """The green, load-bearing floor for T2b: load→save keeps every top-level
    element population (symbols, wires, labels, no_connects) intact."""
    out_path = tmp_path / "roundtrip.kicad_sch"
    payload = json.loads(_run_probe(_ROUNDTRIP_PROBE, str(SOLUS_SAMPLE_SCH), str(out_path)))
    for tag in ("symbol", "wire", "label", "no_connect"):
        assert payload["src"].get(tag) == payload["out"].get(tag), (
            f"round-trip changed the {tag} population: "
            f"{payload['src'].get(tag)} -> {payload['out'].get(tag)}"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Measured 2026-08-03 (T2a): upstream's format preservation does NOT hold on "
        "the Solus fixture — save_as() re-emits multi-line canonical KiCad style "
        "(43,513 B / 655 lines -> 65,603 B / 4,003 lines), reorders top-level "
        "elements, adds format-version fields (fields_autoplaced, show_name, "
        "do_not_autoplace, embedded_fonts, `power global`), and REPLACES embedded "
        "lib_symbols with definitions resolved from the machine's local KiCad "
        "symbol libraries when installed. Wires/labels/no_connects/instance UUIDs "
        "are preserved and a second save is byte-idempotent. T2b's write guard "
        "must NOT assume byte-stable saves."
    ),
)
def test_roundtrip_is_byte_identical_on_the_solus_fixture(tmp_path: Path) -> None:
    out_path = tmp_path / "roundtrip.kicad_sch"
    _run_probe(_ROUNDTRIP_PROBE, str(SOLUS_SAMPLE_SCH), str(out_path))
    assert out_path.read_bytes() == SOLUS_SAMPLE_SCH.read_bytes()
