#!/usr/bin/env python3
"""Entry point for the Solus-authored `code` MCP server (SOLUSDEV-250).

`bin/launch` execs THIS file. It builds a FastMCP (the MCP SDK's built-in
`mcp.server.fastmcp`, from the fork-private venv) and registers exactly the
roster: the reads `probe_environment` and `plan`, and the gated
`create_environment`, `install`, `run`, `test`. Every gated tool calls
`plan_action` first and executes EXACTLY that argv (`execute_plan`) — one
source of truth. Logging goes to stderr only — stdout is the MCP protocol
channel. Every tool returns a plain dict (structuredContent) and NEVER
raises: any internal failure collapses to the documented refusal shape.

Importing this module has no side effects beyond the sys.path bootstrap;
the server starts only under `main()`.
"""

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FORK_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_sys_path() -> None:
    """Make `solus` importable when exec'd as a plain script by the launcher."""
    sys.dont_write_bytecode = True
    entry = str(_FORK_DIR)
    if entry not in sys.path:
        sys.path.insert(0, entry)


_bootstrap_sys_path()

# Package-flexible imports: tests import this module as `code_solus.server`
# (relative imports); bin/launch execs it as a plain script, where only the
# absolute `solus.*` names put on sys.path above can resolve.
try:
    from .execute import execute_plan, pinned_which, refusal
    from .plan import DEFAULT_ENVIRONMENT, DEFAULT_PYTHON, DEFAULT_TEST_TARGET, plan_action
    from .plan import DEFAULT_TIMEOUT_SECONDS as _DEFAULT_TIMEOUT
    from .probe import empty_probe, probe_environment
    from .roster import TOOL_ROSTER
    from .workspace import workspace_root
except ImportError:  # pragma: no cover - script mode under bin/launch
    from solus.execute import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        execute_plan,
        pinned_which,
        refusal,
    )
    from solus.plan import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        DEFAULT_ENVIRONMENT,
        DEFAULT_PYTHON,
        DEFAULT_TEST_TARGET,
        plan_action,
    )
    from solus.plan import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        DEFAULT_TIMEOUT_SECONDS as _DEFAULT_TIMEOUT,
    )
    from solus.probe import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        empty_probe,
        probe_environment,
    )
    from solus.roster import TOOL_ROSTER  # type: ignore[import-not-found, no-redef, unused-ignore]
    from solus.workspace import (
        workspace_root,  # type: ignore[import-not-found, no-redef, unused-ignore]
    )

logger = logging.getLogger("solus.code.server")

SERVER_NAME = "Solus Code"


def _guarded(
    name: str, fallback: Callable[[], dict[str, Any]], body: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Run `body`; on ANY exception log to stderr and answer `fallback()`."""
    try:
        return body()
    except Exception as exc:  # noqa: BLE001 - the never-raises rule
        logger.warning("%s failed: %s: %s", name, type(exc).__name__, exc)
        return fallback()


def tool_probe_environment() -> dict[str, Any]:
    """Probe this machine's Python interpreters, uv, conda, and the linked
    folder's virtualenv (.venv / venv / env) with its installed packages."""
    return _guarded("probe_environment", empty_probe, lambda: probe_environment(workspace_root()))


def tool_plan(action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """The EXACT argv `action` (create_environment | install | run | test)
    would run with `args`, or `ok: false` with the refusal reason. Pure: no
    execution."""
    return _guarded(
        "plan",
        lambda: {"argv": [], "cwd": ".", "ok": False, "reason": "plan failed"},
        lambda: plan_action(workspace_root(), action, args, which=pinned_which).answer(),
    )


def _perform(action: str, args: dict[str, Any]) -> dict[str, Any]:
    """Plan, then execute exactly the plan. The refusal shape on any failure."""

    def body() -> dict[str, Any]:
        root = workspace_root()
        plan = plan_action(root, action, args, which=pinned_which)
        # A refused plan never reaches the executor.
        result = execute_plan(root, plan) if plan.ok else refusal(plan.reason or "refused")
        return {**result, "path": plan.path} if action == "create_environment" else result

    return _guarded(action, lambda: refusal(f"{action} failed"), body)


def tool_create_environment(
    path: str = DEFAULT_ENVIRONMENT, python: str = DEFAULT_PYTHON
) -> dict[str, Any]:
    """Create a virtualenv at `path` inside the linked folder (`uv venv
    --python X` when uv is present, else `python3.X -m venv`). Refuses an
    existing path. Confirmation-gated."""
    return _perform("create_environment", {"path": path, "python": python})


def tool_install(packages: list[str], environment: str = DEFAULT_ENVIRONMENT) -> dict[str, Any]:
    """Install PEP 508 packages into the linked folder's virtualenv with its
    own pip (`uv pip` when uv is present). Refuses options, URLs and paths.
    Confirmation-gated."""
    return _perform("install", {"packages": packages, "environment": environment})


def tool_run(
    script: str,
    args: list[str] | None = None,
    environment: str = DEFAULT_ENVIRONMENT,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run a workspace script with the virtualenv interpreter (timeout ≤ 600 s,
    output tails ≤ 16 KiB). Confirmation-gated."""
    return _perform(
        "run",
        {
            "script": script,
            "args": args,
            "environment": environment,
            "timeout_seconds": timeout_seconds,
        },
    )


def tool_test(
    target: str = DEFAULT_TEST_TARGET,
    environment: str = DEFAULT_ENVIRONMENT,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run `python -m pytest -q -- <target>` with the virtualenv interpreter
    over a workspace target. Confirmation-gated."""
    return _perform(
        "test", {"target": target, "environment": environment, "timeout_seconds": timeout_seconds}
    )


_TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "probe_environment": tool_probe_environment,
    "plan": tool_plan,
    "create_environment": tool_create_environment,
    "install": tool_install,
    "run": tool_run,
    "test": tool_test,
}


def build_server() -> Any:
    """A FastMCP carrying exactly the roster."""
    # Imported lazily: the MCP SDK lives in the fork-private venv.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)
    for name, function in _TOOLS.items():
        server.tool(name=name, description=function.__doc__)(function)
    registered = {tool.name for tool in server._tool_manager.list_tools()}
    if registered != TOOL_ROSTER:
        raise RuntimeError(f"registered {sorted(registered)} != roster {sorted(TOOL_ROSTER)}")
    return server


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        force=True,
        format="%(asctime)s - %(levelname)s - [PID:%(process)d] - %(message)s",
    )


def main() -> None:
    _configure_logging()
    logger.info("Starting Solus code MCP server")
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
