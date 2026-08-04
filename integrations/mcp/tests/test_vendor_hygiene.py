"""Always-on mechanical checks for the `integrations/mcp/` fork layout.

Converts the "recommended CI" checks from `integrations/mcp/README.md` into
pytest tests that run under the root `uv run pytest` invocation:

1. Catalog stdio specs point at Solus-authored vendored launchers, never at
   `npx`/`uvx`/PATH-resolved binaries (README "Provisional servers" rule).
2. Every real fork directory agrees with its `allowlist.yaml` and the catalog:
   dir name == allowlist `server` == spec name, the name-shape regex holds,
   and every composed `{server}.{tool}` name fits the 128-char bound.
3. `load_allowlist` parses the real tree without a single skipped entry.
4. The vendored third-party trees (`integrations/mcp/*/upstream`,
   `integrations/mcp/*/vendor`) are excluded from the repo's ruff/mypy/pytest
   law (they are reviewed upstream code, not Solus style-clean code) while
   Solus-authored areas (`tests/`, `<fork>/solus/`, `<fork>/tests/`) stay in.
"""

import inspect
import logging
import pathlib
import re
import tomllib
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml
from solus_api.agent.tools import mcp_servers
from solus_api.agent.tools.mcp_servers import MCP_SERVER_CATALOG
from solus_api.agent.tools.untrusted import SAFE_REMOTE_NAME
from solus_api.bridge.allowlist import COMPOSED_NAME_MAX, SERVER_NAME, load_allowlist

REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_ROOT = REPO_ROOT / "integrations" / "mcp"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# PATH-resolved launcher names the README bans outright for stdio specs.
FORBIDDEN_LAUNCHERS = frozenset({"npx", "uvx", "uv", "pip", "pipx", "python", "python3", "node"})

# `web_search` is the one knowingly-provisional PATH-resolved spec: it is
# `npx`-launched, unreachable in production (the keyless credential gate
# precedes any spawn), and carries a TODO(MCP-03) in mcp_servers.py for
# vendoring. An explicit exemption + a source-marker guard is used instead of
# xfail: xfail would keep passing silently if the TODO were deleted, whereas
# this fails loudly the moment the exemption's written justification (the TODO)
# disappears or the spec gets vendored without the exemption being removed.
PROVISIONAL_PATH_RESOLVED = frozenset({"web_search"})
PROVISIONAL_TODO_MARKER = "TODO(MCP-03)"

# The two vendored-tree shapes later tasks add (README fork skeleton).
VENDORED_RUFF_GLOBS = ("integrations/mcp/*/upstream", "integrations/mcp/*/vendor")
VENDORED_SAMPLE_PATHS = (
    "integrations/mcp/kicad/upstream/kicad_mcp/server.py",
    "integrations/mcp/kicad/vendor/kicad_sch_api/core.py",
)
SOLUS_SAMPLE_PATHS = (
    "integrations/mcp/tests/test_vendor_hygiene.py",
    "integrations/mcp/kicad/solus/env_allowlist.py",
    "integrations/mcp/kicad/tests/test_launch.py",
)
VENDORED_MYPY_MODULES = frozenset({"kicad_mcp.*", "kicad_sch_api.*", "sexpdata"})

# Real fork directories: one dir per fork, marked by its allowlist.yaml
# (templates, README, and this tests/ dir have none).
FORK_DIRS = sorted(
    path for path in MCP_ROOT.iterdir() if path.is_dir() and (path / "allowlist.yaml").is_file()
)


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text())


def _ruff_excluded(patterns: list[str], rel_path: str) -> bool:
    """Approximate ruff's exclude matching: a pattern with a slash matches the
    root-relative path (a matched directory excludes everything under it); a
    bare pattern matches any single path component."""
    parts = PurePosixPath(rel_path).parts
    prefixes = [str(PurePosixPath(*parts[: i + 1])) for i in range(len(parts))]
    for pattern in patterns:
        if "/" in pattern:
            if any(fnmatch(prefix, pattern) for prefix in prefixes):
                return True
        elif any(fnmatch(part, pattern) for part in parts):
            return True
    return False


def _mypy_excluded(exclude_regexes: list[str], rel_path: str) -> bool:
    return any(re.search(pattern, rel_path) for pattern in exclude_regexes)


# --- README rule: stdio specs launch only via vendored `bin/launch` ----------


@pytest.mark.parametrize("server", ["kicad", "fusion"])
def test_free_tier_stdio_spec_points_at_its_vendored_launcher(server: str) -> None:
    # Phase 4 H4: commands are pinned ABSOLUTE (anchored at the repo root by
    # mcp_servers._fork_launcher) so a spawn never depends on process cwd.
    spec = MCP_SERVER_CATALOG[server]
    assert spec.command == str(REPO_ROOT / f"integrations/mcp/{server}/bin/launch")


def test_catalog_stdio_commands_are_vendored_launchers() -> None:
    for name, spec in MCP_SERVER_CATALOG.items():
        if spec.command is None:
            continue  # url transport: nothing runs on the customer machine
        if name in PROVISIONAL_PATH_RESOLVED:
            assert "integrations/mcp/" not in spec.command, (
                f"{name} is vendored now - remove it from PROVISIONAL_PATH_RESOLVED"
            )
            assert PROVISIONAL_TODO_MARKER in inspect.getsource(mcp_servers), (
                f"{name} is exempt only while its {PROVISIONAL_TODO_MARKER} marker "
                "survives in mcp_servers.py; the marker is gone, so either vendor "
                "the server or restore the written justification"
            )
            continue
        assert spec.command not in FORBIDDEN_LAUNCHERS, (
            f"{name} launches via PATH-resolved {spec.command!r} (README bans npx/uvx/pip)"
        )
        assert "/" in spec.command, f"{name} names a bare PATH binary {spec.command!r}"
        command = pathlib.Path(spec.command)
        assert command.is_absolute(), (
            f"{name} must pin an absolute launcher (Phase 4 H4), got {spec.command!r}"
        )
        assert command == REPO_ROOT / f"integrations/mcp/{name}/bin/launch", (
            f"{name} must launch ONLY via its Solus-authored bin/launch, got {spec.command!r}"
        )


