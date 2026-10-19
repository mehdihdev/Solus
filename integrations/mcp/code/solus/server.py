#!/usr/bin/env python3
"""Entry point for the Solus-authored `code` MCP server (SOLUSDEV-250).

`bin/launch` execs THIS file. It builds a FastMCP (the MCP SDK's built-in
`mcp.server.fastmcp`, from the fork-private venv) and registers exactly the
roster of environment, Git and Arduino tools. Environment actions call
`plan_action` first and execute exactly that argv (`execute_plan`). Git and
Arduino actions use their complete state-bound dry-run plans. Logging goes to
stderr only — stdout is the MCP protocol channel. Environment tools return their
documented refusal shape. Repository tools expose stable protocol failures and
preserve uncertain mutation outcomes.

Importing this module has no side effects beyond the sys.path bootstrap;
the server starts only under `main()`.
"""

import asyncio
import functools
import inspect
import logging
import signal
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import FrameType
from typing import Any, Literal

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
    from . import (
        arduino_compile,
        arduino_process,
        arduino_toolchain,
        arduino_upload,
        git_execution,
        git_operations,
        profiles,
    )
    from .execute import default_runner, execute_plan, pinned_which, prepare, refusal, run_sandboxed
    from .plan import DEFAULT_ENVIRONMENT, DEFAULT_PYTHON, DEFAULT_TEST_TARGET, plan_action
    from .plan import DEFAULT_TIMEOUT_SECONDS as _DEFAULT_TIMEOUT
    from .probe import empty_probe, probe_environment
    from .processes import Registry
    from .progress import CANCEL_EVENT, OUTPUT_CALLBACK, AsyncOutput
    from .roster import TOOL_ROSTER
    from .workspace import workspace_root
