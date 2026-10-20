"""SOLUSDEV-317 — interactive processes (docs/api/code-command-execution.md §11.1):
PTY attach, REPL refusal, `awaiting_input` / `prompt_seq` / `prompt_tail`, the gated
`process_input` tool, and master-fd cleanup. Registry tests use a real pseudo-terminal
with a fake child and an injected clock; the `real_sandbox` tests run real programs
through the macOS sandbox over the MCP wire. HOME is always a temp dir."""

import asyncio
import os
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

processes = overlay_module("processes")
process_os = overlay_module("process_os")
plan = overlay_module("plan")
execute = overlay_module("execute")
server = overlay_module("server")
roster = overlay_module("roster")
terminal = overlay_module("terminal")
repl_guard = overlay_module("repl_guard")
command_plan = overlay_module("command_plan")

REPL_REASON = "interactive mode needs a script or program, not a REPL or bare shell"


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.stdout = None
        self.stderr = None
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise TimeoutError
        return self.returncode


class PtyWorld:
    """A real pseudo-terminal per start; the test plays the program on the slave."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.next_pid = 700
        self.children: dict[int, FakeChild] = {}
        self.slaves: dict[int, int] = {}
        self.masters: dict[int, int] = {}
        self.plain: list[FakeChild] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def _child(self) -> FakeChild:
        self.next_pid += 1
        child = FakeChild(self.next_pid)
        self.children[child.pid] = child
        return child

    def spawn(self, _argv: list[str], _cwd: Path, _env: dict[str, str]) -> FakeChild:
        child = self._child()
        self.plain.append(child)
        return child

    def pty_spawn(self, _argv: list[str], _cwd: Path, _env: dict[str, str]) -> Any:
        master, slave = os.openpty()
        os.set_blocking(master, False)
        child = self._child()
        self.slaves[child.pid], self.masters[child.pid] = slave, master
        return child, master

    def exit(self, pid: int, code: int = 0) -> None:
        """The program exits: its end of the terminal closes."""
        self.children[pid].returncode = code
        slave = self.slaves.pop(pid, None)
        if slave is not None:
            os.close(slave)

    def killpg(self, pgid: int, sig: int) -> None:
        child = self.children.get(pgid)
        if child is not None and child.returncode is None:
            self.exit(pgid, -sig)

    def close(self) -> None:
        for slave in self.slaves.values():
            os.close(slave)
        self.slaves.clear()


class NoTracker:
    def __init__(self, _leader: int) -> None:
        pass

    def observe(self, force: bool = False) -> None:
        pass

    def kill(self, _sig: int) -> None:
        pass


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def world() -> Iterator[PtyWorld]:
    made = PtyWorld()
    yield made
    made.close()


def _registry(ws: Path, world: PtyWorld) -> Any:
    return processes.Registry(
        ws,
        spawn=world.spawn,
        pty_spawn=world.pty_spawn,
        clock=world.clock,
        sleep=world.sleep,
        killpg=world.killpg,
        start_token=lambda pid: f"token-{pid}",
        tracker=NoTracker,
        watch=False,
        git_digest=lambda _root: "same",
    )


def _start(registry: Any, interactive: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = registry.start(
        ["/usr/bin/sandbox-exec", "...", "./servo.sh"],
        display_argv=["./servo.sh"],
        cwd=Path("/w"),
        cwd_label=".",
        env={"PATH": "/usr/bin"},
        name="servo",
        max_runtime_seconds=3600,
        sandbox="sandbox-exec",
        interactive=interactive,
    )
    return result


def _entry(registry: Any) -> dict[str, Any]:
    (entry,) = registry.status()["processes"]
    return dict(entry)


def _until(condition: Callable[[], bool], seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.02)


def _seen(registry: Any, text: str) -> Callable[[], bool]:
    return lambda: text in _entry(registry)["prompt_tail"]


def test_non_interactive_entries_report_no_terminal(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    started = _start(registry, interactive=False)
    assert started["ok"] is True and world.plain and not world.masters
    entry = _entry(registry)
    assert entry["interactive"] is False and entry["awaiting_input"] is False
    assert entry["prompt_seq"] == 0 and entry["prompt_tail"] is None
    refused = registry.input(started["process_id"], "y", enter=True)
    assert refused == {
        "ok": False,
        "process_id": started["process_id"],
        "sent_chars": 0,
        "reason": "process is not interactive",
    }


def test_awaiting_input_after_quiet_pending_prompt(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    slave = world.slaves[started["pid"]]
    os.write(slave, b"booting\n\x1b[1mPlug in the servo, then press Enter \x1b[0m")
    _until(_seen(registry, "press Enter"))
    entry = _entry(registry)
    assert entry["interactive"] is True and entry["awaiting_input"] is False
    world.now += 1.4
    assert _entry(registry)["awaiting_input"] is False
    world.now += 0.1
    entry = _entry(registry)
    assert entry["awaiting_input"] is True and entry["prompt_seq"] == 1
    assert entry["prompt_tail"] == "booting\nPlug in the servo, then press Enter "
    world.now += 5
    assert _entry(registry)["prompt_seq"] == 1  # the same prompt is counted once


def test_output_clears_awaiting_and_a_new_prompt_counts_again(
    ws: Path, home: Path, world: PtyWorld
) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    slave = world.slaves[started["pid"]]
    os.write(slave, b"Overwrite? [y/N]\n")
    _until(_seen(registry, "Overwrite?"))
    world.now += 2
    assert _entry(registry)["awaiting_input"] is True
    os.write(slave, b"still working\n")
    _until(_seen(registry, "still working"))
    entry = _entry(registry)
    assert entry["awaiting_input"] is False and entry["prompt_seq"] == 1
    world.now += 2
    assert _entry(registry)["awaiting_input"] is False  # "still working" is no prompt
    os.write(slave, b"Name: ")
    _until(_seen(registry, "Name:"))
    world.now += 2
    entry = _entry(registry)
    assert entry["awaiting_input"] is True and entry["prompt_seq"] == 2


def test_process_input_reaches_the_program_and_clears_the_prompt(
    ws: Path, home: Path, world: PtyWorld
) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    slave = world.slaves[started["pid"]]
    os.write(slave, b"Name: ")
    _until(_seen(registry, "Name:"))
    world.now += 2
    assert _entry(registry)["awaiting_input"] is True
    sent = registry.input(started["process_id"], "bob", enter=True)
    assert sent == {
        "ok": True,
        "process_id": started["process_id"],
        "sent_chars": 4,
        "reason": None,
    }
    assert os.read(slave, 64) == b"bob\n"
    assert _entry(registry)["awaiting_input"] is False
    _until(lambda: "Name: bob\n" in _chunks(registry, started["process_id"]))
    world.now += 5
    entry = _entry(registry)
    assert entry["awaiting_input"] is False and entry["prompt_seq"] == 1


def test_bare_enter_and_text_without_enter(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    slave = world.slaves[started["pid"]]
    assert registry.input(started["process_id"], "", enter=True)["sent_chars"] == 1
    assert os.read(slave, 64) == b"\n"
    partial = registry.input(started["process_id"], "ab", enter=False)
    assert partial["ok"] is True and partial["sent_chars"] == 2
    nothing = registry.input(started["process_id"], "", enter=False)
    assert nothing["ok"] is False and nothing["reason"] == "nothing to send"


def _chunks(registry: Any, process_id: str) -> str:
    output = registry.status(process_id=process_id)["output"]
    return "".join(chunk["text"] for chunk in output["chunks"])


@pytest.mark.parametrize("text", ["a\nb", "\x1b[A", "\x03", "\t", "x" * 1025])
def test_process_input_refuses_control_and_oversized_text(
    ws: Path, home: Path, world: PtyWorld, text: str
) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    refused = registry.input(started["process_id"], text, enter=True)
    assert refused["ok"] is False and refused["sent_chars"] == 0
    assert refused["reason"] == terminal.INPUT_REFUSAL


def test_process_input_refuses_unknown_and_finished(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    assert registry.input("nope", "y", enter=True)["reason"] == "unknown process"
    started = _start(registry)
    world.exit(started["pid"])
    refused = registry.input(started["process_id"], "y", enter=True)
    assert refused["ok"] is False and refused["reason"] == "process is not running"
    assert _entry(registry)["awaiting_input"] is False


def _closed(fd: int, before: os.stat_result) -> bool:
    try:
        after = os.fstat(fd)
    except OSError:
        return True
    return (after.st_dev, after.st_ino, after.st_rdev) != (
        before.st_dev,
        before.st_ino,
        before.st_rdev,
    )


def test_stop_closes_the_master(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    master = world.masters[started["pid"]]
    before = os.fstat(master)
    stopped = registry.stop(started["process_id"])
    assert stopped["state"] == "stopped"
    assert _closed(master, before)
    refused = registry.input(started["process_id"], "y", enter=True)
    assert refused["reason"] == "process is not running"


def test_exit_and_stop_all_close_the_master(ws: Path, home: Path, world: PtyWorld) -> None:
    registry = _registry(ws, world)
    first, second = _start(registry), _start(registry)
    masters = [world.masters[first["pid"]], world.masters[second["pid"]]]
    stats = [os.fstat(fd) for fd in masters]
    world.exit(first["pid"])
    registry.sweep()
    registry.stop_all()
    assert all(_closed(fd, stat) for fd, stat in zip(masters, stats, strict=True))


def test_stop_closes_the_master_even_when_a_descendant_keeps_the_terminal(
    ws: Path, home: Path, world: PtyWorld
) -> None:
    registry = _registry(ws, world)
    started = _start(registry)
    master = world.masters[started["pid"]]
    before = os.fstat(master)
    held = os.dup(world.slaves[started["pid"]])  # a grandchild still holds the slave
    try:
        registry.stop(started["process_id"])
        assert _closed(master, before)
    finally:
        os.close(held)


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/dev/fd") if name.isdigit()}


def test_default_pty_spawn_attaches_a_terminal_with_a_window(tmp_path: Path) -> None:
    program = (
        "import os, sys; "
        "print(os.isatty(0), os.isatty(1), os.isatty(2), os.get_terminal_size(0), flush=True)"
    )
    child, master = process_os.default_pty_spawn(
        [sys.executable, "-c", program], tmp_path, {"PATH": "/usr/bin:/bin"}
    )
    received = b""
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and b"\n" not in received:
            try:
                received += os.read(master, 4096)
            except BlockingIOError:
                time.sleep(0.02)
            except OSError:
                break
        child.wait(timeout=10)
    finally:
        os.close(master)
    assert b"True True True os.terminal_size(columns=120, lines=24)" in received


def test_default_pty_spawn_failure_leaks_no_descriptors(tmp_path: Path) -> None:
    before = _open_fds()
    with pytest.raises(OSError):
        process_os.default_pty_spawn([str(tmp_path / "missing")], tmp_path, {})
    assert _open_fds() == before


# --- planning -------------------------------------------------------------------------


@pytest.fixture
def plan_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "pws").resolve()
    root.mkdir()
    (tmp_path / "home2").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home2"))
    bins = tmp_path / "roots" / "bin"
    bins.mkdir(parents=True)
    for name in (*INTERPRETERS, *REPL_PROGRAMS, "make", "bash"):
        (bins / name).write_text("#!/bin/sh\n")
        (bins / name).chmod(0o755)
    monkeypatch.setattr(execute, "SEARCH_ROOTS", (str(bins),))
    for script in ("go.sh", "ask.py", "app.js", "x.pl", "x.rb", "x.lua", "x.ts", "x.jl", "x.tcl"):
        (root / script).write_text("\n")
    (root / "sub").mkdir()
    return root


INTERPRETERS = (
    "python3.12",
    "python3",
    "pypy3",
    "node",
    "perl",
    "ruby",
    "lua",
    "php",
    "bun",
    "deno",
)
REPL_PROGRAMS = (
    "ipython",
    "ipython3",
    "sqlite3",
    "psql",
    "gdb",
    "R",
    "julia",
    "tclsh8.6",
    "irb",
    "less",
    "more",
    "most",
    "man",
    "vi",
    "vim",
    "nvim",
    "view",
    "ex",
    "ed",
    "emacs",
    "ftp",
    "telnet",
    "ssh",
    "nc",
    "ncat",
    "socat",
    "screen",
    "tmux",
    "script",
    "expect",
)
STDIN_MODULES = (
    "cProfile",
    "profile",
    "trace",
    "runpy",
    "timeit",
    "pdb",
    "code",
    "xonsh",
    "sqlite3",
    "jupyter",
    "jupyter_console",
    "ptipython",
    "bpdb",
    "web_pdb",
    "rpdb",
    "remote_pdb",
    "IPython",
    "ipykernel",
)


def _guard(root: Path, argv: list[str]) -> str | None:
    """The REPL guard alone, with the workspace's script check."""
    reason: str | None = repl_guard.repl_reason(
        argv, script_file=lambda script: command_plan._script_file(root, ".", script)
    )
    return reason


