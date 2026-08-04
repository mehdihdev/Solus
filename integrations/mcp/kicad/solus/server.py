#!/usr/bin/env python3
"""Solus entry point for the vendored kicad-mcp fork (SOLUSDEV-100 T1b).

`bin/launch` execs THIS file instead of `upstream/main.py`. The differences
are the T1a-flagged shims:

* logging goes to stderr only — upstream main.py opens `kicad-mcp.log` next
  to itself, i.e. writes inside the pristine `upstream/` tree;
* upstream's `.env` loader is never invoked — `kicad_mcp.utils.env.load_dotenv`
  (called only by upstream main.py) logs environment VALUES from a dropped
  .env file; configuration arrives solely through the launcher's scrubbed
  env allowlist (solus/env_allowlist.py);
* only the allowlisted read roster is registered (solus/registration.py);
  every other upstream tool, resource, and prompt is dead in-process.

Importing this module has no side effects beyond sys.path bootstrap; the
server starts only under `main()`.
"""

import functools
import logging
import sys
from pathlib import Path
from typing import Any

_FORK_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_sys_path() -> None:
    """Make `solus` and the vendored `kicad_mcp` importable when this file is
    exec'd as a plain script by the launcher."""
    # Never write bytecode into the vendored tree: __pycache__ under
    # upstream/ would violate the byte-pristine vendored-tree posture.
    sys.dont_write_bytecode = True
    for path in (_FORK_DIR, _FORK_DIR / "upstream"):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)


_bootstrap_sys_path()


def _configure_logging() -> None:
    """stderr-only logging (T1a shim a): stdout is the MCP protocol channel
    and nothing may ever write files into `upstream/`."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        force=True,
        format="%(asctime)s - %(levelname)s - [PID:%(process)d] - %(message)s",
    )


def build_server() -> Any:
    """The trimmed FastMCP server: upstream's lifespan, Solus's roster."""
    from fastmcp import FastMCP  # type: ignore[import-not-found]
    from kicad_mcp.context import kicad_lifespan

    from solus.registration import register_allowlisted_tools

    lifespan = functools.partial(kicad_lifespan, kicad_modules_available=False)
    server = FastMCP("KiCad", lifespan=lifespan)
    registrar = register_allowlisted_tools(server)
    logging.info(
        "Solus kicad overlay: registered %s, trimmed %s upstream tools",
        sorted(registrar.registered),
        len(registrar.blocked),
    )
    return server


def main() -> None:
    _configure_logging()
    logging.info("Starting Solus kicad MCP server (trimmed fork overlay)")
    server = build_server()
    server.run()  # FastMCP manages its own event loop (stdio transport)


if __name__ == "__main__":
    main()
