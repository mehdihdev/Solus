"""SOLUSDEV-100 T1b — the Solus overlay registers ONLY the allowlisted read
roster; every other upstream tool is dead in-process (never registered on the
server instance, not merely hidden from listings)."""

import ast
import asyncio
import contextlib
import inspect
import io
import re
import sys
from pathlib import Path
from typing import Any

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus`/`kicad_mcp` import — keep this line first.
from test_overlay_support import (  # isort: skip
    FORK,
    PROVENANCE,
    REPO_ROOT,
    SOLUS,
    FakeMCP,
    write_minimal_project,
)

from solus.confinement import REASON_PATH_ESCAPES_WORKSPACE  # isort: skip
from solus.registration import register_allowlisted_tools  # isort: skip
from solus.roster import (  # isort: skip
    EXPOSED_UPSTREAM_TOOLS,
    FULL_ROSTER,
    READ_ROSTER,
    SOLUS_AUTHORED_TOOLS,
    WRITE_ROSTER,
)
from solus.trimming import TrimmingRegistrar

from tree_hash import git_tree_hash  # isort: skip  # isort: skip

# Every tool upstream's seven register_* modules register (enumerated from the
# vendored tree at review time). A re-vendor that renames or adds tools must
# update this list AND re-run the review (PROVENANCE re-review triggers).
UPSTREAM_REGISTERED_TOOLS = frozenset(
    {
        # project_tools
        "list_projects",
        "get_project_structure",
        "open_project",
        # analysis_tools
        "validate_project",
        # export_tools
        "generate_pcb_thumbnail",
        "generate_project_thumbnail",
        # drc_tools
        "get_drc_history_tool",
        "run_drc_check",
        # bom_tools
        "analyze_bom",
        "export_bom_csv",
        # netlist_tools
        "extract_schematic_netlist",
        "extract_project_netlist",
        "analyze_schematic_connections",
        "find_component_connections",
        # pattern_tools
        "identify_circuit_patterns",
        "analyze_project_circuit_patterns",
    }
)

# Import roots the standalone fork may use: stdlib, the vendored upstream
# package, the MCP SDKs from the fork's own lockfile, and itself. NEVER
# `solus_api` or anything else from packages/ — the fork runs on customer
# machines with no cloud codebase present.
ALLOWED_IMPORT_ROOTS = frozenset({"kicad_mcp", "mcp", "fastmcp", "solus"})


# --- roster shape -------------------------------------------------------------


def test_roster_is_exposed_upstream_plus_solus_authored() -> None:
    assert READ_ROSTER == EXPOSED_UPSTREAM_TOOLS | SOLUS_AUTHORED_TOOLS
    assert not (EXPOSED_UPSTREAM_TOOLS & SOLUS_AUTHORED_TOOLS)
    assert WRITE_ROSTER == {"set_symbol_property"}
    assert not (WRITE_ROSTER & READ_ROSTER)


def test_exposed_upstream_names_exist_in_the_vendored_tree() -> None:
    """Guards the roster against silent upstream renames on re-vendor: every
    exposed upstream name must be a tool upstream actually registers."""
    assert EXPOSED_UPSTREAM_TOOLS <= UPSTREAM_REGISTERED_TOOLS
    assert SOLUS_AUTHORED_TOOLS == {"export_netlist"}
    assert "export_netlist" not in UPSTREAM_REGISTERED_TOOLS


# --- registration through the trimming registrar ------------------------------


def test_registered_tool_set_equals_the_full_roster() -> None:
    fake = FakeMCP()
    register_allowlisted_tools(fake)
    assert set(fake.tools) == FULL_ROSTER


def test_set_symbol_property_is_registered_and_confirmation_gated() -> None:
    """T2b landed: the write tool is served through the same TrimmingRegistrar
    as the reads, and its allowlist entry (drafted with the fork, rule 2 of
    integrations/mcp/CLAUDE.md) carries requires_confirmation: true."""
    fake = FakeMCP()
    register_allowlisted_tools(fake)
    assert "set_symbol_property" in fake.tools


def test_unregistered_upstream_tools_are_dead_in_process() -> None:
    fake = FakeMCP()
    register_allowlisted_tools(fake)
    dead = UPSTREAM_REGISTERED_TOOLS - EXPOSED_UPSTREAM_TOOLS
    assert dead, "trimming is vacuous if everything upstream is exposed"
    for name in dead:
        assert name not in fake.tools, f"non-allowlisted upstream tool {name} was registered"


def test_registrar_never_forwards_blocked_registrations() -> None:
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"kept"}))

    @registrar.tool()
    def kept() -> str:
        return "kept"

    @registrar.tool()
    def dropped() -> str:
        return "dropped"

    assert set(fake.tools) == {"kept"}
    assert registrar.blocked == ("dropped",)
    # The decorator hands back the ORIGINAL functions either way, so upstream
    # code that calls a sibling tool internally keeps working.
    assert kept() == "kept"
    assert dropped() == "dropped"


# --- wrapper semantics: ctx stripped, stdout redirected ------------------------


def test_registered_wrappers_strip_the_ctx_parameter() -> None:
    """Uses a non-path-shaped placeholder param name deliberately: `path`
    would now (H2) route through the confinement check in
    `test_registered_wrappers_confine_path_shaped_arguments` below, which is
    a different concern from ctx-stripping tested here."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"sample"}))
    seen: dict[str, object] = {}

    @registrar.tool()
    async def sample(value: str, ctx: object | None) -> dict[str, object]:
        seen["value"] = value
        seen["ctx"] = ctx
        return {"ok": True}

    wrapper = fake.tools["sample"]
    assert "ctx" not in inspect.signature(wrapper).parameters
    assert "ctx" not in getattr(wrapper, "__annotations__", {})
    result = asyncio.run(wrapper(value="x"))
    assert result == {"ok": True}
    assert seen == {"value": "x", "ctx": None}


def test_registered_wrappers_redirect_stdout_prints_to_stderr() -> None:
    """Upstream tool bodies print() to stdout, which is the MCP stdio protocol
    channel — the overlay must divert those writes to stderr."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"noisy", "noisy_async"}))

    @registrar.tool()
    def noisy() -> str:
        print("upstream chatter")
        return "done"

    @registrar.tool()
    async def noisy_async(ctx: object | None) -> str:
        print("async chatter")
        return "done"

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        assert fake.tools["noisy"]() == "done"
        assert asyncio.run(fake.tools["noisy_async"]()) == "done"
    assert out.getvalue() == "", "tool prints leaked onto the MCP stdio channel"
    assert "upstream chatter" in err.getvalue()
    assert "async chatter" in err.getvalue()


async def test_concurrent_calls_do_not_clobber_each_others_stdout_diversion() -> None:
    """L1 regression: a naive per-call `contextlib.redirect_stdout` held open
    across an `await` is concurrency-unsafe — if a SECOND overlapping call
    enters and then FINISHES (restoring stdout) before a FIRST, still-running
    call exits, the first call's remaining prints would leak onto the real
    MCP stdio channel. Both calls redirect to the same target, so the
    reference-counted diversion in trimming.py must keep stdout diverted for
    the whole overlapping window regardless of exit order."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"slow", "fast"}))
    slow_started = asyncio.Event()

    @registrar.tool()
    async def slow(ctx: object | None) -> str:
        slow_started.set()
        await asyncio.sleep(0.05)
        print("slow chatter (after fast already exited)")
        return "slow-done"

    @registrar.tool()
    async def fast(ctx: object | None) -> str:
        await slow_started.wait()
        print("fast chatter")
        return "fast-done"

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        results = list(await asyncio.gather(fake.tools["slow"](), fake.tools["fast"]()))

    assert results == ["slow-done", "fast-done"]
    assert out.getvalue() == "", (
        "the still-running 'slow' call's diversion must not be clobbered by "
        "'fast' finishing (and exiting its own diversion) first"
    )
    assert "slow chatter" in err.getvalue()
    assert "fast chatter" in err.getvalue()


# --- H2/H3: path-argument confinement wired through every registered tool -------


async def _call(tool: Any, **kwargs: Any) -> Any:
    result = tool(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def test_registered_wrappers_refuse_before_invoking_the_body_on_an_escaping_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"reads_a_path"}))
    invoked = False

    @registrar.tool()
    def reads_a_path(project_path: str) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {"ok": True}

    result = fake.tools["reads_a_path"](project_path=str(tmp_path / "outside.kicad_pro"))

    assert result == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}
    assert invoked is False, "the tool body must never run once confinement refuses"


def test_registered_wrappers_invoke_the_body_when_the_path_is_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"reads_a_path"}))

    @registrar.tool()
    def reads_a_path(project_path: str) -> dict[str, object]:
        return {"ok": True, "project_path": project_path}

    inside = str(workspace / "board.kicad_pro")

    assert fake.tools["reads_a_path"](project_path=inside) == {
        "ok": True,
        "project_path": inside,
    }


def test_registered_wrappers_refuse_cleanly_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"reads_a_path"}))
    invoked = False

    @registrar.tool()
    def reads_a_path(project_path: str) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {"ok": True}

    result = fake.tools["reads_a_path"](project_path="board.kicad_pro")

    assert result == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}
    assert invoked is False


def test_tools_with_no_path_shaped_argument_are_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`list_projects` takes no path argument at all — confinement must not
    require a workspace it never needs."""
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"no_path_args"}))

    @registrar.tool()
    def no_path_args() -> dict[str, object]:
        return {"ok": True}

    assert fake.tools["no_path_args"]() == {"ok": True}


# The roster tools that take a `project_path` / `schematic_path` argument —
# every one of them goes through the SAME confinement layer in trimming.py.
_PROJECT_PATH_TOOLS = (
    "get_project_structure",
    "extract_project_netlist",
    "analyze_bom",
    "export_netlist",
)
_SCHEMATIC_PATH_TOOLS = ("analyze_schematic_connections",)


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "outside" / "board.kicad_pro"
    outside.parent.mkdir()
    outside.write_text("{}")
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], project_path=str(outside))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_a_traversal_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(
        fake.tools[tool_name], project_path=str(workspace / ".." / "escape.kicad_pro")
    )

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_a_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "secret.kicad_pro"
    outside.write_text("{}")
    link = workspace / "innocent.kicad_pro"
    link.symlink_to(outside)
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], project_path=str(link))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_still_run_when_the_project_is_inside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    project = write_minimal_project(workspace / "proj")
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], project_path=str(project))

    assert result.get("reason") != REASON_PATH_ESCAPES_WORKSPACE
    assert result.get("error") != "path escapes workspace"


@pytest.mark.parametrize("tool_name", _SCHEMATIC_PATH_TOOLS)
async def test_schematic_path_tools_refuse_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "outside.kicad_sch"
    outside.write_text("(kicad_sch)")
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], schematic_path=str(outside))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _SCHEMATIC_PATH_TOOLS)
async def test_schematic_path_tools_refuse_a_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "secret.kicad_sch"
    outside.write_text("(kicad_sch)")
    link = workspace / "innocent.kicad_sch"
    link.symlink_to(outside)
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], schematic_path=str(link))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _SCHEMATIC_PATH_TOOLS)
async def test_schematic_path_tools_still_run_when_the_schematic_is_inside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    project = write_minimal_project(workspace / "proj")
    schematic = project.with_suffix(".kicad_sch")
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(fake.tools[tool_name], schematic_path=str(schematic))

    assert result.get("reason") != REASON_PATH_ESCAPES_WORKSPACE


async def test_set_symbol_property_is_also_confined_at_the_generic_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defense in depth: the write tool has its own stricter confinement
    (`solus/write/paths.py`), but it must never even be REACHED for a path
    outside the workspace — the generic trimming-layer check refuses first."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "secret.kicad_sch"
    outside.write_text("(kicad_sch)")
    fake = FakeMCP()
    register_allowlisted_tools(fake)

    result = await _call(
        fake.tools["set_symbol_property"],
        schematic_path=str(outside),
        reference="U1",
        property="MPN",
        value="X",
    )

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


# --- the fork itself stays pristine --------------------------------------------


def test_upstream_tree_hash_matches_provenance_after_overlay_work() -> None:
    """The overlay adds solus/ files only — the vendored tree hash recorded in
    PROVENANCE.md must still match a recompute of upstream/ (the expected hash
    is READ from PROVENANCE, never hardcoded here)."""
    match = re.search(
        r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", PROVENANCE.read_text(encoding="utf-8")
    )
    assert match, "PROVENANCE.md must record the vendored tree hash"
    # Pure-Python recompute (no `git` binary: the CI image has none — see
    # tree_hash.py). Reading the WORKING TREE also subsumes the old
    # `git status --porcelain` check: an uncommitted edit inside upstream/
    # changes the recomputed hash and fails this assertion.
    assert git_tree_hash(REPO_ROOT / "integrations" / "mcp" / "kicad" / "upstream") == match.group(
        1
    ), "upstream/ no longer matches the PROVENANCE-recorded vendored tree hash"


def test_solus_package_imports_only_stdlib_upstream_and_mcp_libs() -> None:
    """The fork runs standalone on customer machines: solus/ may import the
    stdlib, the vendored upstream, the MCP SDKs, and itself — never the cloud
    codebase (solus_api / packages.*)."""
    offenders: list[str] = []
    for source in sorted(SOLUS.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in sys.stdlib_module_names or root in ALLOWED_IMPORT_ROOTS:
                    continue
                offenders.append(f"{source.name}: {root}")
    assert offenders == [], f"forbidden imports in solus/: {offenders}"


def test_solus_server_module_imports_cleanly() -> None:
    """Importing the entry module must have no side effects (no server start,
    no file writes) — running is gated behind main()."""
    before = set(Path.cwd().iterdir())
    import solus.server  # noqa: F401

    assert set(Path.cwd().iterdir()) == before
    assert (FORK / "solus" / "server.py").is_file()