def _plan(root: Path, argv: list[str], interactive: object = True) -> Any:
    args = {"argv": argv, "interactive": interactive}
    return plan.plan_action(root, "process_start", args, which=lambda _name: None)


@pytest.mark.parametrize(
    "argv",
    [
        ["python3.12"],
        ["python3.12", "-u"],
        ["python3.12", "-W", "ignore"],
        ["python3.12", "-"],
        ["python3.12", "--"],
        ["node"],
        ["node", "-r", "dotenv/config"],
        ["node", "-r", "x"],
        ["perl", "-mFoo"],
        ["perl", "-MFoo"],
        ["perl", "-m", "Foo"],
        ["perl", "-m"],
        ["ruby", "-rfoo"],
        ["ruby", "-m"],
        ["python3.12", "-i", "ask.py"],
        ["python3.12", "-ui", "ask.py"],
        ["python3.12", "-m", "code"],
        ["python3.12", "-m", "pdb", "ask.py"],
        ["python3.12", "-masyncio"],
        ["python3.12", "-m", "IPython"],
        ["python3.12", "-m", "idlelib.idle"],
        ["python3.12", "--frobnicate", "ask.py"],
        ["python3.12", "-Z", "ask.py"],
        ["pypy3", "-m", "pdb"],
        ["node", "-i"],
        ["node", "--interactive", "app.js"],
        ["node", "inspect", "app.js"],
        ["node", "--frobnicate", "app.js"],
        ["perl", "-d", "x.pl"],
        ["lua", "-i", "x.lua"],
        ["php", "-a"],
        ["bun", "repl"],
        *([name] for name in REPL_PROGRAMS),
        ["ipython3", "ask.py"],
        ["sqlite3", "db.sqlite"],
        ["gdb", "./a.out"],
        ["julia", "x.jl"],
        ["tclsh8.6", "x.tcl"],
        ["less", "ask.py"],
        ["vim", "ask.py"],
        ["ssh", "host"],
        ["python3.12", "missing.py"],
        ["python3.12", "/etc/hosts"],
        ["python3.12", "sub"],
        ["python3.12", "/dev/stdin"],
        ["python3.12", "--", "missing.py"],
        ["node", "missing.js"],
        ["perl", "../escape.pl"],
        *(["python3.12", "-m", module, "ask.py"] for module in STDIN_MODULES),
        ["python3.12", "-m", "cProfile.x"],
        ["make", "-f", "-"],
        ["make", "-f", "/dev/stdin"],
        ["make", "--file=/dev/fd/0"],
        ["make", "-f", "/proc/self/fd/0"],
        ["make", "-f", "/proc/123/fd/0"],
        ["make", "-f", "//dev/./stdin"],
        ["deno", "run", "-"],
        ["deno", "run", "/dev/stdin"],
        ["deno", "run", "/dev/fd/0"],
        ["deno", "run", "/dev/tty"],
        ["deno", "run", "missing.ts"],
        ["deno", "run", "--allow-net", "missing.ts"],
    ],
)
def test_interactive_refuses_a_repl(plan_ws: Path, argv: list[str]) -> None:
    refused = _plan(plan_ws, argv)
    # Some are already refused by the deny table (unknown leading option); the REPL
    # guard refuses every one of them on its own as well.
    assert refused.ok is False and _guard(plan_ws, argv) == REPL_REASON
    assert refused.answer()["interactive"] is True


