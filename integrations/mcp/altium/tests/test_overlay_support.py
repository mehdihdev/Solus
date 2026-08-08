"""SOLUSDEV-102 ALT-5 — shared import scaffolding for the overlay-trimming test
modules, plus the hardened-wrapper semantics tests (ctx-strip, path confinement,
stdout diversion, and the proj_get_nets force_recompile pin).

The altium fork runs standalone on customer machines inside its private venv
(`bin/launch`); its runtime dependencies (`psutil`, `networkx`, ...) are
deliberately NOT part of the repo's uv workspace. These tests exercise the
Solus overlay's own logic through duck-typed recorders, installing minimal
import stubs for the fork's lockfile-only dependencies so the vendored
`eda_agent` modules can be imported without them. Siblings import this module
FIRST (package-relative, after `.altium_paths`) for the bootstrap.
"""

import ast
import asyncio
import contextlib
import inspect
import io
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest

# The bootstrap module must run before the overlay import — keep it first.
from .altium_paths import SOLUS_DIR, UPSTREAM_SRC, overlay_module  # isort: skip

# ---------------------------------------------------------------------------
# Import environment: upstream on sys.path + stubs for lockfile-only deps.
# Stubs are ONLY installed when the real package is absent (the repo env);
# in the fork venv the real packages win.
# ---------------------------------------------------------------------------


def _install_module(name: str, module: types.ModuleType) -> None:
    if name not in sys.modules:
        sys.modules[name] = module


def _psutil_stub() -> types.ModuleType:
    """`eda_agent.bridge.process_manager` does `import psutil` at module level
    and only touches attributes at call time (which these tests never reach —
    confinement refuses before any tool body runs)."""
    module = types.ModuleType("psutil")
    return module


def _networkx_stub() -> types.ModuleType:
    """`eda_agent.design.motifs` builds its motif pattern graphs AT IMPORT
    TIME (module-level `_make_pattern` calls) and subclasses `GraphMatcher`,
    so the stub needs a minimally functional graph type, not just names."""

    class _Graph:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._nodes: dict[Any, Any] = {}
            self._edges: list[Any] = []

        def add_node(self, node: Any, **attrs: Any) -> None:
            self._nodes[node] = attrs

        def add_edge(self, left: Any, right: Any, **attrs: Any) -> None:
            self._edges.append((left, right, attrs))

        def __iter__(self) -> Any:
            return iter(self._nodes)

        def __len__(self) -> int:
            return len(self._nodes)

    class _GraphMatcher:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    module = types.ModuleType("networkx")
    module.Graph = _Graph  # type: ignore[attr-defined]
    module.MultiGraph = type("MultiGraph", (_Graph,), {})  # type: ignore[attr-defined]
    module.DiGraph = type("DiGraph", (_Graph,), {})  # type: ignore[attr-defined]
    module.connected_components = lambda graph: iter(())  # type: ignore[attr-defined]
    algorithms = types.ModuleType("networkx.algorithms")
    isomorphism = types.ModuleType("networkx.algorithms.isomorphism")
    isomorphism.GraphMatcher = _GraphMatcher  # type: ignore[attr-defined]
    algorithms.isomorphism = isomorphism  # type: ignore[attr-defined]
    module.algorithms = algorithms  # type: ignore[attr-defined]
    _install_module("networkx.algorithms", algorithms)
    _install_module("networkx.algorithms.isomorphism", isomorphism)
    return module


def install_import_environment() -> None:
    """Make the vendored `eda_agent` importable in the repo test env."""
    entry = str(UPSTREAM_SRC)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    for name, factory in (("psutil", _psutil_stub), ("networkx", _networkx_stub)):
        try:
            __import__(name)
        except ImportError:
            _install_module(name, factory())


install_import_environment()

_confinement = overlay_module("confinement")
_roster = overlay_module("roster")
_trimming = overlay_module("trimming")

REASON_PATH_ESCAPES_WORKSPACE: str = _confinement.REASON_PATH_ESCAPES_WORKSPACE
PENDING_TOOLS: frozenset[str] = _roster.PENDING_TOOLS
registered_roster: Callable[[], frozenset[str]] = _roster.registered_roster
PINNED_PARAMETERS: dict[str, dict[str, Any]] = dict(_trimming.PINNED_PARAMETERS)
TrimmingRegistrar = _trimming.TrimmingRegistrar

F = TypeVar("F", bound=Callable[..., Any])


def registrar_tool(registrar: Any) -> Callable[[F], F]:
    """Typed view of `registrar.tool()`: the overlay is loaded dynamically
    (as `altium_solus`), so its decorator is `Any` to mypy — this helper
    keeps the decorated test tools typed under strict mode."""
    return cast("Callable[[F], F]", registrar.tool())


