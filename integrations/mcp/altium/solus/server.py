#!/usr/bin/env python3
"""Solus entry point for the vendored eda-agent fork (SOLUSDEV-102 ALT-5).

`bin/launch` / `bin/launch.cmd` exec THIS file instead of upstream's
`eda_agent.server` module. That module is never imported here — it builds a
FastMCP and registers the FULL backend surface AT IMPORT TIME, spawns the
Flask dashboard thread (`eda_agent.web`), probes ports with psutil, and
re-execs itself on CLI flags. The overlay differences:

* logging goes to stderr only — stdout is the MCP stdio protocol channel;
* the IPC environment pins are VERIFIED before anything serves:
  `EDA_AGENT_WORKSPACE` / `EDA_AGENT_POINTER_FILE` must byte-match (after
  the same symlink resolution `solus/pointer.py` applies) the confined
  paths computed from `SOLUS_MCP_WORKSPACE`, and `EDA_AGENT_BACKEND` must
  name the altium backend this overlay serves. Any mismatch — or an
  unconfigured workspace, or a symlink escape of the derived paths —
  refuses the start; upstream's machine-global pointer default is
  unreachable on every code path;
* only the allowlisted roster is registered (solus/registration.py) on a
  FastMCP built HERE; upstream's register_backend is never called, so the
  kicad backend, the minimal meta-dispatch toolset, and its ToolRegistry
  can never be enabled;
* no dashboard, no web UI, no CLI subcommands, no argv processing.

Importing this module has no side effects beyond the sys.path bootstrap;
directory creation and serving happen only under `main()`.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

_FORK_DIR = Path(__file__).resolve().parents[1]

#: The one backend this overlay serves; bin/launch pins EDA_AGENT_BACKEND to
#: exactly this value.
_REQUIRED_BACKEND = "altium"


def _bootstrap_sys_path() -> None:
    """Make `solus` and the vendored `eda_agent` importable when this file is
    exec'd as a plain script by the launcher."""
    # Never write bytecode into the vendored tree: __pycache__ under
    # upstream/ would violate the byte-pristine vendored-tree posture.
    sys.dont_write_bytecode = True
    for path in (_FORK_DIR, _FORK_DIR / "upstream" / "src"):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)


_bootstrap_sys_path()

# Package-flexible imports: the tests import this module as part of the
# overlay package (`altium_solus.server`, relative imports); bin/launch execs
# it as a plain script, where only the absolute `solus.*` names (put on
# sys.path by the bootstrap above) can resolve.
try:
    from .pointer import PointerConfinementError, ipc_workspace_dir, pointer_file_path
    from .registration import register_allowlisted_tools
    from .workspace import WorkspaceNotConfiguredError, workspace_root
except ImportError:  # pragma: no cover - script mode under bin/launch
    from solus.pointer import (  # type: ignore[import-not-found, no-redef]
        PointerConfinementError,
        ipc_workspace_dir,
        pointer_file_path,
    )
    from solus.registration import (  # type: ignore[import-not-found, no-redef]
        register_allowlisted_tools,
    )
    from solus.workspace import (  # type: ignore[import-not-found, no-redef]
        WorkspaceNotConfiguredError,
        workspace_root,
    )


class EnvPinMismatchError(RuntimeError):
    """An EDA_AGENT_* environment pin is missing or does not match the
    confined computation — the child environment is not the one bin/launch
    constructs, so the server must refuse to start."""


def _configure_logging() -> None:
    """stderr-only logging: stdout is the MCP protocol channel and nothing
    may ever write log files (upstream logs into its own tree)."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        force=True,
        format="%(asctime)s - %(levelname)s - [PID:%(process)d] - %(message)s",
    )


def verify_ipc_environment_pins() -> tuple[Path, Path]:
    """Validate the launcher-set environment pins against the confined
    computation and return `(ipc_dir, pointer_file)`.

    Upstream's file-drop IPC honours `EDA_AGENT_WORKSPACE` and
    `EDA_AGENT_POINTER_FILE` (`upstream/src/eda_agent/config.py`), falling
    back to a MACHINE-GLOBAL pointer path. bin/launch derives both pins from
    `SOLUS_MCP_WORKSPACE`; this function recomputes them via
    `solus/pointer.py` (fail-closed workspace, symlink-escape refusal) and
    requires the resolved env values to byte-match. Raises
    `WorkspaceNotConfiguredError`, `PointerConfinementError`, or
    `EnvPinMismatchError` — the caller must treat all three as refusals.
    """
    backend = os.environ.get("EDA_AGENT_BACKEND", "")
    if not backend:
        raise EnvPinMismatchError("EDA_AGENT_BACKEND is not set; bin/launch always pins it")
    if backend != _REQUIRED_BACKEND:
        raise EnvPinMismatchError(
            f"EDA_AGENT_BACKEND={backend!r}: this overlay serves the "
            f"{_REQUIRED_BACKEND!r} backend only"
        )
    root = workspace_root()
    expected: dict[str, Path] = {
        "EDA_AGENT_WORKSPACE": ipc_workspace_dir(root),
        "EDA_AGENT_POINTER_FILE": pointer_file_path(root),
    }
    for name, want in expected.items():
        raw = os.environ.get(name, "")
        if not raw:
            raise EnvPinMismatchError(f"{name} is not set; bin/launch always pins it")
        got = Path(raw).resolve()
        if str(got) != str(want):
            raise EnvPinMismatchError(f"{name}={raw!r} resolves to {got}, not the confined {want}")
    return expected["EDA_AGENT_WORKSPACE"], expected["EDA_AGENT_POINTER_FILE"]


def build_server() -> Any:
    """A FastMCP built here, carrying exactly the trimmed registration."""
    # Imported lazily: the MCP SDK lives in the fork-private venv.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(f"eda-agent-{_REQUIRED_BACKEND}")
    registrar = register_allowlisted_tools(server)
    logging.info(
        "Solus altium overlay: registered %s, trimmed %s upstream tools",
        sorted(registrar.registered),
        len(registrar.blocked),
    )
    return server


def main() -> None:
    _configure_logging()
    try:
        ipc_dir, pointer_file = verify_ipc_environment_pins()
    except (EnvPinMismatchError, PointerConfinementError, WorkspaceNotConfiguredError) as exc:
        logging.error("refusing to start: %s", exc)
        raise SystemExit(1) from exc
    # The confined equivalent of upstream serve_mcp's config.ensure_workspace():
    # the file-drop IPC exchange must exist before the bridge's first drop.
    ipc_dir.mkdir(parents=True, exist_ok=True)
    logging.info(
        "Starting Solus altium MCP server (trimmed fork overlay); ipc=%s pointer=%s",
        ipc_dir,
        pointer_file,
    )
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