@pytest.mark.parametrize(
    "argv",
    [
        ["python3.12", "ask.py"],
        ["python3.12", "-u", "ask.py"],
        ["python3.12", "-m", "serial.tools.miniterm"],
        ["python3.12", "-um", "tool"],
        ["python3", "-m", "mypkg"],
        ["pypy3", "-m", "mypkg"],
        ["perl", "x.pl"],
        ["perl", "-MFoo", "x.pl"],
        ["ruby", "-rfoo", "x.rb"],
        ["python3.12", "-m", "http.server"],
        ["node", "--watch", "app.js"],
        ["lua", "x.lua"],
        ["deno", "run", "x.ts"],
        ["deno", "run", "--allow-net", "x.ts"],
        ["python3.12", "./ask.py"],
        ["node", "app.js"],
        ["make", "flash"],
        ["make"],
        ["bash", "go.sh"],
    ],
)
def test_interactive_allows_scripts_modules_and_programs(plan_ws: Path, argv: list[str]) -> None:
    accepted = _plan(plan_ws, argv)
    assert accepted.ok, accepted.reason
    assert accepted.interactive is True and accepted.answer()["interactive"] is True


def test_non_interactive_plan_is_unchanged(plan_ws: Path) -> None:
    accepted = _plan(plan_ws, ["python3.12"], interactive=False)
    assert accepted.ok and accepted.interactive is False
    assert accepted.answer()["interactive"] is False
    default = plan.plan_action(
        plan_ws, "process_start", {"argv": ["make"]}, which=lambda _name: None
    )
    assert default.interactive is False
    assert (
        "interactive"
        not in plan.plan_action(
            plan_ws, "exec", {"argv": ["make"]}, which=lambda _name: None
        ).answer()
    )


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_interactive_must_be_a_boolean(plan_ws: Path, value: object) -> None:
    result = _plan(plan_ws, ["make"], interactive=value)
    if value is None:
        assert result.ok and result.interactive is False
    else:
        assert result.ok is False and result.reason == "interactive must be true or false"


