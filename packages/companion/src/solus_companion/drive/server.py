"""`DriveServer`: the companion builtin "drive" (docs/architecture/sol-drive.md §3).

Same inventory and `CallToolResult` shapes as `machine`, so the cloud gate and
`dispatch.map_result` treat it like any server. It advertises nothing unless
the platform is macOS and the desktop app has switched driving on; a linked
workspace is optional (sol-drive.md §2.2) and only adds `--within` and the
saved-file watch. Each call is relayed to the desktop app, which alone
reaches the helper agent (slice 3b, XPC; `helper.py`), so a missing agent is a
call-time `agent_unavailable`. Arguments are checked strictly here; the agent
re-checks everything that matters for safety itself.
"""

import asyncio
import base64
import binascii
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_companion.drive.helper import DriveHelperError, DriveRelay
from solus_companion.drive.outline import Emit, outline_line, stdout_writer
from solus_companion.drive.save_watch import SaveWatch, document_folder

logger = logging.getLogger("solus.companion.drive")

ENV_SWITCH = "SOLUS_COMPANION_DRIVE"
OFF = "SOL can't use your mouse and keyboard (off)"
NO_HELPER = "the input helper is missing"
NOT_MACOS = "driving apps needs macOS"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SUMMARY_CAP = 2000
_COORD = 100_000
#: Seconds per helper command; `act` adds its own `wait`.
DEFAULT_TIMEOUTS = {"identify": 5.0, "capture": 15.0, "act": 10.0}

Bundle = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
WindowId = Field(ge=0, le=2**32 - 1)
#: The window owner's pid from the summon snapshot (§2.2); the helper checks it.
Pid = Field(default=None, ge=1, le=2**31 - 1)
Coord = Field(default=None, ge=-_COORD, le=_COORD)
#: Text a helper argument may carry: no NUL (it cannot cross argv).
_NO_NUL = r"^[^\x00]*$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IdentifyArgs(_Args):
    pass


class CaptureArgs(_Args):
    bundle: str = Bundle
    window: int = WindowId
    pid: int | None = Pid
    max_edge: int = Field(default=1568, ge=256, le=2048)


class ActArgs(_Args):
    bundle: str = Bundle
    window: int = WindowId
    pid: int | None = Pid
    #: From the helper's own clock: identify.now, then the previous act's finishedAt.
    since: float = Field(ge=0, allow_inf_nan=False)
    verb: Literal["click", "move", "drag", "scroll", "key", "type", "wait"]
    x: int | None = Coord
    y: int | None = Coord
    to_x: int | None = Coord
    to_y: int | None = Coord
    dx: int | None = Coord
    dy: int | None = Coord
    button: Literal["left", "right"] | None = None
    count: int | None = Field(default=None, ge=1, le=2)
    chord: str | None = Field(default=None, min_length=1, max_length=64, pattern=_NO_NUL)
    text: str | None = Field(default=None, min_length=1, max_length=200, pattern=_NO_NUL)
    ms: int | None = Field(default=None, ge=0, le=2000)
    #: The window size (points) the caller last captured: a resize since refuses.
    expect_width: int | None = Field(default=None, ge=1, le=_COORD)
    expect_height: int | None = Field(default=None, ge=1, le=_COORD)


#: Helper flags in a fixed order, so the argument list is deterministic.
_ACT_FLAGS = (
    ("x", "--x"),
    ("y", "--y"),
    ("to_x", "--to-x"),
    ("to_y", "--to-y"),
    ("dx", "--dx"),
    ("dy", "--dy"),
    ("button", "--button"),
    ("count", "--count"),
    ("chord", "--chord"),
    ("text", "--text"),
    ("ms", "--ms"),
    ("expect_width", "--expect-width"),
    ("expect_height", "--expect-height"),
)

_TOOLS: dict[str, tuple[type[_Args], str]] = {
    "identify": (IdentifyArgs, "The frontmost app and window, trust state, and the helper clock."),
    "capture": (CaptureArgs, "A PNG of one window of a drivable app (staged as an artifact)."),
    "act": (ActArgs, "One checked input action inside the bound window of a drivable app."),
}
TOOL_NAMES = frozenset(_TOOLS)


def _error(text: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text[:_SUMMARY_CAP])], isError=True
    )