class FakeMCP:
    """Duck-typed FastMCP recorder. Upstream register functions touch
    `.tool()`; `.prompt()`/`.resource()` are recorded so the overlay tests can
    assert NOTHING beyond tools ever reaches the backing server."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}
        self.prompts: list[str] = []
        self.resources: list[str] = []

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        name_override = kwargs.get("name")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            name = name_override if isinstance(name_override, str) else fn.__name__
            if name in self.tools:
                raise AssertionError(f"duplicate tool registration: {name}")
            self.tools[name] = fn
            return fn

        return decorator

    def prompt(
        self, *args: Any, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.prompts.append(getattr(fn, "__name__", "<anonymous>"))
            return fn

        return decorator

    def resource(
        self, *args: Any, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.resources.append(getattr(fn, "__name__", "<anonymous>"))
            return fn

        return decorator


_FULL_SURFACE: FakeMCP | None = None


def upstream_full_surface() -> FakeMCP:
    """Every tool/prompt/resource upstream's own `register_backend(...,
    "altium", "full")` registers — the REAL ~396-tool surface the overlay
    trims, enumerated from the vendored tree rather than hardcoded. Cached:
    registration only defines closures, but 396 of them add up."""
    global _FULL_SURFACE
    if _FULL_SURFACE is None:
        import eda_agent.tools as upstream_tools

        recorder = FakeMCP()
        upstream_tools.register_backend(recorder, "altium", "full")
        _FULL_SURFACE = recorder
    return _FULL_SURFACE


def register_overlay(backing: Any) -> Any:
    """Run the REAL overlay registration (solus/registration.py) against
    *backing*, returning the TrimmingRegistrar for audit."""
    registration = overlay_module("registration")
    return registration.register_allowlisted_tools(backing)


async def call_tool(tool: Callable[..., Any], **kwargs: Any) -> Any:
    result = tool(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class RecordingBridge:
    """Stands in for upstream's AltiumBridge: records every IPC command the
    tool body would send instead of round-tripping Altium."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []

    async def send_command_async(
        self, command: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.commands.append((command, dict(params or {})))
        return {"pins": [], "count": 0}


# --- scaffolding sanity --------------------------------------------------------


def test_import_environment_provides_upstream_and_overlay_roots() -> None:
    import eda_agent.tools  # noqa: F401

    for name in ("psutil", "networkx"):
        assert name in sys.modules, f"{name} neither real nor stubbed"
    assert upstream_full_surface().tools, "upstream surface enumeration is empty"


# --- wrapper semantics: ctx stripped -------------------------------------------


def test_registered_wrappers_strip_the_ctx_parameter() -> None:
    """Uses a non-path-shaped placeholder param name deliberately: `path`
    would route through the confinement check tested separately below."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"sample"}))
    seen: dict[str, object] = {}

    @registrar_tool(registrar)
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


def test_real_roster_wrappers_advertise_no_ctx_parameter() -> None:
    fake = FakeMCP()
    register_overlay(fake)
    for name, wrapper in fake.tools.items():
        assert "ctx" not in inspect.signature(wrapper).parameters, name


# --- wrapper semantics: stdout diversion ----------------------------------------


def test_registered_wrappers_redirect_stdout_prints_to_stderr() -> None:
    """Upstream tool bodies print() to stdout, which is the MCP stdio protocol
    channel — the overlay must divert those writes to stderr."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"noisy", "noisy_async"}))

    @registrar_tool(registrar)
    def noisy() -> str:
        print("upstream chatter")
        return "done"

    @registrar_tool(registrar)
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
    """A naive per-call `contextlib.redirect_stdout` held open across an
    `await` is concurrency-unsafe: if a SECOND overlapping call enters and
    then FINISHES (restoring stdout) before a FIRST, still-running call
    exits, the first call's remaining prints would leak onto the real MCP
    stdio channel. The reference-counted diversion must keep stdout diverted
    for the whole overlapping window regardless of exit order."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"slow", "fast"}))
    slow_started = asyncio.Event()

    @registrar_tool(registrar)
    async def slow() -> str:
        slow_started.set()
        await asyncio.sleep(0.05)
        print("slow chatter (after fast already exited)")
        return "slow-done"

    @registrar_tool(registrar)
    async def fast() -> str:
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


# --- wrapper semantics: path confinement BEFORE the tool body -------------------


def test_registered_wrappers_refuse_before_invoking_the_body_on_an_escaping_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"reads_a_path"}))
    invoked = False

    @registrar_tool(registrar)
    def reads_a_path(project_path: str) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {"ok": True}

    result = fake.tools["reads_a_path"](project_path=str(tmp_path / "outside.PrjPcb"))

    assert result == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}
    assert invoked is False, "the tool body must never run once confinement refuses"


def test_registered_wrappers_refuse_cleanly_when_the_workspace_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"reads_a_path"}))
    invoked = False

    @registrar_tool(registrar)
    def reads_a_path(project_path: str) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {"ok": True}

    result = fake.tools["reads_a_path"](project_path="board.PrjPcb")

    assert result == {"error": "path escapes workspace", "reason": REASON_PATH_ESCAPES_WORKSPACE}
    assert invoked is False


def test_tools_with_no_path_shaped_argument_are_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    fake = FakeMCP()
    registrar = TrimmingRegistrar(fake, allowed=frozenset({"no_path_args"}))

    @registrar_tool(registrar)
    def no_path_args() -> dict[str, object]:
        return {"ok": True}

    assert fake.tools["no_path_args"]() == {"ok": True}


# The registered roster tools that take a `project_path` argument — every one
# goes through the SAME confinement layer in trimming.py.
_PROJECT_PATH_TOOLS = (
    "proj_list_documents",
    "proj_get_stats",
    "proj_get_bom",
    "proj_get_nets",
    "proj_get_component_info",
)


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_an_absolute_path_outside_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "outside" / "board.PrjPcb"
    fake = FakeMCP()
    register_overlay(fake)

    result = await call_tool(fake.tools[tool_name], project_path=str(outside))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_a_traversal_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    fake = FakeMCP()
    register_overlay(fake)

    result = await call_tool(
        fake.tools[tool_name], project_path=str(workspace / ".." / "escape.PrjPcb")
    )

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


@pytest.mark.parametrize("tool_name", _PROJECT_PATH_TOOLS)
async def test_project_path_tools_refuse_a_symlink_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tool_name: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    outside = tmp_path / "secret.PrjPcb"
    outside.write_text("|RECORD=Design\n", encoding="utf-8")
    link = workspace / "innocent.PrjPcb"
    link.symlink_to(outside)
    fake = FakeMCP()
    register_overlay(fake)

    result = await call_tool(fake.tools[tool_name], project_path=str(link))

    assert result["reason"] == REASON_PATH_ESCAPES_WORKSPACE


# --- the proj_get_nets force_recompile pin --------------------------------------


def test_pinned_parameters_pin_proj_get_nets_force_recompile_false() -> None:
    """Upstream `force_recompile=True` saves ALL dirty documents — a disk
    write hidden behind a read-only tool. The pin is data, not code, so
    future pins extend the mapping rather than the wrapper."""
    assert PINNED_PARAMETERS["proj_get_nets"] == {"force_recompile": False}


def test_proj_get_nets_advertised_signature_lacks_force_recompile() -> None:
    fake = FakeMCP()
    register_overlay(fake)
    wrapper = fake.tools["proj_get_nets"]
    assert "force_recompile" not in inspect.signature(wrapper).parameters
    assert "force_recompile" not in getattr(wrapper, "__annotations__", {})


async def test_proj_get_nets_wrapper_neutralizes_a_smuggled_force_recompile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even a caller that smuggles `force_recompile=True` past the advertised
    schema must reach the bridge WITHOUT the flag: upstream's tool body only
    forwards it when truthy, so pinning False means the IPC command never
    carries it and no dirty document is ever saved."""
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    import eda_agent.tools.project as project_module

    bridge = RecordingBridge()
    monkeypatch.setattr(project_module, "get_bridge", lambda: bridge)
    fake = FakeMCP()
    register_overlay(fake)

    result = await call_tool(fake.tools["proj_get_nets"], force_recompile=True, limit=7)

    assert result == {"pins": [], "count": 0}
    assert len(bridge.commands) == 1
    command, params = bridge.commands[0]
    assert command == "project.get_nets"
    assert "force_recompile" not in params, "the smuggled flag reached the bridge"


# --- the list_nets backend pin (H2) ----------------------------------------------


def test_pinned_parameters_pin_list_nets_backend_altium() -> None:
    """Upstream's `list_nets(backend=...)` routes through `resolve_backend`,
    which will happily construct the KiCad backend on request — a model
    argument must never switch backends on the altium overlay."""
    assert PINNED_PARAMETERS["list_nets"] == {"backend": "altium"}


def test_list_nets_advertised_signature_lacks_backend() -> None:
    fake = FakeMCP()
    register_overlay(fake)
    wrapper = fake.tools["list_nets"]
    assert "backend" not in inspect.signature(wrapper).parameters
    assert "backend" not in getattr(wrapper, "__annotations__", {})


async def test_list_nets_wrapper_neutralizes_a_smuggled_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a caller that smuggles `backend="kicad"` past the advertised
    schema must reach upstream's body with the pinned "altium"."""
    import eda_agent.tools.eda as eda_module

    resolved: list[object] = []

    class _FakeBackend:
        name = "altium"

        async def snapshot(self) -> Any:
            raise RuntimeError("stop after resolve")

    def fake_resolve(name: object = None) -> Any:
        resolved.append(name)
        return _FakeBackend()

    monkeypatch.setattr(eda_module, "resolve_backend", fake_resolve)
    fake = FakeMCP()
    register_overlay(fake)

    await call_tool(fake.tools["list_nets"], backend="kicad")

    assert resolved == ["altium"], "the smuggled backend name reached resolve_backend"


async def test_kicad_backend_is_never_constructed_by_the_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end with upstream's REAL resolve_backend: a full roster
    registration plus a smuggled-backend list_nets call must never construct
    the KiCad backend class."""
    import eda_agent.bridge as bridge_module
    import eda_agent.core.backends as backends_module

    constructed: list[str] = []
    original_init = backends_module.KiCadBackend.__init__

    def recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        constructed.append("KiCadBackend")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(backends_module.KiCadBackend, "__init__", recording_init)
    monkeypatch.setattr(bridge_module, "get_bridge", lambda: RecordingBridge())
    fake = FakeMCP()
    register_overlay(fake)

    result = await call_tool(fake.tools["list_nets"], backend="kicad")

    assert constructed == [], "the KiCad backend was constructed on the altium overlay"
    assert isinstance(result, dict)


async def test_pinned_parameters_are_generic_registrar_behaviour() -> None:
    """The pin mechanism is generic: any {tool: {param: value}} entry is
    forced on the call and stripped from the advertised surface."""
    fake = FakeMCP()
    registrar = TrimmingRegistrar(
        fake,
        allowed=frozenset({"sample"}),
        pinned={"sample": {"danger": False}},
    )
    seen: dict[str, object] = {}

    @registrar_tool(registrar)
    async def sample(value: str, danger: bool = True) -> dict[str, object]:
        seen.update({"value": value, "danger": danger})
        return {"ok": True}

    wrapper = fake.tools["sample"]
    assert "danger" not in inspect.signature(wrapper).parameters
    await call_tool(wrapper, value="x", danger=True)
    assert seen == {"value": "x", "danger": False}


# --- the overlay package stays standalone ---------------------------------------


def test_solus_package_imports_only_stdlib_upstream_and_mcp_libs() -> None:
    """The fork runs standalone on customer machines: solus/ may import the
    stdlib, the vendored `eda_agent`, the MCP SDK, and itself — never the
    cloud codebase (solus_api / packages.*)."""
    allowed_roots = frozenset({"eda_agent", "mcp", "solus"})
    offenders: list[str] = []
    for source in sorted(SOLUS_DIR.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in sys.stdlib_module_names or root in allowed_roots:
                    continue
                offenders.append(f"{source.name}: {root}")
    assert offenders == [], f"forbidden imports in solus/: {offenders}"


# --- solus/server.py: import safety and startup posture -------------------------


def test_solus_server_module_imports_cleanly_with_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the entry module must have no side effects beyond the
    sys.path bootstrap — no server start, no file writes, no env reads."""
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    overlay_module("server")
    assert set(tmp_path.iterdir()) == before
    assert sys.dont_write_bytecode is True


def test_solus_server_never_touches_upstreams_server_dashboard_or_web() -> None:
    """Upstream's `eda_agent.server` registers the FULL backend at import
    time and spawns the Flask dashboard; the web/ package is the dashboard
    itself. The overlay entry must never import any of them, and must never
    enable the kicad backend."""
    source = (SOLUS_DIR / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "eda_agent.server",
        "eda_agent.web",
        "eda_agent.web.dashboard",
        "eda_agent.tools.kicad",
    }
    assert not (imported & forbidden), f"forbidden imports in server.py: {imported & forbidden}"
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert "register_backend" not in called, (
        "server.py must never call upstream's register_backend (it can enable "
        "the kicad backend and the minimal meta-dispatch toolset)"
    )
    assert "register_allowlisted_tools" in called, (
        "server.py must register through the trimming registration"
    )


def _pin_environment(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Set the env exactly as bin/launch pins it for *workspace*."""
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    monkeypatch.setenv("EDA_AGENT_BACKEND", "altium")
    monkeypatch.setenv("EDA_AGENT_WORKSPACE", str(workspace / ".eda-agent-ipc"))
    monkeypatch.setenv(
        "EDA_AGENT_POINTER_FILE", str(workspace / ".eda-agent-ipc" / "workspace-path.txt")
    )


def test_verify_pins_accepts_the_launcher_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = overlay_module("server")
    _pin_environment(monkeypatch, tmp_path)

    ipc_dir, pointer_file = server.verify_ipc_environment_pins()

    assert ipc_dir == (tmp_path / ".eda-agent-ipc").resolve()
    assert pointer_file == ipc_dir / "workspace-path.txt"


def test_verify_pins_accepts_a_symlinked_workspace_spelling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """bin/launch composes the pins textually from SOLUS_MCP_WORKSPACE; when
    that spelling contains a symlink (e.g. /tmp on macOS) the resolved pin
    still byte-matches the confined computation."""
    real = tmp_path / "real-workspace"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    server = overlay_module("server")
    _pin_environment(monkeypatch, alias)

    ipc_dir, _ = server.verify_ipc_environment_pins()

    assert ipc_dir == (real / ".eda-agent-ipc").resolve()


def test_verify_pins_refuses_an_unconfigured_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = overlay_module("server")
    workspace_mod = overlay_module("workspace")
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.setenv("EDA_AGENT_BACKEND", "altium")
    monkeypatch.setenv("EDA_AGENT_WORKSPACE", str(tmp_path / ".eda-agent-ipc"))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(workspace_mod.WorkspaceNotConfiguredError):
        server.verify_ipc_environment_pins()


@pytest.mark.parametrize(
    "pin", ["EDA_AGENT_WORKSPACE", "EDA_AGENT_POINTER_FILE", "EDA_AGENT_BACKEND"]
)
def test_verify_pins_refuses_a_missing_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pin: str
) -> None:
    server = overlay_module("server")
    _pin_environment(monkeypatch, tmp_path)
    monkeypatch.delenv(pin)

    with pytest.raises(server.EnvPinMismatchError):
        server.verify_ipc_environment_pins()


@pytest.mark.parametrize("pin", ["EDA_AGENT_WORKSPACE", "EDA_AGENT_POINTER_FILE"])
def test_verify_pins_refuses_a_repointed_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pin: str
) -> None:
    """A pin that names ANY other location than the confined computation —
    e.g. upstream's machine-global default or another team's workspace —
    refuses the start outright."""
    server = overlay_module("server")
    _pin_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(pin, str(tmp_path / "elsewhere" / "drop-box"))

    with pytest.raises(server.EnvPinMismatchError):
        server.verify_ipc_environment_pins()


def test_verify_pins_refuses_a_non_altium_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = overlay_module("server")
    _pin_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("EDA_AGENT_BACKEND", "kicad")

    with pytest.raises(server.EnvPinMismatchError):
        server.verify_ipc_environment_pins()


def test_main_refuses_to_start_before_building_the_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = overlay_module("server")
    built = False

    def fake_build() -> Any:
        nonlocal built
        built = True

    monkeypatch.setattr(server, "build_server", fake_build)
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        server.main()

    assert excinfo.value.code == 1
    assert built is False, "the server must never be built once the pins refuse"


def test_main_serves_stdio_with_the_verified_pins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = overlay_module("server")
    _pin_environment(monkeypatch, tmp_path)

    class FakeServer:
        def __init__(self) -> None:
            self.transport: str | None = None

        def run(self, transport: str) -> None:
            self.transport = transport

    fake = FakeServer()
    monkeypatch.setattr(server, "build_server", lambda: fake)

    server.main()

    assert fake.transport == "stdio"
    assert (tmp_path / ".eda-agent-ipc").is_dir(), (
        "main must create the confined IPC drop box (upstream's "
        "config.ensure_workspace equivalent, confined)"
    )


def test_build_server_registers_exactly_the_roster_on_a_real_fastmcp() -> None:
    """End to end against the REAL MCP SDK: the running server's own tool
    table — the one an MCP client and any dispatch path sees — is exactly the
    registered roster, and the advertised proj_get_nets schema carries no
    force_recompile."""
    pytest.importorskip("mcp.server.fastmcp")
    server = overlay_module("server")

    built = server.build_server()

    tools = asyncio.run(built.list_tools())
    assert {tool.name for tool in tools} == set(registered_roster())
    nets = next(tool for tool in tools if tool.name == "proj_get_nets")
    properties = cast(dict[str, Any], nets.inputSchema).get("properties", {})
    assert "force_recompile" not in properties
