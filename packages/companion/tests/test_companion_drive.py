"""The ADR-041 `drive` builtin (docs/architecture/sol-drive.md §3): relays each
command to the desktop over stdout/stdin (slice 3b, XPC — the desktop reaches
the agent), validates what comes back, stages captures as artifacts, and
advertises nothing unless switched on.

The desktop here (`FakeDesktop`) runs a real stand-in script per request and
answers through the real stdin routing, so the relay path (ids, one deadline,
drive_cancel, the reply cap) is exercised for real.
"""

import asyncio
import base64
import contextlib
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from solus_companion.__main__ import build_builtins
from solus_companion.artifacts import ArtifactStore
from solus_companion.config import TokenBox, apply_token_line
from solus_companion.dispatch import Dispatcher
from solus_companion.drive.helper import DriveHelperError, DriveRelay
from solus_companion.drive.server import TOOL_NAMES, DriveServer, drive_server_from_env
from solus_companion.frames import ArtifactFetchIn, ToolCallIn
from solus_companion.supervisor import Supervisor
from solus_companion.watch import saved_design_fingerprint

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
OK_IDENTIFY = {"ok": True, "app": {"bundleId": "org.kicad.kicad"}, "allowed": True}


def make_helper(tmp_path: Path, body: str) -> Path:
    """An executable stand-in for solus-input. `argv` is the list it received;
    it records every invocation in `calls.jsonl` beside itself."""
    script = tmp_path / "solus-input"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time, pathlib\n"
        "argv = sys.argv[1:]\n"
        "log = pathlib.Path(__file__).with_name('calls.jsonl')\n"
        "with log.open('a') as f: f.write(json.dumps(argv) + '\\n')\n" + body,
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class FakeDesktop:
    """Solus.app main as the companion sees it: it reads `drive_request` lines off
    the companion's stdout, runs the stand-in `script` with the request argv (in
    place of the XPC agent), and answers with a `drive_reply` line through the
    real stdin routing (`apply_token_line`). `drive_cancel` terminates the script."""

    def __init__(self, script: Path) -> None:
        self.script = script
        self.lines: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.procs: dict[int, asyncio.subprocess.Process] = {}
        self.box = TokenBox()
        self.tasks: set[asyncio.Task[None]] = set()

    def emit(self, line: str) -> None:
        self.lines.append(line)
        message = json.loads(line)
        if message["type"] == "drive_request":
            self.requests.append(message)
            task = asyncio.get_running_loop().create_task(self._serve(message))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        elif message["type"] == "drive_cancel":
            proc = self.procs.get(message["id"])
            if proc is not None and proc.returncode is None:
                proc.terminate()

    async def _serve(self, message: dict[str, Any]) -> None:
        proc = await asyncio.create_subprocess_exec(
            str(self.script), *message["argv"], stdout=asyncio.subprocess.PIPE
        )
        self.procs[message["id"]] = proc
        out, _ = await proc.communicate()
        try:
            reply: Any = json.loads(out)
        except ValueError:
            reply = out.decode(errors="replace")  # garbage still reaches the companion
        line = json.dumps({"type": "drive_reply", "id": message["id"], "reply": reply})
        apply_token_line(self.box, line.encode())

    def stop(self) -> None:
        for proc in self.procs.values():
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        for task in self.tasks:
            task.cancel()


_DESKTOPS: list[FakeDesktop] = []


@pytest.fixture(autouse=True)
def _stop_desktops() -> Iterator[None]:
    yield
    while _DESKTOPS:
        _DESKTOPS.pop().stop()


def desktop_for(script: Path) -> FakeDesktop:
    desktop = FakeDesktop(script)
    _DESKTOPS.append(desktop)
    return desktop


def desktop_relay(script: Path, **kwargs: Any) -> DriveRelay:
    """A DriveRelay whose stdout goes to a fake desktop running `script`."""
    desktop = desktop_for(script)
    relay = DriveRelay(desktop.emit, attached=True, **kwargs)
    desktop.box.drive_relay = relay
    return relay


def gone(pid: int) -> bool:
    """The desktop stops the script a moment after the companion cancels."""
    for _ in range(200):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


def calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def echo_helper(tmp_path: Path, reply: dict[str, Any]) -> Path:
    return make_helper(tmp_path, f"print(json.dumps({reply!r}))\n")


def workspace_of(helper: Path) -> Path:
    """The linked project folder beside the stand-in helper (never inside it)."""
    ws = helper.parent / "ws"
    ws.mkdir(exist_ok=True)
    return ws


def server_with(path: Path, *, bound: bool = True, **kwargs: Any) -> DriveServer:
    """`bound`: as after the step's identify — the saved-design baseline is taken."""
    server = DriveServer(
        desktop_relay(path, **kwargs),
        enabled=True,
        workspace=workspace_of(path),
        platform="darwin",
    )
    if bound:
        server._designs_at_bind = saved_design_fingerprint(server.workspace)
    return server


