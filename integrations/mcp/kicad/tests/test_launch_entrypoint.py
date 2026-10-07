"""SOLUSDEV-100 T1a — the kicad fork's Solus-authored launch entrypoint.

Locks the ADR-031 / `integrations/mcp/README.md` launcher law for the
vendored `lamaalrajih/kicad-mcp` fork:

- `bin/launch` exists, is executable, and resolves INSIDE `integrations/mcp/`
  (no symlink escape) so the companion's `_launch_command` guard accepts it;
- the script has a FIXED argv (no `$@`/`$*` passthrough), a scrubbed
  environment (explicit `env -i` allowlist, PATH pinned to a constant), and
  zero network/installer commands or PATH-resolved interpreters;
- `solus_companion.config.discover_servers` discovers the fork;
- `PROVENANCE.md` carries every template section, the pinned upstream SHA,
  a tree hash that matches a recompute of `upstream/`, a modification row
  for every deviation from verbatim, and BLANK (human-only) sign-offs;
- `requirements.lock.txt` is fully hash-pinned (`name==version --hash=...`).
"""

import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from solus_companion.config import discover_servers

from tree_hash import git_tree_hash  # isort: skip

REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_ROOT = REPO_ROOT / "integrations" / "mcp"
FORK = MCP_ROOT / "kicad"
UPSTREAM = FORK / "upstream"
LAUNCH = FORK / "bin" / "launch"
PROVENANCE = FORK / "PROVENANCE.md"
LOCKFILE = FORK / "requirements.lock.txt"
FORK_README = FORK / "README.md"
TEMPLATE = MCP_ROOT / "PROVENANCE.template.md"

PINNED_SHA = "98c9ea41cb393393a8bafd157a93e84431e00afb"

# The launcher's declared child-environment allowlist now LIVES in solus/
# (T1b relocation, anticipated by T1a): solus/env_allowlist.py is the single
# written declaration, and this test pins the shell script to it. Changing
# the set is a re-review trigger (PROVENANCE "Re-review triggers").
if str(FORK) not in sys.path:
    sys.path.insert(0, str(FORK))
from solus.env_allowlist import (  # noqa: E402
    CHILD_ENV_ALLOWLIST as DECLARED_ENV_ALLOWLIST,
)

# Network / installer / PATH-resolved-launcher tokens banned from the script
# text outright (README rule 4: zero network I/O, no installs at launch).
FORBIDDEN_TOKENS = (
    "npx",
    "uvx",
    "pip install",
    "uv ",
    "curl",
    "wget",
    "git clone",
    "nc -",
    "ftp",
    "rsync",
    "ssh ",
)

# Paths excluded from the verbatim vendor copy (human-approved F6 pattern).
# Each excluded path that existed upstream needs a PROVENANCE modification row.
VENDOR_EXCLUSIONS = ("CLAUDE.md", ".claude", "agents", ".mcp.json", ".github")


def _launch_text() -> str:
    return LAUNCH.read_text(encoding="utf-8")


def _launch_commands() -> str:
    """Script text with comment lines stripped (shebang included)."""
    lines = [line for line in _launch_text().splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines)


# --- bin/launch: existence, executability, containment ----------------------


def test_launch_exists_and_is_executable() -> None:
    assert LAUNCH.is_file(), "integrations/mcp/kicad/bin/launch is missing"
    assert os.access(LAUNCH, os.X_OK), "bin/launch is not executable"


def test_launch_is_a_regular_file_resolving_inside_mcp_root() -> None:
    assert not LAUNCH.is_symlink(), "bin/launch must be a regular file, not a symlink"
    resolved = LAUNCH.resolve()
    assert resolved.is_relative_to(MCP_ROOT.resolve()), (
        "bin/launch resolves outside integrations/mcp/ — the companion guard would refuse it"
    )


# --- bin/launch: fixed argv, scrubbed env, no network ------------------------


def test_launch_has_fixed_argv_with_no_argument_passthrough() -> None:
    text = _launch_text()
    assert "$@" not in text, "bin/launch must not forward caller arguments"
    assert "$*" not in text, "bin/launch must not forward caller arguments"
    assert '"$PYTHON" "$FORK_DIR/solus/server.py"' in text, (
        "bin/launch must exec the fixed private interpreter against the "
        "Solus overlay entrypoint (T1b: solus/server.py replaces "
        "upstream/main.py) with a fixed argv"
    )