def _ok(value: dict[str, Any]) -> CallToolResult:
    summary = json.dumps(value, default=str)[:_SUMMARY_CAP]
    return CallToolResult(
        content=[TextContent(type="text", text=summary)], structuredContent=value, isError=False
    )


def _target(args: CaptureArgs | ActArgs) -> list[str]:
    """`--bundle B --window W [--pid P]`: always an argument list, never a shell string."""
    argv = ["--bundle", args.bundle, "--window", str(args.window)]
    return argv if args.pid is None else [*argv, "--pid", str(args.pid)]


def _forwarded(reply: dict[str, Any]) -> dict[str, Any]:
    """The identify reply for the cloud: `front.documentDir` stays on this machine."""
    front = reply.get("front")
    if not isinstance(front, dict) or "documentDir" not in front:
        return reply
    return {**reply, "front": {k: v for k, v in front.items() if k != "documentDir"}}


def act_argv(args: ActArgs) -> list[str]:
    argv = [
        "act",
        *_target(args),
        "--since",
        repr(args.since),
        args.verb,
    ]
    for field, flag in _ACT_FLAGS:
        value = getattr(args, field)
        if value is not None:
            argv += [flag, str(value)]
    return argv


class DriveServer:
    name = "drive"
    tool_names = TOOL_NAMES

    def __init__(
        self,
        helper: DriveRelay | None,
        *,
        enabled: bool,
        workspace: Path | None,
        platform: str = sys.platform,
        emit: Emit | None = None,
    ) -> None:
        self.helper = helper
        #: Slice 3: where `drive_window` outline lines go (the companion's stdout).
        self.emit = emit if emit is not None else stdout_writer()
        self.enabled = enabled
        #: ADR-041 M2: when linked, every helper command carries `--within` it.
        self.workspace = workspace.resolve() if workspace is not None else None
        self.platform = platform
        #: Set by the step's ok identify; `act` refuses `not_bound` before it.
        self._bound = False
        #: The step's saved-file watch (§2.2); None = off (nothing to report).
        self._watch: SaveWatch | None = None
        self._since = datetime.now(UTC).isoformat()
        # One helper at a time: two acts must never interleave events in a window.
        self._one_at_a_time = asyncio.Lock()

    def _off_reason(self) -> str | None:
        if self.platform != "darwin":
            return NOT_MACOS
        if not self.enabled:
            return OFF
        if self.helper is None:
            return NO_HELPER
        return None

    def inventory(self) -> dict[str, Any] | None:
        if self._off_reason() is not None:
            return None
        tools = [
            {"name": name, "description": description, "input_schema": model.model_json_schema()}
            for name, (model, description) in _TOOLS.items()
        ]
        return {"server": self.name, "tools": tools}

    def status_entry(self) -> dict[str, Any]:
        reason = self._off_reason()
        return {
            "name": self.name,
            "state": "ready" if reason is None else "not_launched",
            "detail": reason,
            "updated_at": self._since,
        }

    async def call_tool(self, tool: str, args: dict[str, Any]) -> CallToolResult:
        spec = _TOOLS.get(tool)
        if spec is None:
            return _error(f"unknown_tool: drive.{tool}")
        reason = self._off_reason()
        if reason is not None or self.helper is None:
            return _error(f"drive_off: {reason or NO_HELPER}")
        try:
            parsed = spec[0].model_validate(args)
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return _error(f"invalid_arguments: {detail}")
        try:
            async with self._one_at_a_time:
                return await self._run(self.helper, tool, parsed)
        except DriveHelperError as exc:
            logger.warning("drive.%s helper failure: %s", tool, exc.code)
            return _error(str(exc))

    async def _run(self, helper: DriveRelay, tool: str, args: _Args) -> CallToolResult:
        if isinstance(args, ActArgs):
            stop = await self._stop_before_act()
            if stop is not None:
                return _error(stop)
        if tool == "identify":  # each step binds afresh: no stale baseline
            self._bound, self._watch = False, None
        reply = await self._helper(helper, tool, args)
        # A save is reported however the act ended (it may have saved, then been
        # refused), and by every capture: KiCad writes a moment after the click.
        saved = tool != "identify" and await self._saved()
        if not reply["ok"]:
            if tool == "act" and saved and self._watch is not None:
                return _error(f"design_saved: {self._watch.stop_message}")
            return _error(f"{reply.get('code', 'refused')}: {reply.get('message', '')}")
        if tool == "identify":
            front = reply.get("front")
            front = front if isinstance(front, dict) else None
            self._watch = await self._take_watch(front)
            self._bound = True
            self._outline(front.get("bounds") if front is not None else None)
            return _ok(_forwarded(reply))
        if tool == "capture":
            result = _capture_result(reply, design_saved=saved)
            self._outline(reply.get("bounds"))
            return result
        self._outline(reply.get("bounds"))
        return _ok({**reply, "designSaved": saved})

    async def _take_watch(self, front: dict[str, Any] | None) -> SaveWatch | None:
        """§2.2: KiCad watches design files in the workspace; a window-bound app
        watches its document's folder when that lies in the workspace; else off."""
        if self.workspace is None:
            return None
        if front is not None and front.get("binding") == "window":
            folder = document_folder(self.workspace, front.get("documentDir"))
            if folder is None:
                return None
            return await asyncio.to_thread(SaveWatch.take, folder, every_file=True)
        return await asyncio.to_thread(SaveWatch.take, self.workspace, every_file=False)

    def _outline(self, bounds: Any) -> None:
        """One `drive_window` line for valid bounds; nothing otherwise (§3)."""
        line = outline_line(bounds)
        if line is not None:
            self.emit(line)

    async def _saved(self) -> bool:
        """A watched file changed since the step's bind (or it cannot be seen)."""
        if self._watch is None:
            return False
        return await asyncio.to_thread(self._watch.changed)

    async def _stop_before_act(self) -> str | None:
        """Why an act must not run: not bound yet, or a watched file changed since."""
        if not self._bound:
            return "not_bound: identify the window first"
        if self._watch is not None and await self._saved():
            return f"design_saved: {self._watch.stop_message}"
        return None

    async def _helper(self, helper: DriveRelay, tool: str, args: _Args) -> dict[str, Any]:
        if isinstance(args, CaptureArgs):
            argv = ["capture", *_target(args), "--max-edge", str(args.max_edge)]
        elif isinstance(args, ActArgs):
            argv = act_argv(args)
        else:
            argv = ["identify"]
        if self.workspace is not None:
            argv[1:1] = ["--within", str(self.workspace)]
        extra = (args.ms or 0) / 1000 if isinstance(args, ActArgs) else 0.0
        return await helper.run(
            argv, timeout=helper.timeout_for(tool, DEFAULT_TIMEOUTS[tool]) + extra
        )