def within(tmp_path: Path) -> list[str]:
    return ["--within", str((tmp_path / "ws").resolve())]


def text_of(result: CallToolResult) -> str:
    return " ".join(b.text for b in result.content if isinstance(b, TextContent))


# --- the pinned path -----------------------------------------------------------


def test_from_env_needs_the_switch_macos_and_a_workspace(tmp_path: Path) -> None:
    on = {"SOLUS_COMPANION_DRIVE": "1"}
    assert drive_server_from_env(on, workspace=tmp_path, platform="darwin").inventory() is not None
    assert drive_server_from_env(on, workspace=None, platform="darwin").inventory() is None
    assert (
        drive_server_from_env(
            {"SOLUS_COMPANION_DRIVE": "true"}, workspace=tmp_path, platform="darwin"
        ).inventory()
        is None
    )
    assert drive_server_from_env({}, workspace=tmp_path, platform="darwin").inventory() is None
    assert drive_server_from_env(on, workspace=tmp_path, platform="linux").inventory() is None


def test_from_env_ignores_the_retired_helper_path(tmp_path: Path) -> None:
    env = {"SOLUS_COMPANION_DRIVE": "1", "SOLUS_DRIVE_HELPER": "/nowhere/solus-input"}
    assert drive_server_from_env(env, workspace=tmp_path, platform="darwin").inventory() is not None


# --- advertising -----------------------------------------------------------------


def test_off_advertises_nothing_says_why_and_fails_closed(tmp_path: Path) -> None:
    helper = DriveRelay(lambda _: None)
    for server, detail in [
        (
            DriveServer(helper, enabled=False, workspace=tmp_path, platform="darwin"),
            "SOL can't use your mouse and keyboard (off)",
        ),
        (
            DriveServer(None, enabled=True, workspace=tmp_path, platform="darwin"),
            "the input helper is missing",
        ),
        (
            DriveServer(helper, enabled=True, workspace=tmp_path, platform="win32"),
            "driving apps needs macOS",
        ),
        (
            DriveServer(helper, enabled=True, workspace=None, platform="darwin"),
            "no project workspace is linked",
        ),
    ]:
        assert server.inventory() is None
        entry = server.status_entry()
        assert entry["name"] == "drive"
        assert entry["state"] == "not_launched"
        assert entry["detail"] == detail


async def test_off_server_refuses_calls_without_running_the_helper(tmp_path: Path) -> None:
    server = DriveServer(
        desktop_relay(echo_helper(tmp_path, OK_IDENTIFY)),
        enabled=False,
        workspace=tmp_path,
        platform="darwin",
    )
    result = await server.call_tool("identify", {})
    assert result.isError
    assert calls(tmp_path) == []


def test_on_advertises_exactly_the_three_tools_with_strict_schemas(tmp_path: Path) -> None:
    inventory = server_with(echo_helper(tmp_path, OK_IDENTIFY)).inventory()
    assert inventory is not None
    assert inventory["server"] == "drive"
    assert (
        {tool["name"] for tool in inventory["tools"]}
        == TOOL_NAMES
        == {"identify", "capture", "act"}
    )
    for tool in inventory["tools"]:
        assert tool["input_schema"].get("additionalProperties") is False


# --- identify / act ----------------------------------------------------------------


async def test_identify_runs_the_helper_and_returns_its_json(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, OK_IDENTIFY))
    result = await server.call_tool("identify", {})
    assert not result.isError
    assert result.structuredContent == OK_IDENTIFY
    assert calls(tmp_path) == [["identify", *within(tmp_path)]]


async def test_act_builds_the_argument_list_in_a_fixed_order(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True, "verb": "click", "idleSeconds": 9}))
    args = {
        "bundle": "org.kicad.kicad",
        "window": 7,
        "since": 990.5,
        "verb": "click",
        "y": 20,
        "x": 10,
    }
    result = await server.call_tool("act", args)
    assert not result.isError
    assert calls(tmp_path) == [
        [
            "act",
            *within(tmp_path),
            "--bundle",
            "org.kicad.kicad",
            "--window",
            "7",
            "--since",
            "990.5",
            "click",
            "--x",
            "10",
            "--y",
            "20",
        ]
    ]


