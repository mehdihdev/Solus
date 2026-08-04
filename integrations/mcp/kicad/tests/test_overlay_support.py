"""SOLUSDEV-100 T1b — shared import scaffolding for the overlay test modules.

The kicad fork runs standalone on customer machines inside its private venv
(`bin/launch`), so its runtime dependencies (`mcp`, `fastmcp`, `pandas`) are
deliberately NOT part of the repo's uv workspace. These tests exercise the
Solus overlay's own logic (trimming, degradation, packaging, allowlist shape)
through duck-typed recorders, installing minimal import stubs for the fork's
lockfile-only dependencies so upstream modules can be imported without them.

This module contains no tests; siblings import it for the bootstrap.
"""

import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_ROOT = REPO_ROOT / "integrations" / "mcp"
FORK = MCP_ROOT / "kicad"
UPSTREAM = FORK / "upstream"
SOLUS = FORK / "solus"
LAUNCH = FORK / "bin" / "launch"
ALLOWLIST_YAML = FORK / "allowlist.yaml"
PROVENANCE = FORK / "PROVENANCE.md"

# Import stubs are ONLY installed when the real package is absent (the repo
# env); on a machine with the fork venv active the real packages win.
_STUBBED_MODULES = ("mcp", "mcp.server", "mcp.server.fastmcp", "fastmcp", "pandas")


class _StubFastMCP:
    """Signature-compatible stand-in for FastMCP in type annotations."""


class _StubContext:
    """Stand-in for the MCP Context annotation (`ctx: Context | None`)."""


class _StubImage:
    """Stand-in for mcp.server.fastmcp.Image (imported by bom_tools)."""


def _install_stub(name: str, **attrs: object) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


def install_import_environment() -> None:
    """Make `solus.*` and `kicad_mcp.*` importable in the repo test env."""
    # Importing the vendored tree must never write bytecode into upstream/ —
    # the vendored tree hash (PROVENANCE) covers a byte-pristine tree.
    sys.dont_write_bytecode = True
    for path in (FORK, UPSTREAM):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)
    try:
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        _install_stub("mcp")
        _install_stub("mcp.server")
        _install_stub(
            "mcp.server.fastmcp",
            FastMCP=_StubFastMCP,
            Context=_StubContext,
            Image=_StubImage,
        )
        sys.modules["mcp"].server = sys.modules["mcp.server"]  # type: ignore[attr-defined]
        sys.modules["mcp.server"].fastmcp = (  # type: ignore[attr-defined]
            sys.modules["mcp.server.fastmcp"]
        )
    try:
        import fastmcp  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        _install_stub("fastmcp", FastMCP=_StubFastMCP)
    try:
        import pandas  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        _install_stub("pandas", DataFrame=object)


install_import_environment()


def test_import_environment_provides_upstream_and_solus_roots() -> None:
    """Sanity check for the scaffolding itself: after the bootstrap, upstream
    `kicad_mcp` is importable and every stubbed name resolves."""
    import kicad_mcp  # noqa: F401
    from mcp.server.fastmcp import Context, FastMCP, Image

    for stub in (FastMCP, Context, Image):
        assert stub is not None
    for name in _STUBBED_MODULES:
        assert name in sys.modules, f"{name} neither real nor stubbed"


class FakeMCP:
    """Duck-typed FastMCP recorder: the only surface the upstream register
    functions and the Solus registrar touch is `.tool()`."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        name_override = kwargs.get("name")

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            name = name_override if isinstance(name_override, str) else fn.__name__
            if name in self.tools:
                raise AssertionError(f"duplicate tool registration: {name}")
            self.tools[name] = fn
            return fn

        return decorator


def write_minimal_project(directory: Path, stem: str = "board") -> Path:
    """A tiny on-disk KiCad project the upstream regex parser can read."""
    directory.mkdir(parents=True, exist_ok=True)
    project = directory / f"{stem}.kicad_pro"
    project.write_text(json.dumps({"meta": {"filename": f"{stem}.kicad_pro"}}))
    schematic = directory / f"{stem}.kicad_sch"
    schematic.write_text(
        "(kicad_sch (version 20231120)\n"
        '  (symbol (lib_id "Device:R") (at 10 20 0)\n'
        '    (property "Reference" "R1" (at 0 0 0))\n'
        '    (property "Value" "10k" (at 0 0 0))\n'
        "  )\n"
        '  (symbol (lib_id "Device:C") (at 30 40 0)\n'
        '    (property "Reference" "C1" (at 0 0 0))\n'
        '    (property "Value" "100n" (at 0 0 0))\n'
        "  )\n"
        ")\n"
    )
    return project