def test_interactive_child_env_is_a_dumb_terminal(plan_ws: Path) -> None:
    interactive = _plan(plan_ws, ["make"])
    assert execute.child_env(plan_ws, interactive)["TERM"] == "dumb"
    quiet = _plan(plan_ws, ["make"], interactive=False)
    assert execute.child_env(plan_ws, quiet).get("TERM") != "dumb"


# --- the MCP surface ------------------------------------------------------------------


@pytest.fixture
def wire_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "ws"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(server, "_REGISTRY", None)
    yield root.resolve()
    if server._REGISTRY is not None:
        server._REGISTRY.stop_all()


async def test_process_input_is_registered_strict_and_gated() -> None:
    tools = {tool.name: tool for tool in await server.build_server().list_tools()}
    schema = tools["process_input"].inputSchema
    assert set(schema["required"]) == {"process_id", "text"}
    assert schema["properties"]["enter"]["default"] is True
    assert schema["properties"]["text"]["maxLength"] == 1024
    assert "interactive" in tools["process_start"].inputSchema["properties"]
    assert "process_input" in roster.GATED_TOOLS


@pytest.mark.parametrize(
    "arguments",
    [
        {"process_id": "x", "text": "y", "force": True},
        {"process_id": "x", "text": "y", "enter": "yes"},
        {"process_id": "x", "text": "y" * 1025},
        {"process_id": "x"},
    ],
)
async def test_process_input_schema_refusals(wire_ws: Path, arguments: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        await server.build_server().call_tool("process_input", arguments)


async def test_process_input_for_an_unknown_process(wire_ws: Path) -> None:
    _content, result = await server.build_server().call_tool(
        "process_input", {"process_id": "nope", "text": ""}
    )
    assert result == {
        "ok": False,
        "process_id": "nope",
        "sent_chars": 0,
        "reason": "unknown process",
    }


def test_process_input_never_raises(wire_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("on fire")

    monkeypatch.setattr(server, "_registry", boom)
    result = server.tool_process_input("x" * 99, "y")
    assert result == {
        "ok": False,
        "process_id": "x" * 64,
        "sent_chars": 0,
        "reason": "process_input failed",
    }


async def test_interactive_python_without_a_script_is_refused_over_the_wire(
    wire_ws: Path,
) -> None:
    _content, result = await server.build_server().call_tool(
        "process_start", {"argv": ["python3"], "interactive": True}
    )
    assert result["ok"] is False and result["reason"] == REPL_REASON


# --- real programs in the macOS sandbox -----------------------------------------------

REAL_SANDBOX = pytest.mark.real_sandbox
MACOS_ONLY = pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox-exec")


def _script(root: Path, name: str, body: str) -> None:
    path = root / name
    path.write_text(body)
    path.chmod(0o755)


async def _poll(
    built: Any, process_id: str, done: Callable[[dict[str, Any], str], bool], seconds: float = 15
) -> tuple[dict[str, Any], str, bool]:
    """Poll status until `done(entry, all_output)`; also whether awaiting was ever seen."""
    deadline = time.monotonic() + seconds
    text, ever_awaiting = "", False
    while True:
        _content, status = await built.call_tool(
            "process_status", {"process_id": process_id, "cursor": 0}
        )
        entry = next(p for p in status["processes"] if p["process_id"] == process_id)
        text = "".join(chunk["text"] for chunk in status["output"]["chunks"])
        ever_awaiting = ever_awaiting or entry["awaiting_input"]
        if done(entry, text):
            return entry, text, ever_awaiting
        if time.monotonic() > deadline:
            raise AssertionError(f"not reached: {entry} {text!r}")
        await asyncio.sleep(0.1)


async def _start_real(built: Any, argv: list[str]) -> str:
    _content, started = await built.call_tool(
        "process_start", {"argv": argv, "interactive": True, "max_runtime_seconds": 60}
    )
    assert started["ok"] is True, started
    process_id: str = started["process_id"]
    return process_id


@REAL_SANDBOX
@MACOS_ONLY
async def test_real_read_prompt_waits_and_enter_continues(wire_ws: Path) -> None:
    _script(
        wire_ws,
        "servo.sh",
        '#!/bin/bash\nread -p "Plug in the servo, then press Enter " x\necho got:$x\n',
    )
    built = server.build_server()
    process_id = await _start_real(built, ["./servo.sh"])
    entry, _text, _ = await _poll(built, process_id, lambda e, _t: e["awaiting_input"])
    assert "Plug in the servo, then press Enter" in entry["prompt_tail"]
    assert entry["prompt_seq"] == 1 and entry["interactive"] is True
    _content, sent = await built.call_tool(
        "process_input", {"process_id": process_id, "text": "", "enter": True}
    )
    assert sent == {"ok": True, "process_id": process_id, "sent_chars": 1, "reason": None}
    entry, text, _ = await _poll(built, process_id, lambda e, t: "got:" in t)
    assert "\x1b" not in text and "\r" not in text


@REAL_SANDBOX
@MACOS_ONLY
async def test_real_yes_no_prompt_gets_its_answer(wire_ws: Path) -> None:
    _script(wire_ws, "ask.sh", '#!/bin/bash\nread -p "Overwrite? [y/N] " a\necho answer:$a\n')
    built = server.build_server()
    process_id = await _start_real(built, ["./ask.sh"])
    entry, _text, _ = await _poll(built, process_id, lambda e, _t: e["awaiting_input"])
    assert "[y/N]" in entry["prompt_tail"]
    _content, sent = await built.call_tool("process_input", {"process_id": process_id, "text": "y"})
    assert sent["ok"] is True and sent["sent_chars"] == 2
    await _poll(built, process_id, lambda e, t: "answer:y" in t)


@REAL_SANDBOX
@MACOS_ONLY
async def test_real_program_that_prints_and_exits_never_awaits(wire_ws: Path) -> None:
    _script(wire_ws, "hello.sh", "#!/bin/bash\necho hello\n")
    built = server.build_server()
    process_id = await _start_real(built, ["./hello.sh"])
    entry, text, ever = await _poll(built, process_id, lambda e, _t: e["state"] != "running")
    await asyncio.sleep(1.6)
    _entry_after, _t, ever_after = await _poll(built, process_id, lambda e, _t: True)
    assert entry["state"] == "exited" and "hello" in text
    assert not ever and not ever_after and _entry_after["awaiting_input"] is False


@REAL_SANDBOX
@MACOS_ONLY
async def test_real_python_input_under_the_terminal(wire_ws: Path) -> None:
    (wire_ws / "ask.py").write_text('name = input("Your name: ")\nprint("hi", name)\n')
    built = server.build_server()
    process_id = await _start_real(built, ["python3", "ask.py"])
    entry, _text, _ = await _poll(built, process_id, lambda e, _t: e["awaiting_input"])
    assert entry["prompt_tail"].endswith("Your name: ")
    await built.call_tool("process_input", {"process_id": process_id, "text": "Ada"})
    await _poll(built, process_id, lambda e, t: "hi Ada" in t)


@REAL_SANDBOX
@MACOS_ONLY
async def test_real_stop_and_shutdown_close_the_terminal(wire_ws: Path) -> None:
    _script(wire_ws, "wait.sh", '#!/bin/bash\nread -p "Press Enter to finish " x\n')
    built = server.build_server()
    first = await _start_real(built, ["./wait.sh"])
    second = await _start_real(built, ["./wait.sh"])
    await _poll(built, first, lambda e, _t: e["awaiting_input"])
    registry = server._REGISTRY
    assert registry is not None
    entries = [registry._entries[first], registry._entries[second]]
    masters = [(entry.master_fd, os.fstat(entry.master_fd)) for entry in entries]
    pids = [entry.pid for entry in entries]
    _content, stopped = await built.call_tool("process_stop", {"process_id": first})
    assert stopped["state"] == "stopped"
    assert _closed(*masters[0]) and entries[0].master_fd is None
    registry.stop_all()
    assert _closed(*masters[1]) and entries[1].master_fd is None
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.parametrize(
    "argv",
    [
        ["bash"],
        ["bash", "-i", "go.sh"],
        ["sh", "-s", "go.sh"],
        ["bash", "--rcfile", "x", "go.sh"],
        ["bash", "-o", "vi", "go.sh"],
        ["bash", "+o", "posix", "go.sh"],
        ["deno"],
        ["deno", "repl"],
        ["deno", "--frobnicate", "run", "x.ts"],
    ],
)
def test_repl_guard_refuses_shell_options_and_bare_deno(argv: list[str]) -> None:
    assert repl_guard.repl_reason(argv, script_file=lambda _script: True) == REPL_REASON


@pytest.mark.parametrize("argv", [["bash", "go.sh", "-i"], ["deno", "run", "x.ts"], ["make"]])
def test_repl_guard_allows_scripts(argv: list[str]) -> None:
    assert repl_guard.repl_reason(argv, script_file=lambda _script: True) is None


@pytest.mark.parametrize("argv", [["bash", "go.sh"], ["deno", "run", "x.ts"], ["python3", "a.py"]])
def test_repl_guard_without_a_script_check_fails_closed(argv: list[str]) -> None:
    assert repl_guard.repl_reason(argv) == REPL_REASON