async def test_typed_text_is_one_argument_never_a_shell_string(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    hostile = '$(touch pwned); "; rm -rf ~ `id`'
    await server.call_tool(
        "act",
        {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "type", "text": hostile},
    )
    assert calls(tmp_path)[0][-2:] == ["--text", hostile]
    assert not (tmp_path / "pwned").exists()


async def test_a_helper_refusal_reads_code_colon_message(tmp_path: Path) -> None:
    refusal = {"ok": False, "code": "chord_denied", "message": "that shortcut is not allowed"}
    server = server_with(echo_helper(tmp_path, refusal))
    result = await server.call_tool(
        "act",
        {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "key", "chord": "cmd+q"},
    )
    assert result.isError
    assert text_of(result) == "chord_denied: that shortcut is not allowed"


@pytest.mark.parametrize(
    "args",
    [
        {
            "bundle": "org.kicad.kicad",
            "window": 7,
            "since": 1.0,
            "verb": "click",
            "x": 1,
            "y": 1,
            "extra": 1,
        },
        {"bundle": "org.kicad.kicad", "window": "7", "since": 1.0, "verb": "click", "x": 1, "y": 1},
        {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "launch"},
        {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "type", "text": "a" * 201},
        {"bundle": "org kicad; rm", "window": 7, "since": 1.0, "verb": "wait", "ms": 1},
        {"bundle": "org.kicad.kicad", "window": -1, "since": 1.0, "verb": "wait", "ms": 1},
        {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "wait", "ms": 2001},
    ],
)
async def test_invalid_arguments_never_reach_the_helper(
    tmp_path: Path, args: dict[str, Any]
) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    result = await server.call_tool("act", args)
    assert result.isError
    assert text_of(result).startswith("invalid_arguments: ")
    assert calls(tmp_path) == []


async def test_unknown_tool_is_an_error(tmp_path: Path) -> None:
    result = await server_with(echo_helper(tmp_path, {"ok": True})).call_tool("launch", {})
    assert result.isError


# --- capture -----------------------------------------------------------------------------


def capture_reply(png: str) -> dict[str, Any]:
    return {
        "ok": True,
        "png": png,
        "imageWidth": 1568,
        "imageHeight": 1176,
        "pointsWidth": 800,
        "pointsHeight": 600,
    }


async def test_capture_returns_the_image_as_content_and_metadata_without_the_pixels(
    tmp_path: Path,
) -> None:
    encoded = base64.b64encode(PNG).decode()
    server = server_with(echo_helper(tmp_path, capture_reply(encoded)))
    result = await server.call_tool("capture", {"bundle": "org.kicad.kicad", "window": 7})
    assert not result.isError
    assert result.structuredContent is None  # else dispatch would drop the image block
    image = next(b for b in result.content if isinstance(b, ImageContent))
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == PNG
    meta = json.loads(text_of(result))
    assert meta == {
        "imageWidth": 1568,
        "imageHeight": 1176,
        "pointsWidth": 800,
        "pointsHeight": 600,
        "designSaved": False,
    }
    assert calls(tmp_path) == [
        [
            "capture",
            *within(tmp_path),
            "--bundle",
            "org.kicad.kicad",
            "--window",
            "7",
            "--max-edge",
            "1568",
        ]
    ]


@pytest.mark.parametrize("png", ["not base64!!", base64.b64encode(b"GIF89a....").decode()])
async def test_capture_refuses_anything_that_is_not_a_png(tmp_path: Path, png: str) -> None:
    server = server_with(echo_helper(tmp_path, capture_reply(png)))
    result = await server.call_tool("capture", {"bundle": "org.kicad.kicad", "window": 7})
    assert result.isError
    assert text_of(result).startswith("helper_output: ")


async def test_dispatch_stages_the_capture_as_an_artifact_never_inline(tmp_path: Path) -> None:
    encoded = base64.b64encode(PNG).decode()
    sup = Supervisor((), builtins=(server_with(echo_helper(tmp_path, capture_reply(encoded))),))
    assert [entry["server"] for entry in sup.inventory()] == ["drive"]
    sent: list[dict[str, Any]] = []

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(sup, send)
    dispatcher.handle_tool_call(
        ToolCallIn(
            tool="drive.capture", args={"bundle": "org.kicad.kicad", "window": 7}, call_id="c1"
        )
    )
    await dispatcher.wait_idle()
    blocks = sent[0]["data"]["value"]["content"]
    image = next(b for b in blocks if b["type"] == "image")
    assert image["inlined"] is False
    assert image["media_type"] == "image/png"
    assert "artifact_id" in image
    assert encoded not in json.dumps(sent)


# --- a misbehaving helper --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("print('not json')\n", "helper_output: "),
        ("print('[1, 2]')\n", "helper_output: "),
        ("print(json.dumps({'no_ok': 1}))\n", "helper_output: "),
        ("print('{}'); print('{}')\n", "helper_output: "),
        ("sys.exit(3)\n", "helper_output: "),
        ("sys.stdout.write('x' * (24 * 1024 * 1024 + 4096))\n", "helper_output: "),
    ],
)
async def test_bad_helper_output_is_an_error_not_a_guess(
    tmp_path: Path, body: str, expected: str
) -> None:
    result = await server_with(make_helper(tmp_path, body)).call_tool("identify", {})
    assert result.isError
    assert text_of(result).startswith(expected)