except ImportError:  # pragma: no cover - script mode under bin/launch
    from solus import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        arduino_compile,
        arduino_process,
        arduino_toolchain,
        arduino_upload,
        git_execution,
        git_operations,
        profiles,
    )
    from solus.execute import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        default_runner,
        execute_plan,
        pinned_which,
        prepare,
        refusal,
        run_sandboxed,
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
    from solus.processes import (  # type: ignore[import-not-found, no-redef, unused-ignore]
        Registry,
    )
    from solus.progress import (
        CANCEL_EVENT,
        OUTPUT_CALLBACK,
        AsyncOutput,  # type: ignore[import-not-found, no-redef, unused-ignore]
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


def tool_probe_environment(environment: str | None = None) -> dict[str, Any]:
    """Probe this machine's Python interpreters, uv, conda, and the linked
    folder's requested virtualenv, or the first of .venv / venv / env when
    omitted, with its installed packages. An explicit target never falls back."""
    return _guarded(
        "probe_environment",
        empty_probe,
        lambda: probe_environment(workspace_root(), environment=environment),
    )


def tool_plan(action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """The EXACT argv `action` (create_environment | install | run | test | exec |
    process_start | profile_capture) would run with `args`, plus the sandbox, profile
    and environment it would use, or `ok: false` with the refusal reason. Pure."""
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


# --- SOLUSDEV-317: commands, processes, profiles (code-command-execution.md §2) ------

_REGISTRY: Registry | None = None
_REGISTRY_LOCK = threading.Lock()
MAX_PROCESS_ID_CHARS = 64


def _registry() -> Registry:
    """The server's one process registry, for the linked workspace."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = Registry(workspace_root())
        return _REGISTRY


def tool_exec(
    argv: list[str],
    cwd: str = ".",
    environment: str | None = None,
    profile: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run one argument list (never a shell) in the linked folder inside the OS sandbox.
    argv[0] resolves to an absolute program without the inherited PATH; shells,
    wrappers, elevation and inline code are refused. Confirmation-gated."""
    args = {"argv": argv, "cwd": cwd, "environment": environment, "profile": profile}
    return _perform("exec", {**args, "timeout_seconds": timeout_seconds})


def _process_refusal(reason: str) -> dict[str, Any]:
    return Registry._start_refusal(reason)


def tool_process_start(
    argv: list[str],
    cwd: str = ".",
    environment: str | None = None,
    profile: str | None = None,
    name: str | None = None,
    max_runtime_seconds: int = 3600,
) -> dict[str, Any]:
    """Start a long-running sandboxed process (at most 4) and return immediately.
    It is stopped after max_runtime_seconds and when the server exits; never restarted.
    Confirmation-gated."""

    def body() -> dict[str, Any]:
        root = workspace_root()
        args: dict[str, Any] = {"argv": argv, "cwd": cwd, "environment": environment}
        args |= {"profile": profile, "name": name, "max_runtime_seconds": max_runtime_seconds}
        plan = plan_action(root, "process_start", args, which=pinned_which)
        prepared = prepare(root, plan) if plan.ok else plan.reason or "refused"
        if isinstance(prepared, str):
            return _process_refusal(prepared)
        with prepared.handing_over():
            return _registry().start(
                prepared.argv,
                display_argv=list(plan.argv),
                cwd=prepared.cwd,
                cwd_label=plan.cwd,
                env=prepared.env,
                name=plan.label,
                max_runtime_seconds=plan.max_runtime_seconds or 3600,
                sandbox=plan.sandbox,
            )

    return _guarded("process_start", lambda: _process_refusal("process_start failed"), body)


def tool_process_stop(process_id: str) -> dict[str, Any]:
    """Stop a process SOL started: SIGTERM to its group, SIGKILL after 5 s."""
    fallback = {
        "ok": False,
        "process_id": process_id[:MAX_PROCESS_ID_CHARS],
        "state": None,
        "exit_code": None,
        "reason": "process_stop failed",
    }
    return _guarded(
        "process_stop",
        lambda: dict(fallback),
        lambda: _registry().stop(process_id[:MAX_PROCESS_ID_CHARS]),
    )


def tool_process_status(process_id: str | None = None, cursor: int = 0) -> dict[str, Any]:
    """Processes SOL started on this machine and, for one process_id, its output
    chunks after cursor (at most 64 KiB per answer)."""
    if cursor < 0:
        return {"processes": [], "output": None, "reason": "cursor must be >= 0"}
    key = process_id[:MAX_PROCESS_ID_CHARS] if process_id is not None else None
    return _guarded(
        "process_status",
        lambda: {"processes": [], "output": None},
        lambda: _registry().status(process_id=key, cursor=cursor),
    )


def _capture_refusal(name: str, reason: str) -> dict[str, Any]:
    return profiles._capture_refusal(name, reason)


def tool_profile_capture(name: str, setup_file: str, extends: str | None = None) -> dict[str, Any]:
    """Source a setup file (ROS setup.bash, …) with a fixed Solus script inside the
    sandbox and store the filtered environment privately on this machine. Answers
    variable names only, never values. Confirmation-gated."""

    def body() -> dict[str, Any]:
        root = workspace_root()
        args = {"name": name, "setup_file": setup_file, "extends": extends}
        plan = plan_action(root, "profile_capture", args, which=pinned_which)
        if not plan.ok:
            return _capture_refusal(name, plan.reason or "refused")
        runner = functools.partial(default_runner, tail_bytes=profiles.MAX_ENV_BYTES + 1)
        ran = run_sandboxed(root, plan, runner=runner)
        if isinstance(ran, str):
            return _capture_refusal(name, ran)
        extended = plan.profile.name if plan.profile else None
        setup = plan.setup_file or setup_file
        return profiles.finish_capture(
            root, plan.capture_name or name, setup, extended, ran.outcome, ran.env
        )

    return _guarded("profile_capture", lambda: _capture_refusal(name, "capture failed"), body)


def tool_profile_list() -> dict[str, Any]:
    """Stored environment profiles: names and variable names, never values."""
    return _guarded(
        "profile_list",
        lambda: {"profiles": []},
        lambda: {"profiles": profiles.list_profiles(workspace_root())},
    )


def tool_profile_delete(name: str) -> dict[str, Any]:
    """Delete a stored environment profile. Confirmation-gated."""
    return _guarded(
        "profile_delete",
        lambda: {"ok": False, "name": name[:64], "reason": "profile_delete failed"},
        lambda: profiles.delete(workspace_root(), name),
    )


def _git_call(operation: Callable[..., dict[str, Any]], **args: Any) -> dict[str, Any]:
    try:
        root = workspace_root()
    except (OSError, RuntimeError):
        raise ValueError("workspace_unavailable") from None
    try:
        return operation(root, **args)
    except git_execution.GitOperationError as exc:
        raise ValueError(str(exc)) from None
    except OSError:
        raise ValueError("git_unavailable") from None


def tool_git_status() -> dict[str, Any]:
    """Read the linked repository's HEAD, staged/unstaged paths and index fingerprint."""
    return _git_call(git_operations.git_status)


def tool_git_log(limit: int = 10) -> dict[str, Any]:
    """Read up to 50 recent commits in the linked repository, with bounded output."""
    return _git_call(git_operations.git_log, limit=limit)


def tool_git_diff(scope: str, paths: list[str] | None = None) -> dict[str, Any]:
    """Read the staged or unstaged diff, optionally for explicit workspace-relative paths."""
    return _git_call(git_operations.git_diff, scope=scope, paths=paths)


def tool_git_commit(
    message: str, expected_head: str, expected_index_fingerprint: str, dry_run: bool = False
) -> dict[str, Any]:
    """Commit only the already staged index after approval of its complete diff and state.
    dry_run previews without writing. Never stages files or resolves conflicts."""
    return _git_call(
        git_operations.git_commit,
        message=message,
        expected_head=expected_head,
        expected_index_fingerprint=expected_index_fingerprint,
        dry_run=dry_run,
    )


def tool_git_push(
    remote: str,
    branch: str,
    expected_head: str,
    expected_remote_head: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Push one exact commit to an existing configured remote after explicit approval.
    dry_run checks the destination and remote tip. Never force-pushes or adds credentials."""
    return _git_call(
        git_operations.git_push,
        remote=remote,
        branch=branch,
        expected_head=expected_head,
        expected_remote_head=expected_remote_head,
        dry_run=dry_run,
    )


async def _arduino_call(operation: Callable[..., dict[str, Any]], **args: Any) -> dict[str, Any]:
    """Keep MCP responsive and propagate cancellation into bounded owned work."""
    cancelled = threading.Event()
    token = arduino_process.CANCEL_EVENT.set(cancelled)
    try:
        return await asyncio.to_thread(operation, **args)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    except arduino_toolchain.ArduinoError as exc:
        raise ValueError(str(exc)) from None
    except OSError:
        raise ValueError("toolchain_unavailable") from None
    finally:
        arduino_process.CANCEL_EVENT.reset(token)


async def tool_arduino_probe() -> dict[str, Any]:
    """Verify the pinned Arduino CLI and Uno toolchain locally, without running the CLI."""
    return await _arduino_call(arduino_toolchain.arduino_probe)


async def tool_arduino_prepare(dry_run: bool = False) -> dict[str, Any]:
    """Prepare the frozen Arduino Uno compiler after approval of all dependencies and paths.
    dry_run previews without installing. Does not identify or access attached boards."""
    return await _arduino_call(arduino_toolchain.arduino_prepare, dry_run=dry_run)


async def tool_arduino_compile(
    sketch: str, fqbn: Literal["arduino:avr:uno"], dry_run: bool = False
) -> dict[str, Any]:
    """Compile a linked workspace sketch for arduino:avr:uno after approval of the full plan.
    Uses an offline isolated snapshot. Returns verified artifacts; never uploads to a board."""
    try:
        root = workspace_root()
    except (OSError, RuntimeError):
        raise ValueError("workspace_unavailable") from None
    return await _arduino_call(
        arduino_compile.arduino_compile, root=root, sketch=sketch, fqbn=fqbn, dry_run=dry_run
    )


async def tool_arduino_upload(
    sketch: str,
    fqbn: Literal["arduino:avr:uno"],
    build_id: str,
    device_ref: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Preview one verified workspace application build; execution is currently unavailable.
    Upload refuses until exclusive serial ownership can be handed to the uploader.
    Select a current USB device_ref, never a tty path. Prior firmware is unknown.
    A started failure has unknown device state and must never be retried automatically."""
    try:
        root = workspace_root()
    except (OSError, RuntimeError):
        raise ValueError("workspace_unavailable") from None
    return await _arduino_call(
        arduino_upload.arduino_upload,
        root=root,
        sketch=sketch,
        fqbn=fqbn,
        build_id=build_id,
        device_ref=device_ref,
        dry_run=dry_run,
    )


_TOOLS: dict[str, Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]] = {
    "probe_environment": tool_probe_environment,
    "plan": tool_plan,
    "create_environment": tool_create_environment,
    "install": tool_install,
    "run": tool_run,
    "test": tool_test,
    "git_status": tool_git_status,
    "git_log": tool_git_log,
    "git_diff": tool_git_diff,
    "git_commit": tool_git_commit,
    "git_push": tool_git_push,
    "arduino_probe": tool_arduino_probe,
    "arduino_prepare": tool_arduino_prepare,
    "arduino_compile": tool_arduino_compile,
    "arduino_upload": tool_arduino_upload,
    "exec": tool_exec,
    "process_start": tool_process_start,
    "process_stop": tool_process_stop,
    "process_status": tool_process_status,
    "profile_capture": tool_profile_capture,
    "profile_list": tool_profile_list,
    "profile_delete": tool_profile_delete,
}
#: Tools that stream incremental output (MCP progress) while they run.
STREAMING_TOOLS = frozenset({"run", "test", "exec", "arduino_upload"})
#: Strict argument models: extra fields forbidden, no type coercion.
STRICT_PREFIXES = ("git_", "arduino_", "process_", "profile_")
STRICT_TOOLS = frozenset({"exec"})


def _streaming_tool(server: Any, function: Callable[..., Any]) -> Callable[..., Any]:
    """Use the SDK request context without exposing a model-controlled callback."""

    @functools.wraps(function)
    async def invoke(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output = AsyncOutput(server.get_context())
        output_token = OUTPUT_CALLBACK.set(output.output)
        cancel_token = CANCEL_EVENT.set(output.cancelled)
        operation = (
            function(*args, **kwargs)
            if inspect.iscoroutinefunction(function)
            else asyncio.to_thread(function, *args, **kwargs)
        )
        worker = asyncio.create_task(operation)
        publisher = asyncio.create_task(output.publish())
        try:
            result = await asyncio.shield(worker)
            output.finished.set()
            try:
                await asyncio.wait_for(asyncio.shield(publisher), timeout=5)
            except Exception:
                publisher.cancel()
            return dict(result)
        except asyncio.CancelledError:
            output.cancelled.set()
            if inspect.iscoroutinefunction(function):
                worker.cancel()
            await asyncio.shield(worker)
            raise
        finally:
            publisher.cancel()
            OUTPUT_CALLBACK.reset(output_token)
            CANCEL_EVENT.reset(cancel_token)

    return invoke


def build_server() -> Any:
    """A FastMCP carrying exactly the roster."""
    # Imported lazily: the MCP SDK lives in the fork-private venv.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)
    for name, function in _TOOLS.items():
        registered_function = (
            _streaming_tool(server, function) if name in STREAMING_TOOLS else function
        )
        server.tool(name=name, description=function.__doc__)(registered_function)
        if name.startswith(STRICT_PREFIXES) or name in STRICT_TOOLS:
            tool = server._tool_manager.get_tool(name)
            if tool is None:
                raise RuntimeError("Strict tool registration failed")
            model = tool.fn_metadata.arg_model
            model.model_config["extra"] = "forbid"
            model.model_config["strict"] = True
            model.model_config["hide_input_in_errors"] = True
            model.model_rebuild(force=True)
            tool.parameters = model.model_json_schema(by_alias=True)
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


def _exit_on_signal(signum: int, _frame: FrameType | None) -> None:
    """SIGTERM/SIGINT unwind through main()'s cleanup like stdin EOF does."""
    raise SystemExit(128 + signum)


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _exit_on_signal)
    signal.signal(signal.SIGINT, _exit_on_signal)


def _reap_orphans() -> None:
    try:
        _registry().reap_orphans()
    except Exception as exc:  # noqa: BLE001 - startup must not fail on cleanup
        logger.warning("orphan reaping skipped: %s", type(exc).__name__)


def _stop_processes() -> None:
    if _REGISTRY is not None:
        _REGISTRY.stop_all()


def main() -> None:
    _configure_logging()
    _install_signal_handlers()
    logger.info("Starting Solus code MCP server")
    _reap_orphans()
    try:
        build_server().run(transport="stdio")
    finally:
        # stdin EOF, SIGTERM or SIGINT: every started process is stopped.
        _stop_processes()


if __name__ == "__main__":
    main()