# --- README rule: dir name == allowlist server == spec name; name shapes -----


@pytest.mark.parametrize("fork", FORK_DIRS, ids=lambda path: path.name)
def test_fork_directory_agrees_with_allowlist_and_catalog(fork: Path) -> None:
    assert SERVER_NAME.fullmatch(fork.name), (
        f"fork dir {fork.name!r} violates the naming rule ^[a-z][a-z0-9_]{{0,31}}$"
    )
    data = yaml.safe_load((fork / "allowlist.yaml").read_text())
    assert isinstance(data, dict), f"{fork.name}/allowlist.yaml is not a mapping"
    assert data.get("server") == fork.name, (
        f"{fork.name}/allowlist.yaml declares server {data.get('server')!r}"
    )
    for tool in data.get("tools") or ():
        tool_name = tool["name"]
        assert SAFE_REMOTE_NAME.fullmatch(tool_name), (
            f"{fork.name} tool {tool_name!r} fails _SAFE_REMOTE_NAME"
        )
        composed_len = len(fork.name) + 1 + len(tool_name)
        assert composed_len <= COMPOSED_NAME_MAX, (
            f"{fork.name}.{tool_name} composed name is {composed_len} chars "
            f"(bound {COMPOSED_NAME_MAX})"
        )
    for spec_name, spec in MCP_SERVER_CATALOG.items():
        if spec.command and spec.command.startswith(f"integrations/mcp/{fork.name}/"):
            assert spec_name == fork.name, (
                f"catalog spec {spec_name!r} launches from integrations/mcp/{fork.name}/"
            )


def test_load_allowlist_parses_real_tree_without_skips(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="solus.bridge.allowlist"):
        loaded = load_allowlist(MCP_ROOT)
    assert [record.getMessage() for record in caplog.records] == []
    assert sorted(loaded.servers) == [fork.name for fork in FORK_DIRS]


# --- vendored trees excluded from the lint/type/test law ---------------------


def test_ruff_excludes_vendored_trees_only() -> None:
    excludes = _load_pyproject()["tool"]["ruff"]["extend-exclude"]
    for glob in VENDORED_RUFF_GLOBS:
        assert glob in excludes, f"root ruff extend-exclude is missing {glob!r}"
    for sample in VENDORED_SAMPLE_PATHS:
        assert _ruff_excluded(excludes, sample), f"ruff would still lint vendored {sample}"
    for sample in SOLUS_SAMPLE_PATHS:
        assert not _ruff_excluded(excludes, sample), (
            f"ruff exclude swallows Solus-authored {sample}"
        )


def test_mypy_excludes_vendored_trees_only() -> None:
    mypy_cfg = _load_pyproject()["tool"]["mypy"]
    excludes = mypy_cfg.get("exclude", [])
    assert isinstance(excludes, list), "keep mypy exclude a list so entries stay reviewable"
    for sample in VENDORED_SAMPLE_PATHS:
        assert _mypy_excluded(excludes, sample), f"mypy would still check vendored {sample}"
    for sample in SOLUS_SAMPLE_PATHS:
        assert not _mypy_excluded(excludes, sample), f"mypy exclude swallows {sample}"


def test_mypy_ignores_vendored_modules_by_name_not_blanket() -> None:
    overrides = _load_pyproject()["tool"]["mypy"].get("overrides", [])
    covered: set[str] = set()
    for override in overrides:
        modules = override.get("module", [])
        modules = [modules] if isinstance(modules, str) else modules
        assert "*" not in modules, "a blanket module='*' override guts strict mode"
        if override.get("ignore_missing_imports"):
            covered.update(module for module in modules if module in VENDORED_MYPY_MODULES)
    missing = VENDORED_MYPY_MODULES - covered
    assert not missing, f"mypy overrides missing ignore_missing_imports for {sorted(missing)}"


def test_pytest_does_not_collect_vendored_trees() -> None:
    ini = _load_pyproject()["tool"]["pytest"]["ini_options"]
    norecurse = ini.get("norecursedirs", [])
    for vendored_dir in ("upstream", "vendor"):
        assert any(fnmatch(vendored_dir, pattern) for pattern in norecurse), (
            f"pytest would recurse into vendored {vendored_dir}/ trees"
        )
    # Setting norecursedirs REPLACES pytest's defaults - the defaults we rely
    # on must be restated, not lost.
    for default_dir in ("node_modules", ".venv", "build", "dist"):
        assert any(fnmatch(default_dir, pattern) for pattern in norecurse), (
            f"norecursedirs override dropped the {default_dir!r} default"
        )


def test_solus_authored_areas_stay_collected() -> None:
    ini = _load_pyproject()["tool"]["pytest"]["ini_options"]
    assert "integrations" in ini["testpaths"], "root pytest no longer collects integrations/"
    for solus_dir in ("tests", "solus"):
        assert not any(fnmatch(solus_dir, pattern) for pattern in ini.get("norecursedirs", [])), (
            f"norecursedirs must not swallow Solus-authored {solus_dir}/ dirs"
        )