async def test_a_hung_helper_is_killed_at_its_timeout(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    body = f"open({str(pidfile)!r}, 'w').write(str(__import__('os').getpid()))\ntime.sleep(30)\n"
    server = server_with(make_helper(tmp_path, body), timeouts={"identify": 0.5})
    result = await server.call_tool("identify", {})
    assert result.isError
    assert text_of(result).startswith("helper_timeout: ")
    assert gone(int(pidfile.read_text()))


async def test_helper_errors_carry_a_code(tmp_path: Path) -> None:
    with pytest.raises(DriveHelperError) as caught:
        await desktop_relay(make_helper(tmp_path, "sys.exit(1)\n")).run(["identify"], timeout=5)
    assert caught.value.code == "helper_output"


# --- review fixes: cancellation, one deadline, path re-check, one call at a time ------------


async def _wait_for(path: Path) -> None:
    import asyncio

    for _ in range(200):
        if path.exists() and path.read_text():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{path} never appeared")


async def test_a_cancelled_call_kills_the_helper(tmp_path: Path) -> None:
    import asyncio

    pidfile = tmp_path / "pid"
    body = f"open({str(pidfile)!r}, 'w').write(str(__import__('os').getpid()))\ntime.sleep(30)\n"
    server = server_with(make_helper(tmp_path, body))
    task = asyncio.create_task(server.call_tool("identify", {}))
    await _wait_for(pidfile)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gone(int(pidfile.read_text()))


async def test_one_deadline_covers_the_whole_request(tmp_path: Path) -> None:
    import time as clock

    # The agent answers only once the script exits: the call still ends at the timeout.
    body = (
        "import os\nprint(json.dumps({'ok': True}))\n"
        "sys.stdout.flush(); os.close(1)\ntime.sleep(30)\n"
    )
    server = server_with(make_helper(tmp_path, body), timeouts={"identify": 0.6})
    started = clock.monotonic()
    result = await server.call_tool("identify", {})
    assert text_of(result).startswith("helper_timeout: ")
    assert clock.monotonic() - started < 1.0


async def test_calls_run_one_at_a_time_never_interleaved(tmp_path: Path) -> None:
    import asyncio

    log = tmp_path / "spans"
    body = (
        f"open({str(log)!r}, 'a').write('start\\n')\n"
        "time.sleep(0.3)\n"
        f"open({str(log)!r}, 'a').write('end\\n')\n"
        "print(json.dumps({'ok': True}))\n"
    )
    server = server_with(make_helper(tmp_path, body))
    act = {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "wait", "ms": 1}
    await asyncio.gather(server.call_tool("act", act), server.call_tool("act", act))
    assert log.read_text().split() == ["start", "end", "start", "end"]


async def test_an_int_since_is_accepted_and_sent_as_a_float(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    await server.call_tool(
        "act", {"bundle": "org.kicad.kicad", "window": 7, "since": 5, "verb": "wait", "ms": 0}
    )
    assert calls(tmp_path)[0][7:9] == ["--since", "5.0"]


@pytest.mark.parametrize("since", [-1.0, float("nan"), float("inf")])
async def test_since_must_be_a_finite_non_negative_time(tmp_path: Path, since: float) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    result = await server.call_tool(
        "act", {"bundle": "org.kicad.kicad", "window": 7, "since": since, "verb": "wait", "ms": 0}
    )
    assert text_of(result).startswith("invalid_arguments: ")
    assert calls(tmp_path) == []


async def test_a_well_formed_but_undrivable_bundle_is_left_to_the_helper(tmp_path: Path) -> None:
    refusal = {"ok": False, "code": "app_not_allowed", "message": "not a drivable app"}
    server = server_with(echo_helper(tmp_path, refusal))
    result = await server.call_tool("capture", {"bundle": "com.apple.Terminal", "window": 7})
    assert text_of(result) == "app_not_allowed: not a drivable app"


async def test_identify_takes_no_arguments(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, OK_IDENTIFY))
    assert (await server.call_tool("identify", {"x": 1})).isError
    assert calls(tmp_path) == []


def test_capture_max_edge_stays_within_the_output_cap() -> None:
    from solus_companion.drive.helper import STDOUT_CAP_BYTES
    from solus_companion.drive.server import CaptureArgs

    schema = CaptureArgs.model_json_schema()["properties"]["max_edge"]
    assert schema["maximum"] == 2048
    # Worst case: an incompressible RGBA PNG (4 bytes/px) as base64 (x4/3) still fits.
    assert 2048 * 2048 * 4 * 4 // 3 < STDOUT_CAP_BYTES


async def test_a_nul_byte_is_an_argument_error_not_an_exception(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    for field, value in [("text", "a\x00b"), ("chord", "cmd+\x00")]:
        args = {
            "bundle": "org.kicad.kicad",
            "window": 7,
            "since": 1.0,
            "verb": "type",
            field: value,
        }
        result = await server.call_tool("act", args)
        assert text_of(result).startswith("invalid_arguments: ")
    assert calls(tmp_path) == []


async def test_unicode_line_separators_inside_json_strings_still_parse(tmp_path: Path) -> None:
    reply = {"ok": True, "allowed": True, "window": {"title": "board\u2028sheet\u0085x"}}
    server = server_with(
        make_helper(
            tmp_path, f"sys.stdout.write(json.dumps({reply!r}, ensure_ascii=False) + '\\n')\n"
        )
    )
    result = await server.call_tool("identify", {})
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["window"]["title"] == "board\u2028sheet\u0085x"


async def test_act_passes_the_expected_window_size_through(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True}))
    args = {
        "bundle": "org.kicad.kicad",
        "window": 7,
        "since": 1.0,
        "verb": "click",
        "x": 1,
        "y": 40,
        "expect_width": 800,
        "expect_height": 600,
    }
    await server.call_tool("act", args)
    assert calls(tmp_path)[0][-4:] == ["--expect-width", "800", "--expect-height", "600"]