def test_launch_scrubs_environment_to_the_declared_allowlist() -> None:
    commands = _launch_commands()
    marker = "/usr/bin/env -i"
    assert marker in commands, "bin/launch must clear the environment with env -i"
    env_block = commands.split(marker, 1)[1]
    passed = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", env_block, re.MULTILINE))
    assert passed == DECLARED_ENV_ALLOWLIST, (
        f"env allowlist drift: script passes {sorted(passed)}, "
        f"declared {sorted(DECLARED_ENV_ALLOWLIST)}"
    )


def test_launch_pins_path_to_a_constant_instead_of_inheriting_it() -> None:
    text = _launch_text()
    assert 'PATH="/usr/bin:/bin"' in text, (
        "PATH must be a fixed constant for the child, never inherited"
    )
    assert 'PATH="$PATH' not in text and 'PATH="${PATH' not in text


def test_launch_contains_no_network_or_installer_commands() -> None:
    text = _launch_text()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"bin/launch contains forbidden token {token!r}"


def test_launch_uses_only_the_fixed_private_interpreter() -> None:
    commands = _launch_commands()
    assert '.venv/bin/python3"' in commands, (
        "the interpreter must be the fork's private .venv/bin/python3"
    )
    # Every python mention in command text is the fixed private path — no
    # bare/PATH-resolved `python`, `python3`, or `node` invocations.
    for match in re.finditer(r"\S*python3?\b", commands):
        assert match.group().endswith(".venv/bin/python3"), (
            f"PATH-resolved interpreter in bin/launch: {match.group()!r}"
        )
    assert not re.search(r"(?:^|\s)node\b", commands), "no node in a python fork's launcher"


def test_launch_cds_to_the_companion_passed_workspace_env_var() -> None:
    text = _launch_text()
    assert "SOLUS_MCP_WORKSPACE" in text, (
        "the workspace must arrive via the documented SOLUS_MCP_WORKSPACE env var"
    )
    assert re.search(r'^\s*cd\s+--\s*"\$WORKSPACE"', text, re.MULTILINE), (
        "bin/launch must cd to the validated workspace before exec"
    )


# --- companion discovery ------------------------------------------------------


def test_discover_servers_finds_the_kicad_launch(tmp_path: Path) -> None:
    """The real `bin/launch`, placed in a minimal integrations root, passes the
    companion's paranoid discovery guard (exists + executable + inside-root).
    A synthetic root is used because `allowlist.yaml` is T1b's deliverable."""
    fork = tmp_path / "kicad"
    (fork / "bin").mkdir(parents=True)
    (fork / "allowlist.yaml").write_text("server: kicad\n", encoding="utf-8")
    copied = fork / "bin" / "launch"
    shutil.copy2(LAUNCH, copied)

    servers = discover_servers(tmp_path)

    assert [server.name for server in servers] == ["kicad"]
    assert servers[0].command == copied.resolve()
    assert servers[0].args == ()


def test_discover_servers_finds_kicad_in_the_real_tree() -> None:
    if not (FORK / "allowlist.yaml").is_file():
        pytest.skip("allowlist.yaml is T1b's deliverable; real-tree discovery arms then")
    servers = discover_servers(MCP_ROOT)
    by_name = {server.name: server for server in servers}
    assert "kicad" in by_name
    assert by_name["kicad"].command == LAUNCH.resolve()


# --- PROVENANCE.md -------------------------------------------------------------


def _provenance_text() -> str:
    return PROVENANCE.read_text(encoding="utf-8")


def _recomputed_upstream_tree_hash() -> str:
    """The git tree hash of the CURRENT `upstream/` worktree state — computed in
    pure Python (`tree_hash.git_tree_hash`) rather than by shelling out, because
    the CI python image ships no `git` binary and this guard must run THERE
    above all. `test_tree_hash.py` cross-checks the implementation against real
    git wherever git exists, including on this very tree."""
    return git_tree_hash(UPSTREAM)