def _capture_result(reply: dict[str, Any], *, design_saved: bool) -> CallToolResult:
    """The image as MCP content (dispatch stages it as an artifact); the sizes as
    text. No structuredContent: dispatch would forward that and drop the image."""
    png = reply.get("png")
    sizes = {
        key: reply.get(key) for key in ("imageWidth", "imageHeight", "pointsWidth", "pointsHeight")
    }
    if not isinstance(png, str) or not all(isinstance(v, int) and v > 0 for v in sizes.values()):
        raise DriveHelperError("helper_output", "capture is missing its image or sizes")
    try:
        decoded = base64.b64decode(png, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DriveHelperError("helper_output", "capture image is not base64") from exc
    if not decoded.startswith(PNG_SIGNATURE):
        raise DriveHelperError("helper_output", "capture image is not a PNG")
    return CallToolResult(
        content=[
            ImageContent(type="image", data=png, mimeType="image/png"),
            TextContent(type="text", text=json.dumps({**sizes, "designSaved": design_saved})),
        ],
        isError=False,
    )


def drive_server_from_env(
    env: Mapping[str, str],
    *,
    workspace: Path | None,
    platform: str = sys.platform,
    relay: DriveRelay | None = None,
) -> DriveServer:
    """What the companion builds at start: the desktop app sets the switch to
    exactly "1". Calls are relayed to the desktop over stdio (slice 3b, XPC)."""
    return DriveServer(
        relay if relay is not None else DriveRelay(stdout_writer()),
        enabled=env.get(ENV_SWITCH) == "1",
        workspace=workspace,
        platform=platform,
    )