# --- slice 2: captures are fetched once, then gone (ADR-041 §6) ----------------------------


def test_a_fetch_once_artifact_is_served_once_then_dropped() -> None:
    store = ArtifactStore()
    staged = store.stage(PNG, media_type="image/png", fetch_once=True)
    assert (
        b"".join(chunk for chunk, _final in store.chunks(staged.artifact_id, chunk_bytes=8)) == PNG
    )
    assert list(store.chunks(staged.artifact_id, chunk_bytes=8)) == []
    assert store.get(staged.artifact_id) is None
    assert len(store) == 0


def test_ordinary_artifacts_can_still_be_fetched_again() -> None:
    store = ArtifactStore()
    staged = store.stage(PNG, media_type="image/png")
    for _ in range(2):
        assert list(store.chunks(staged.artifact_id, chunk_bytes=1024)) == [(PNG, True)]


async def test_a_drive_capture_can_be_pulled_exactly_once(tmp_path: Path) -> None:
    encoded = base64.b64encode(PNG).decode()
    sup = Supervisor((), builtins=(server_with(echo_helper(tmp_path, capture_reply(encoded))),))
    sent: list[dict[str, Any]] = []

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(sup, send)
    dispatcher.handle_tool_call(
        ToolCallIn(
            tool="drive.capture", args={"bundle": "org.kicad.kicad", "window": 7}, call_id="c1"
        )
    )
    await dispatcher.wait_idle()
    blocks = sent[0]["data"]["value"]["content"]
    artifact_id = next(b for b in blocks if b["type"] == "image")["artifact_id"]

    async def fetch(fetch_id: str) -> dict[str, Any]:
        before = len(sent)
        dispatcher.handle_artifact_fetch(
            ArtifactFetchIn(artifact_id=artifact_id, fetch_id=fetch_id)
        )
        for _ in range(200):
            if len(sent) > before:
                break
            await asyncio.sleep(0.005)
        data: dict[str, Any] = sent[-1]["data"]
        return data

    first = await fetch("f1")
    assert first["final"] is True and not first.get("error")
    second = await fetch("f2")
    assert second["error"] == "unknown artifact"


# --- slice 2: the companion builds drive beside machine ------------------------------------


def test_builtins_include_drive_switched_off_by_default(tmp_path: Path) -> None:
    builtins = build_builtins(None, env={})
    assert [server.name for server in builtins] == ["machine", "drive"]
    assert builtins[1].inventory() is None


def test_builtins_switch_drive_on_from_the_environment(tmp_path: Path) -> None:
    env = {"SOLUS_COMPANION_DRIVE": "1"}
    assert build_builtins(None, env=env, platform="darwin")[1].inventory() is None  # no project
    drive = build_builtins(str(tmp_path), env=env, platform="darwin")[1]
    inventory = drive.inventory()
    assert inventory is not None
    assert {tool["name"] for tool in inventory["tools"]} == set(TOOL_NAMES)


def test_a_fetch_once_artifact_nobody_pulls_expires() -> None:
    now = [0.0]
    store = ArtifactStore(clock=lambda: now[0])
    staged = store.stage(PNG, media_type="image/png", fetch_once=True)
    kept = store.stage(PNG, media_type="image/png")
    now[0] = 61.0
    assert store.get(staged.artifact_id) is None
    assert store.get(kept.artifact_id) == PNG  # ordinary artifacts do not expire
    assert len(store) == 1


# --- ADR-041 amendment (M2/M3): bound to the project; a save ends the step -------------

#: The helper "saves": an act writes the schematic inside the workspace it was given.
SAVING_HELPER = (
    "if argv[0] == 'act':\n"
    "    pathlib.Path(argv[2], 'board.kicad_sch').write_text('saved by the act')\n"
    "print(json.dumps({'ok': True, 'verb': 'click', 'finishedAt': 2.0}))\n"
)
ACT = {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "click", "x": 1, "y": 40}


