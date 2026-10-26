"""`DriveServer`: the companion builtin "drive" (docs/architecture/sol-drive.md §3).

Same inventory and `CallToolResult` shapes as `machine`, so the cloud gate and
`dispatch.map_result` treat it like any server. It advertises nothing unless
the platform is macOS, the pinned helper validates, and the desktop app has
switched driving on. Arguments are checked strictly here; the helper re-checks
everything that matters for safety itself.
"""

import base64
import binascii
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_companion.drive.helper import DriveHelper, DriveHelperError, resolve_helper

logger = logging.getLogger("solus.companion.drive")

ENV_SWITCH = "SOLUS_COMPANION_DRIVE"
ENV_HELPER = "SOLUS_DRIVE_HELPER"
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
Coord = Field(default=None, ge=-_COORD, le=_COORD)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IdentifyArgs(_Args):
    pass


class CaptureArgs(_Args):
    bundle: str = Bundle
    window: int = WindowId
    max_edge: int = Field(default=1568, ge=256, le=4096)


class ActArgs(_Args):
    bundle: str = Bundle
    window: int = WindowId
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
    chord: str | None = Field(default=None, min_length=1, max_length=64)
    text: str | None = Field(default=None, min_length=1, max_length=200)
    ms: int | None = Field(default=None, ge=0, le=2000)


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


def act_argv(args: ActArgs) -> list[str]:
    argv = [
        "act",
        "--bundle",
        args.bundle,
        "--window",
        str(args.window),
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
        self, helper: DriveHelper | None, *, enabled: bool, platform: str = sys.platform
    ) -> None:
        self.helper = helper
        self.enabled = enabled
        self.platform = platform
        self._since = datetime.now(UTC).isoformat()

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
            return await self._run(self.helper, tool, parsed)
        except DriveHelperError as exc:
            logger.warning("drive.%s helper failure: %s", tool, exc.code)
            return _error(str(exc))

    async def _run(self, helper: DriveHelper, tool: str, args: _Args) -> CallToolResult:
        if isinstance(args, CaptureArgs):
            argv = [
                "capture",
                "--bundle",
                args.bundle,
                "--window",
                str(args.window),
                "--max-edge",
                str(args.max_edge),
            ]
        elif isinstance(args, ActArgs):
            argv = act_argv(args)
        else:
            argv = ["identify"]
        extra = (args.ms or 0) / 1000 if isinstance(args, ActArgs) else 0.0
        reply = await helper.run(
            argv, timeout=helper.timeout_for(tool, DEFAULT_TIMEOUTS[tool]) + extra
        )
        if not reply["ok"]:
            return _error(f"{reply.get('code', 'refused')}: {reply.get('message', '')}")
        return _capture_result(reply) if tool == "capture" else _ok(reply)


def _capture_result(reply: dict[str, Any]) -> CallToolResult:
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
            TextContent(type="text", text=json.dumps(sizes)),
        ],
        isError=False,
    )


def drive_server_from_env(env: Mapping[str, str], *, platform: str = sys.platform) -> DriveServer:
    """What the companion builds at start (slice 2): the desktop app sets the
    switch to exactly "1" and the helper to its packaged absolute path."""
    path = resolve_helper(env.get(ENV_HELPER))
    return DriveServer(
        DriveHelper(path) if path is not None else None,
        enabled=env.get(ENV_SWITCH) == "1",
        platform=platform,
    )
