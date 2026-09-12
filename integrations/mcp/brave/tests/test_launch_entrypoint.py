"""SOLUSDEV-252 P6 — the brave fork's Solus-authored launch entrypoint and paper trail.

Locks the ADR-031 / `integrations/mcp/README.md` launcher law for the vendored
`@brave/brave-search-mcp-server@2.1.3` fork, which the API launches CLOUD-SIDE:

- `bin/launch` exists, is executable, resolves INSIDE `integrations/mcp/`;
- fixed argv, `env -i` scrubbed environment, PATH pinned to a constant, zero
  network/installer tokens, no PATH-resolved `node`;
- behaviour (run against a fake `node`): refuses an unresolvable or relative
  interpreter, a Node < 22, an empty key, and forwards EXACTLY the declared env;
- `allowlist.yaml` loads through the bridge loader and matches the fork-side
  `BRAVE_MCP_ENABLED_TOOLS` trimming in the launcher;
- `PROVENANCE.md` carries the template sections, the pinned npm version + tarball
  sha512, a tree hash that matches a recompute of `upstream/`, and BLANK sign-offs;
- `package.json` mirrors upstream's runtime deps and `package-lock.json` pins every
  package with an integrity hash; upstream's only network egress is the Brave API.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from solus_api.bridge.allowlist import load_allowlist

REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_ROOT = REPO_ROOT / "integrations" / "mcp"
FORK = MCP_ROOT / "brave"
UPSTREAM = FORK / "upstream"
LAUNCH = FORK / "bin" / "launch"
PROVENANCE = FORK / "PROVENANCE.md"
SECURITY_REVIEW = FORK / "SECURITY_REVIEW.md"
TEMPLATE = MCP_ROOT / "PROVENANCE.template.md"

_LIB = str(MCP_ROOT / "tests" / "_lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
from vendored_tree_hash import git_tree_hash  # noqa: E402

PINNED_VERSION = "2.1.3"
PINNED_TARBALL_SHA512 = (
    "cdd6db2b10afd7a355d6d2948ccd3a8d85612ff13d24848249af9c45e10214393d864b2f5072c6fc"
    "dc2d6e06d796412fd137cda99800d6d23076b174383708ff"
)
DECLARED_ENV = {
    "HOME",
    "LANG",
    "TMPDIR",
    "PATH",
    "BRAVE_API_KEY",
    "BRAVE_MCP_TRANSPORT",
    "BRAVE_MCP_LOG_LEVEL",
    "BRAVE_MCP_ENABLED_TOOLS",
}
FORBIDDEN_TOKENS = (
    "npx",
    "uvx",
    "npm install",
    "npm ci",
    "pip install",
    "curl",
    "wget",
    "git clone",
    "nc -",
    "ftp",
    "rsync",
    "ssh ",
)
REFUSED = 78
KEY_PLACEHOLDER = "placeholder-key"  # test-only sentinel, never a real value


def _launch_text() -> str:
    return LAUNCH.read_text(encoding="utf-8")


def _launch_commands() -> str:
    return "\n".join(
        line for line in _launch_text().splitlines() if not line.lstrip().startswith("#")
    )


def _allowlisted_names() -> list[str]:
    data = yaml.safe_load((FORK / "allowlist.yaml").read_text(encoding="utf-8"))
    return [tool["name"] for tool in data["tools"]]


# --- bin/launch: static law -------------------------------------------------------


def test_launch_exists_executable_and_inside_mcp_root() -> None:
    assert LAUNCH.is_file() and os.access(LAUNCH, os.X_OK)
    assert not LAUNCH.is_symlink()
    assert LAUNCH.resolve().is_relative_to(MCP_ROOT.resolve())


def test_launch_has_fixed_argv_with_no_argument_passthrough() -> None:
    text = _launch_text()
    assert "$@" not in text and "$*" not in text
    assert '"$NODE" "$FORK_DIR/upstream/dist/index.js" --transport stdio' in text


def test_launch_scrubs_environment_to_the_declared_allowlist() -> None:
    commands = _launch_commands()
    marker = "/usr/bin/env -i"
    assert marker in commands
    env_block = commands.split(marker, 1)[1]
    passed = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", env_block, re.MULTILINE))
    assert passed == DECLARED_ENV


def test_launch_pins_path_and_never_inherits_it() -> None:
    text = _launch_text()
    assert 'PATH="/usr/bin:/bin"' in text
    assert 'PATH="$PATH' not in text and 'PATH="${PATH' not in text


def test_launch_contains_no_network_or_installer_commands() -> None:
    commands = _launch_commands()
    for token in FORBIDDEN_TOKENS:
        assert token not in commands, f"bin/launch contains forbidden token {token!r}"


def test_launch_never_resolves_node_from_path() -> None:
    commands = _launch_commands()
    for line in commands.splitlines():
        if re.search(r"(?<![\w/$\"])node\b", line):
            assert "refuse" in line, f"PATH-shaped node mention in bin/launch: {line.strip()!r}"
    for candidate in re.findall(r"(\S*/node)\b", commands):
        assert candidate.startswith("/"), f"non-absolute node candidate {candidate!r}"


def test_launch_trims_the_server_to_the_allowlist_roster() -> None:
    match = re.search(r'BRAVE_MCP_ENABLED_TOOLS="([^"]+)"', _launch_text())
    assert match is not None
    assert sorted(match.group(1).split()) == sorted(_allowlisted_names())


# --- bin/launch: behaviour against a fake node ----------------------------------


def _fake_node(tmp_path: Path, version: str = "v22.9.0") -> Path:
    node = tmp_path / "node"
    node.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = "--version" ] && {{ echo {version}; exit 0; }}\n'
        'echo "ARGV=$*"\nenv | sort | grep -v "^_="\n',
        encoding="utf-8",
    )
    node.chmod(0o755)
    return node


def _run(env: dict[str, str], *extra: str) -> subprocess.CompletedProcess[str]:
    base = {"HOME": os.environ.get("HOME", "/"), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [str(LAUNCH), *extra],
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_launch_refuses_an_unresolvable_interpreter(tmp_path: Path) -> None:
    result = _run({"SOLUS_NODE_BIN": str(tmp_path / "missing" / "node"), "BRAVE_API_KEY": "k"})
    assert result.returncode == REFUSED
    assert "SOLUS_NODE_BIN" in result.stderr


def test_launch_refuses_a_relative_interpreter(tmp_path: Path) -> None:
    result = _run({"SOLUS_NODE_BIN": "node", "BRAVE_API_KEY": "k"})
    assert result.returncode == REFUSED
    assert "absolute" in result.stderr


def test_launch_refuses_node_below_22(tmp_path: Path) -> None:
    node = _fake_node(tmp_path, version="v18.19.1")
    result = _run({"SOLUS_NODE_BIN": str(node), "BRAVE_API_KEY": "k"})
    assert result.returncode == REFUSED
    assert "Node >= 22" in result.stderr


def test_launch_refuses_an_empty_key_before_spawning(tmp_path: Path) -> None:
    node = _fake_node(tmp_path)
    result = _run({"SOLUS_NODE_BIN": str(node)})
    assert result.returncode == REFUSED
    assert "BRAVE_API_KEY" in result.stderr
    assert "ARGV=" not in result.stdout  # the fake node never ran


def test_launch_forwards_exactly_the_declared_env_and_fixed_argv(tmp_path: Path) -> None:
    created = not (FORK / "node_modules").is_dir()
    if created:
        # ponytail: the deps check is a plain directory test; the fake run needs it.
        (FORK / "node_modules").mkdir()
    try:
        node = _fake_node(tmp_path)
        result = _run(
            {
                "SOLUS_NODE_BIN": str(node),
                "BRAVE_API_KEY": KEY_PLACEHOLDER,
                "LEAKY_SECRET": "must-not-pass",
                "BRAVE_MCP_TRANSPORT": "http",  # hostile ambient value: Solus's wins
            },
            "--injected",
            "arg",
        )
    finally:
        if created:
            (FORK / "node_modules").rmdir()
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == f"ARGV={UPSTREAM / 'dist' / 'index.js'} --transport stdio"
    child_env = dict(line.split("=", 1) for line in lines[1:] if "=" in line)
    assert child_env["BRAVE_API_KEY"] == KEY_PLACEHOLDER
    assert child_env["BRAVE_MCP_TRANSPORT"] == "stdio"
    assert child_env["PATH"] == "/usr/bin:/bin"
    assert child_env["PWD"] == str(FORK)  # cwd = fork dir: dotenv.config() finds no .env
    assert "LEAKY_SECRET" not in child_env
    assert set(child_env) - {"PWD", "SHLVL", "OLDPWD"} <= DECLARED_ENV


# --- allowlist ---------------------------------------------------------------------


def test_allowlist_loads_through_the_bridge_loader_as_reads() -> None:
    loaded = load_allowlist(MCP_ROOT).servers["brave"]
    assert set(loaded) == {
        "brave_web_search",
        "brave_llm_context",
        "brave_news_search",
        "brave_summarizer",
    }
    for tool in loaded.values():
        assert tool.requires_confirmation is False
        assert tool.reason  # Solus's own words for every exposed read


# --- upstream tree, deps, egress ---------------------------------------------------


def test_upstream_is_the_pinned_npm_release_and_mit() -> None:
    package = json.loads((UPSTREAM / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "@brave/brave-search-mcp-server"
    assert package["version"] == PINNED_VERSION
    assert package["license"] == "MIT"
    assert "MIT License" in (UPSTREAM / "LICENSE").read_text(encoding="utf-8")
    assert (UPSTREAM / "dist" / "index.js").is_file()
    assert not (UPSTREAM / "node_modules").exists()


def test_solus_package_json_mirrors_upstream_runtime_deps_only() -> None:
    upstream = json.loads((UPSTREAM / "package.json").read_text(encoding="utf-8"))
    solus = json.loads((FORK / "package.json").read_text(encoding="utf-8"))
    assert solus["private"] is True
    assert solus["dependencies"] == upstream["dependencies"]
    assert "devDependencies" not in solus


def test_lockfile_pins_every_package_with_an_integrity_hash() -> None:
    lock = json.loads((FORK / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 3
    packages = {path: meta for path, meta in lock["packages"].items() if path}
    assert packages
    for path, meta in packages.items():
        assert meta.get("integrity", "").startswith("sha512-"), f"{path} lacks integrity"
        assert meta.get("resolved", "").startswith("https://registry.npmjs.org/"), path
        assert not meta.get("dev"), f"dev dependency {path} in a runtime-only lock"


def test_upstream_network_egress_is_the_brave_api_only() -> None:
    fetch_sites = [
        path
        for path in UPSTREAM.rglob("*.js")
        if not path.name.endswith(".test.js") and "fetch(" in path.read_text(encoding="utf-8")
    ]
    assert fetch_sites == [UPSTREAM / "dist" / "BraveAPI" / "index.js"]
    api = (UPSTREAM / "dist" / "BraveAPI" / "index.js").read_text(encoding="utf-8")
    assert "https://api.search.brave.com" in api
    for path in UPSTREAM.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert "child_process" not in text and "eval(" not in text, path


# --- PROVENANCE / SECURITY_REVIEW / README ------------------------------------------


def test_provenance_contains_every_template_section() -> None:
    headings = [
        line for line in TEMPLATE.read_text(encoding="utf-8").splitlines() if line.startswith("## ")
    ]
    text = PROVENANCE.read_text(encoding="utf-8")
    for heading in headings:
        assert heading in text, f"PROVENANCE.md is missing template section {heading!r}"


def test_provenance_pins_version_tarball_and_matching_tree_hash() -> None:
    text = PROVENANCE.read_text(encoding="utf-8")
    assert PINNED_VERSION in text and PINNED_TARBALL_SHA512 in text
    match = re.search(r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", text)
    assert match, "PROVENANCE.md must record the vendored tree hash as a 40-hex `code` span"
    assert match.group(1) == git_tree_hash(UPSTREAM), "PROVENANCE tree hash is stale"
    assert SECURITY_REVIEW.is_file() and match.group(1) in SECURITY_REVIEW.read_text("utf-8")


def test_provenance_sign_offs_are_present_but_blank() -> None:
    text = PROVENANCE.read_text(encoding="utf-8")
    for reviewer in ("Reviewer 1", "Reviewer 2"):
        line = next((c for c in text.splitlines() if f"**{reviewer}:**" in c), None)
        assert line is not None and "`<name>`" in line, f"{reviewer} sign-off must stay BLANK"


def test_fork_readme_documents_the_pin_and_revendor_procedure() -> None:
    text = (FORK / "README.md").read_text(encoding="utf-8")
    assert PINNED_VERSION in text and "re-vendor" in text.lower() and "14" in text