def _schematic(ws: Path, text: str = "(kicad_sch)") -> Path:
    path = ws / "board.kicad_sch"
    path.write_text(text)
    return path


async def test_no_linked_workspace_refuses_without_running_the_helper(tmp_path: Path) -> None:
    server = DriveServer(
        desktop_relay(echo_helper(tmp_path, OK_IDENTIFY)),
        enabled=True,
        workspace=None,
        platform="darwin",
    )
    result = await server.call_tool("identify", {})
    assert result.isError and "no project workspace" in text_of(result)
    assert calls(tmp_path) == []


async def test_the_workspace_is_sent_resolved(tmp_path: Path) -> None:
    helper = echo_helper(tmp_path, OK_IDENTIFY)
    real = workspace_of(helper)
    link = tmp_path / "link"
    link.symlink_to(real)
    server = DriveServer(desktop_relay(helper), enabled=True, workspace=link, platform="darwin")
    await server.call_tool("identify", {})
    assert calls(tmp_path) == [["identify", "--within", str(real.resolve())]]


async def test_an_act_before_identify_is_refused(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True, "finishedAt": 2.0}), bound=False)
    result = await server.call_tool("act", ACT)
    assert result.isError and text_of(result).startswith("not_bound: ")
    assert calls(tmp_path) == []


async def test_identify_takes_the_saved_design_baseline(tmp_path: Path) -> None:
    helper = make_helper(tmp_path, SAVING_HELPER.replace("'click'", "'x', 'now': 1.0"))
    ws = workspace_of(helper)
    _schematic(ws)
    server = server_with(helper, bound=False)
    assert not (await server.call_tool("identify", {})).isError
    assert server._designs_at_bind == saved_design_fingerprint(server.workspace)


async def test_an_act_that_saves_reports_it(tmp_path: Path) -> None:
    helper = make_helper(tmp_path, SAVING_HELPER)
    _schematic(workspace_of(helper))
    server = server_with(helper)
    result = await server.call_tool("act", ACT)
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["designSaved"] is True


async def test_an_act_that_does_not_save_says_so(tmp_path: Path) -> None:
    server = server_with(echo_helper(tmp_path, {"ok": True, "finishedAt": 2.0}))
    result = await server.call_tool("act", ACT)
    assert result.structuredContent is not None
    assert result.structuredContent["designSaved"] is False


async def test_a_design_changed_since_bind_stops_before_the_next_act(tmp_path: Path) -> None:
    helper = echo_helper(tmp_path, {"ok": True, "finishedAt": 2.0})
    schematic = _schematic(workspace_of(helper))
    server = server_with(helper)
    schematic.write_text("(kicad_sch saved)")
    result = await server.call_tool("act", ACT)
    assert result.isError and text_of(result).startswith("design_saved: ")
    assert calls(tmp_path) == []  # nothing ran


async def test_kicads_timed_writes_are_not_a_save(tmp_path: Path) -> None:
    helper = echo_helper(tmp_path, {"ok": True, "finishedAt": 2.0})
    ws = workspace_of(helper)
    _schematic(ws)
    server = server_with(helper)
    (ws / ".history").mkdir()
    (ws / ".history" / "board.kicad_sch").write_text("snapshot")
    (ws / "_autosave-board.kicad_sch").write_text("autosave")
    (ws / "board.kicad_sch.lck").write_text("{}")
    (ws / "notes.txt").write_text("not a design")
    result = await server.call_tool("act", ACT)
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["designSaved"] is False


def test_saved_design_fingerprint_sees_saves_in_subfolders_only_of_design_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "sub").mkdir()
    before = saved_design_fingerprint(tmp_path)
    (tmp_path / "sub" / "power.kicad_sch").write_text("(kicad_sch)")
    after = saved_design_fingerprint(tmp_path)
    assert before and after and before != after
    (tmp_path / "main.py").write_text("print()")  # source is not a design save
    assert saved_design_fingerprint(tmp_path) == after
    assert saved_design_fingerprint(None) == ""


def test_saved_design_fingerprint_fails_closed_past_its_entry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_companion import watch

    monkeypatch.setattr(watch, "MAX_ENTRIES", 3)
    for n in range(4):
        (tmp_path / f"f{n}.txt").write_text("x")
    assert saved_design_fingerprint(tmp_path) == ""