def test_provenance_contains_every_template_section() -> None:
    headings = [
        line for line in TEMPLATE.read_text(encoding="utf-8").splitlines() if line.startswith("## ")
    ]
    assert headings, "PROVENANCE.template.md lost its section headings?"
    text = _provenance_text()
    for heading in headings:
        assert heading in text, f"PROVENANCE.md is missing template section {heading!r}"


def test_provenance_pins_the_upstream_sha() -> None:
    assert PINNED_SHA in _provenance_text()


def test_provenance_tree_hash_matches_a_recompute_of_upstream() -> None:
    match = re.search(r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", _provenance_text())
    assert match, "PROVENANCE.md must record the vendored tree hash as a 40-hex `code` span"
    assert match.group(1) == _recomputed_upstream_tree_hash(), (
        "PROVENANCE tree hash is stale — upstream/ changed without updating it "
        "(this mechanically voids the sign-offs)"
    )


def test_provenance_logs_every_vendor_exclusion_and_none_ship() -> None:
    text = _provenance_text()
    section = text.split("## Local modifications", 1)[1].split("## ", 1)[0]
    for excluded in VENDOR_EXCLUSIONS:
        assert not (UPSTREAM / excluded).exists(), (
            f"excluded path upstream/{excluded} was vendored anyway"
        )
    # `.github/` is the one exclusion pattern that exists at the pinned SHA —
    # its omission from the verbatim copy needs a modification-log row.
    assert ".github" in section, "PROVENANCE modification log is missing the .github/ exclusion row"


def test_provenance_sign_offs_are_blank_or_pin_the_current_tree_hashes() -> None:
    """Sign-offs are a human-only act. A line is either the blank template placeholder, or a
    complete signature that pins BOTH current vendored tree hashes — a stale hash voids it."""
    text = _provenance_text()
    upstream = re.search(r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", text)
    vendor = re.search(r"Vendor tree hash:\*\*\s*`([0-9a-f]{40})`", text)
    assert upstream is not None and vendor is not None
    for reviewer in ("Reviewer 1", "Reviewer 2"):
        line = next(
            (candidate for candidate in text.splitlines() if f"**{reviewer}:**" in candidate),
            None,
        )
        assert line is not None, f"PROVENANCE.md is missing the {reviewer} sign-off line"
        if "`<name>`" in line:
            continue  # still the blank template placeholder
        assert upstream.group(1) in line and vendor.group(1) in line, (
            f"{reviewer} signed against stale or missing tree hashes — re-review required"
        )


# --- requirements.lock.txt -----------------------------------------------------


def _logical_lock_lines() -> list[str]:
    """Lockfile lines with backslash continuations joined."""
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


def test_lockfile_exists_and_every_requirement_is_hash_pinned() -> None:
    assert LOCKFILE.is_file(), "requirements.lock.txt is missing"
    requirement_re = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;\\]+"  # name==exact-version
        r"(?:\s*;[^-][^\\]*?)?"  # optional environment marker
        r"(?:\s+--hash=sha256:[0-9a-f]{64})+$"  # one or more pinned hashes
    )
    lines = [line for line in _logical_lock_lines() if not line.startswith("#")]
    assert lines, "requirements.lock.txt has no requirement lines"
    for line in lines:
        assert not line.startswith("-"), f"option/editable line in lockfile: {line!r}"
        assert requirement_re.match(line), f"not fully hash-pinned: {line!r}"


def test_lockfile_pins_the_upstream_runtime_dependencies() -> None:
    names = {
        line.split("==", 1)[0].lower().replace("_", "-")
        for line in _logical_lock_lines()
        if not line.startswith("#")
    }
    for dependency in ("mcp", "fastmcp", "pandas", "pyyaml", "defusedxml"):
        assert dependency in names, f"lockfile is missing upstream dependency {dependency!r}"


# --- fork README ----------------------------------------------------------------


def test_fork_readme_documents_the_pin_and_revendor_procedure() -> None:
    assert FORK_README.is_file(), "integrations/mcp/kicad/README.md is missing"
    text = FORK_README.read_text(encoding="utf-8")
    assert PINNED_SHA in text, "fork README must state the pinned SHA"
    assert "re-vendor" in text.lower(), "fork README must describe the re-vendor procedure"
    assert "14" in text, "fork README must state the 14-day CVE re-vendor clock"