def test_saved_design_fingerprint_counts_symlinked_and_dot_folder_designs(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.kicad_sch"
    outside.write_text("(kicad_sch)")
    ws = tmp_path / "ws"
    (ws / ".hidden").mkdir(parents=True)
    (ws / "board.kicad_sch").symlink_to(outside)
    before = saved_design_fingerprint(ws)
    outside.write_text("(kicad_sch saved through the link)")
    assert saved_design_fingerprint(ws) != before
    before = saved_design_fingerprint(ws)
    (ws / ".hidden" / "power.kicad_sch").write_text("(kicad_sch)")
    assert saved_design_fingerprint(ws) != before  # only `.history` is KiCad's own


async def test_a_failed_act_that_saved_first_reports_the_save(tmp_path: Path) -> None:
    helper = make_helper(
        tmp_path,
        "pathlib.Path(argv[2], 'board.kicad_sch').write_text('saved, then the user moved')\n"
        "print(json.dumps({'ok': False, 'code': 'user_active', 'message': 'you moved'}))\n",
    )
    _schematic(workspace_of(helper))
    result = await server_with(helper).call_tool("act", ACT)
    assert result.isError and text_of(result).startswith("design_saved: ")


async def test_the_capture_after_an_act_reports_a_save_that_landed_late(tmp_path: Path) -> None:
    helper = echo_helper(tmp_path, capture_reply(base64.b64encode(PNG).decode()))
    schematic = _schematic(workspace_of(helper))
    server = server_with(helper)
    capture = {"bundle": "org.kicad.kicad", "window": 7}
    assert json.loads(text_of(await server.call_tool("capture", capture)))["designSaved"] is False
    schematic.write_text("(kicad_sch written a moment after the act)")
    assert json.loads(text_of(await server.call_tool("capture", capture)))["designSaved"] is True


async def test_every_identify_starts_from_no_baseline(tmp_path: Path) -> None:
    helper = echo_helper(tmp_path, {"ok": False, "code": "usage", "message": "x"})
    server = server_with(helper)  # bound by an earlier step
    await server.call_tool("identify", {})
    result = await server.call_tool("act", ACT)
    assert text_of(result).startswith("not_bound: ")


def test_saved_design_fingerprint_sees_a_project_under_build(tmp_path: Path) -> None:
    (tmp_path / "build").mkdir()
    before = saved_design_fingerprint(tmp_path)
    (tmp_path / "build" / "board.kicad_sch").write_text("(kicad_sch)")
    assert saved_design_fingerprint(tmp_path) != before


# --- slice 3b (XPC): the relay to the desktop (sol-drive.md §3 helper.py) ------------------


def reply_line(call_id: Any, reply: Any) -> bytes:
    return json.dumps({"type": "drive_reply", "id": call_id, "reply": reply}).encode()


async def test_each_call_writes_one_request_with_increasing_ids(tmp_path: Path) -> None:
    relay = desktop_relay(echo_helper(tmp_path, OK_IDENTIFY))
    desktop = _DESKTOPS[-1]
    assert await relay.run(["identify", "--within", "/w"], timeout=5) == OK_IDENTIFY
    assert await relay.run(["identify"], timeout=5) == OK_IDENTIFY
    first, second = (json.loads(line) for line in desktop.lines)
    assert first == {"type": "drive_request", "id": 1, "argv": ["identify", "--within", "/w"]}
    assert second["id"] == 2


async def test_a_relay_with_no_desktop_attached_refuses_agent_unavailable() -> None:
    lines: list[str] = []
    with pytest.raises(DriveHelperError) as caught:
        await DriveRelay(lines.append).run(["identify"], timeout=1)
    assert caught.value.code == "agent_unavailable"
    assert lines == []


async def test_a_desktop_refusal_is_a_reply_like_any_other() -> None:
    lines: list[str] = []
    relay = DriveRelay(lines.append, attached=True)
    box = TokenBox()
    box.drive_relay = relay
    task = asyncio.create_task(relay.run(["identify"], timeout=5))
    await asyncio.sleep(0)
    refusal = {"ok": False, "code": "agent_unavailable", "message": "not running"}
    apply_token_line(box, reply_line(1, refusal))
    assert await task == refusal


async def test_timeout_writes_a_cancel_and_a_late_reply_is_dropped() -> None:
    lines: list[str] = []
    relay = DriveRelay(lines.append, attached=True)
    with pytest.raises(DriveHelperError) as caught:
        await relay.run(["identify"], timeout=0.05)
    assert caught.value.code == "helper_timeout"
    assert [json.loads(line) for line in lines] == [
        {"type": "drive_request", "id": 1, "argv": ["identify"]},
        {"type": "drive_cancel", "id": 1},
    ]
    relay.deliver({"type": "drive_reply", "id": 1, "reply": {"ok": True}}, size=30)  # no raise
    assert relay.pending == 0


async def test_cancellation_writes_a_cancel() -> None:
    lines: list[str] = []
    relay = DriveRelay(lines.append, attached=True)
    task = asyncio.create_task(relay.run(["identify"], timeout=5))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert json.loads(lines[-1]) == {"type": "drive_cancel", "id": 1}
    assert relay.pending == 0


@pytest.mark.parametrize(
    "message",
    [
        {"type": "drive_reply", "id": 99, "reply": {"ok": True}},
        {"type": "drive_reply", "id": "1", "reply": {"ok": True}},
        {"type": "drive_reply", "id": True, "reply": {"ok": True}},
        {"type": "drive_reply", "reply": {"ok": True}},
        {"type": "drive_reply", "id": 1, "reply": {"ok": True}, "extra": 1},
    ],
)
async def test_unknown_or_malformed_replies_are_dropped(message: dict[str, Any]) -> None:
    relay = DriveRelay(lambda _: None, attached=True)
    task = asyncio.create_task(relay.run(["identify"], timeout=0.2))
    await asyncio.sleep(0)
    relay.deliver(message, size=64)
    with pytest.raises(DriveHelperError) as caught:
        await task
    assert caught.value.code == "helper_timeout"  # the call was never answered


async def test_a_reply_over_24_mib_fails_its_call() -> None:
    relay = DriveRelay(lambda _: None, attached=True)
    task = asyncio.create_task(relay.run(["capture"], timeout=5))
    await asyncio.sleep(0)
    relay.deliver({"type": "drive_reply", "id": 1, "reply": {"ok": True}}, size=24 * 2**20 + 1)
    with pytest.raises(DriveHelperError) as caught:
        await task
    assert caught.value.code == "helper_output"


def test_drive_reply_lines_without_a_relay_are_ignored() -> None:
    apply_token_line(TokenBox(), reply_line(1, {"ok": True}))  # must not raise


async def test_a_large_drive_reply_line_passes_the_stdin_bound(tmp_path: Path) -> None:
    lines: list[str] = []
    relay = DriveRelay(lines.append, attached=True)
    box = TokenBox()
    box.drive_relay = relay
    task = asyncio.create_task(relay.run(["capture"], timeout=5))
    await asyncio.sleep(0)
    big = {"ok": True, "png": "A" * (2 * 2**20)}  # far over the 32 KiB control bound
    apply_token_line(box, reply_line(1, big))
    assert (await task)["png"] == big["png"]


def test_builtins_share_the_relay_with_drive(tmp_path: Path) -> None:
    relay = DriveRelay(lambda _: None)
    drive = build_builtins(
        str(tmp_path), env={"SOLUS_COMPANION_DRIVE": "1"}, platform="darwin", relay=relay
    )[1]
    assert isinstance(drive, DriveServer)
    assert drive.helper is relay


def test_an_oversize_non_drive_line_is_still_refused_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(raw: object) -> object:
        raise AssertionError("an oversize control line must not be parsed")

    monkeypatch.setattr("solus_companion.config.json.loads", boom)
    box = TokenBox("tok-1")
    box.drive_relay = DriveRelay(lambda _: None, attached=True)
    token = json.dumps({"type": "token", "access_token": "t" * (40 * 1024)}).encode()
    apply_token_line(box, token)
    # Padding before the type key does not smuggle a big line past the bound.
    sneaky = b' {"type":"drive_reply","id":1,"reply":' + b"0" * (40 * 1024) + b"}"
    apply_token_line(box, sneaky)
    assert box() == "tok-1"


async def test_the_stdin_reader_carries_a_capture_sized_drive_reply() -> None:
    from solus_companion.__main__ import STDIN_READER_LIMIT, _consume_token_lines

    assert STDIN_READER_LIMIT >= 25 * 2**20
    relay = DriveRelay(lambda _: None, attached=True)
    box = TokenBox()
    box.drive_relay = relay
    task = asyncio.create_task(relay.run(["capture"], timeout=10))
    await asyncio.sleep(0)
    reader = asyncio.StreamReader(limit=STDIN_READER_LIMIT)
    png = "A" * (22 * 2**20)  # an incompressible 2048-px capture as base64
    reader.feed_data(reply_line(1, {"ok": True, "png": png}) + b"\n")
    reader.feed_eof()
    await _consume_token_lines(reader, box)
    assert (await task)["png"] == png


async def test_a_line_over_the_reader_limit_is_dropped_and_the_loop_survives() -> None:
    from solus_companion.__main__ import STDIN_READER_LIMIT, _consume_token_lines

    box = TokenBox()
    reader = asyncio.StreamReader(limit=STDIN_READER_LIMIT)
    reader.feed_data(b"x" * (STDIN_READER_LIMIT + 1024) + b"\n")
    reader.feed_data(json.dumps({"type": "token", "access_token": "after"}).encode() + b"\n")
    reader.feed_eof()
    await _consume_token_lines(reader, box)
    assert box() == "after"


def test_a_duplicate_type_key_cannot_smuggle_a_big_token_line() -> None:
    box = TokenBox("tok-1")
    box.drive_relay = DriveRelay(lambda _: None, attached=True)
    smuggled = b'{"type":"drive_reply","type":"token","access_token":"' + b"t" * 40960 + b'"}'
    apply_token_line(box, smuggled)
    assert box() == "tok-1"
