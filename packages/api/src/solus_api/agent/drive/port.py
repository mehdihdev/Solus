"""The drive executor's view of the helper: `identify`, `capture`, `act`.

`BridgeDrivePort` reaches the companion's INTERNAL `drive.*` tools (allowlist
`exposure: internal`) and parses what comes back. Everything here is untrusted
input from the machine (CLAUDE.md §7): shapes are checked, sizes bounded, and a
malformed reply is a refusal, never a crash. A helper refusal arrives as the
companion's `code: message` error text and becomes `DriveRefusal(code, …)`.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from solus_api.agent.drive.actions import ActRequest, Frame
from solus_api.agent.drive.binding import BUNDLE_ID_PATTERN, PID_MAX, WINDOW_ID_MAX
from solus_api.agent.tools.tool import Tool, ToolException

PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
#: The vision limit on every toolset model (Anthropic: 2,576 px long edge).
MAX_IMAGE_EDGE: Final = 2576
_CODE_PREFIX: Final = re.compile(r"^([a-z][a-z_]{0,39}): (.*)$", re.DOTALL)
#: sol-drive.md §2 (helper) and §3 (companion) refusal codes. Anything else a
#: companion sends is `unknown`: the code reaches SOL and data events, so it is
#: never free text from the machine.
KNOWN_CODES: Final = frozenset(
    {
        "usage",
        # Kept for older helpers; slice 4 helpers answer app_denied instead.
        "app_not_allowed",
        "app_denied",
        "pid_mismatch",
        "not_trusted",
        "screen_recording_denied",
        "not_frontmost",
        "window_mismatch",
        "window_not_found",
        "window_resized",
        "window_chrome",
        "out_of_bounds",
        "occluded",
        "bad_chord",
        "chord_denied",
        "bad_text",
        "secure_field",
        "user_active",
        "focus_lost",
        "stopped",
        "capture_failed",
        "outside_workspace",
        "design_saved",
        "not_bound",
        "helper_missing",
        "helper_spawn",
        "helper_timeout",
        "helper_crashed",
        "helper_output",
        "agent_unavailable",
        "bridge",
    }
)
#: One bridge round trip; BridgeTool.invoke is called directly here, outside
#: the registry's own timeout.
CALL_TIMEOUT_SECONDS: Final = 30.0
_BUNDLE_ID: Final = re.compile(BUNDLE_ID_PATTERN)
_BINDINGS: Final = frozenset({"project", "window"})
_REASONS: Final = frozenset({"denied", "no_workspace", "outside_workspace"})


class DriveRefusal(Exception):  # noqa: N818 — a refusal, not a bug
    """The helper (or the path to it) refused; `code` is its stable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Identity:
    """The helper's `identify` reply (sol-drive.md §2.2 `front`). Never the
    window title: the executor binds by ids alone."""

    #: The app in front is drivable (`front.drivable`).
    allowed: bool
    bundle_id: str | None
    app_name: str | None
    window_id: int | None
    now: float
    accessibility: bool
    screen_recording: bool
    #: The drivable app in front is working on a project outside the linked
    #: workspace (ADR-041 amendment, M2); the helper hid its identity.
    outside_workspace: bool = False
    pid: int | None = None
    #: `project` (KiCad) or `window` (any other drivable app).
    binding: str | None = None
    #: Why the app in front is not drivable: denied / no_workspace / outside_workspace.
    reason: str | None = None


@dataclass(frozen=True)
class Shot:
    png: bytes
    frame: Frame
    #: A design file changed since the step's bind (ADR-041 M3): KiCad writes a
    #: moment after a Save click, so the look after an act is where it shows.
    design_saved: bool = False


@dataclass(frozen=True)
class ActDone:
    finished_at: float
    #: The companion saw a design file in the workspace change (ADR-041 M3).
    design_saved: bool = False


class DrivePort(Protocol):
    async def identify(self) -> Identity: ...

    async def capture(
        self, bundle: str, window: int, *, max_edge: int, pid: int | None = None
    ) -> Shot: ...

    async def act(
        self,
        bundle: str,
        window: int,
        request: ActRequest,
        *,
        since: float,
        expect_width: int,
        expect_height: int,
        pid: int | None = None,
    ) -> ActDone: ...


def _malformed(what: str) -> DriveRefusal:
    return DriveRefusal("bridge", f"the companion sent a malformed {what} reply")


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bounded_int(value: Any, top: int) -> int | None:
    return value if _positive_int(value) and value <= top else None


def parse_identity(value: Any) -> Identity:
    """The slice-4 `{…, front: Front | null}` reply. Anything else in `front`
    (including the retired `allowed`/`app`/`window` shape) is not drivable."""
    if not isinstance(value, dict) or not _number(value.get("now")):
        raise _malformed("identify")
    trust, front = _mapping(value.get("trust")), _mapping(value.get("front"))
    bundle, name = front.get("bundleId"), front.get("name")
    bundle_id = bundle if isinstance(bundle, str) and _BUNDLE_ID.match(bundle) else None
    binding = front.get("binding") if front.get("binding") in _BINDINGS else None
    reason = front.get("reason") if front.get("reason") in _REASONS else None
    pid = _bounded_int(front.get("pid"), PID_MAX)
    window_id = _bounded_int(front.get("windowId"), WINDOW_ID_MAX)
    drivable = front.get("drivable") is True and bundle_id is not None and binding is not None
    if binding == "window" and pid is None:
        drivable = False
    return Identity(
        allowed=drivable,
        bundle_id=bundle_id,
        app_name=name[:64] if isinstance(name, str) else None,
        # A denied or unbound app never yields a pid or window to act on.
        window_id=window_id if drivable else None,
        now=float(value["now"]),
        accessibility=trust.get("accessibility") is True,
        screen_recording=trust.get("screenRecording") is True,
        outside_workspace=reason == "outside_workspace",
        pid=pid if drivable else None,
        binding=binding,
        reason=None if drivable else reason,
    )


def parse_capture(value: Any, *, max_edge: int) -> tuple[str, Frame, bool]:
    """The staged image's artifact id, the capture sizes, and whether a design
    was saved since the step's bind."""
    blocks = value.get("content") if isinstance(value, dict) else None
    if not isinstance(blocks, list):
        raise _malformed("capture")
    image = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "image"), None)
    text = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "text"), None)
    if image is None or not isinstance(image.get("artifact_id"), str) or text is None:
        raise _malformed("capture")
    try:
        sizes = json.loads(text.get("text") or "")
    except (TypeError, ValueError):
        raise _malformed("capture") from None
    keys = ("imageWidth", "imageHeight", "pointsWidth", "pointsHeight")
    if not isinstance(sizes, dict) or not all(_positive_int(sizes.get(k)) for k in keys):
        raise _malformed("capture")
    if max(sizes["imageWidth"], sizes["imageHeight"]) > min(max_edge, MAX_IMAGE_EDGE):
        raise _malformed("capture")
    frame = Frame(*(sizes[k] for k in keys))
    return image["artifact_id"], frame, sizes.get("designSaved") is True


def _refusal(exc: ToolException) -> DriveRefusal:
    match = _CODE_PREFIX.match(exc.message)
    if match is None:
        return DriveRefusal("bridge", exc.message[:200])
    code = match.group(1) if match.group(1) in KNOWN_CODES else "unknown"
    return DriveRefusal(code, match.group(2)[:200])


class BridgeDrivePort:
    """`DrivePort` over the requesting user's companion (internal tools only)."""

    def __init__(
        self,
        *,
        identify: Tool,
        capture: Tool,
        act: Tool,
        fetch: Callable[[str], Awaitable[bytes]],
    ) -> None:
        self._identify = identify
        self._capture = capture
        self._act = act
        self._fetch = fetch

    async def _call(self, tool: Tool, args: dict[str, Any]) -> Any:
        try:
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                return await tool.invoke(args)
        except TimeoutError:
            raise DriveRefusal("helper_timeout", "the companion did not answer in time") from None
        except ToolException as exc:
            raise _refusal(exc) from None

    async def identify(self) -> Identity:
        return parse_identity(await self._call(self._identify, {}))

    async def capture(
        self, bundle: str, window: int, *, max_edge: int, pid: int | None = None
    ) -> Shot:
        args: dict[str, Any] = {"bundle": bundle, "window": window, "max_edge": max_edge}
        if pid is not None:
            args["pid"] = pid
        value = await self._call(self._capture, args)
        artifact_id, frame, design_saved = parse_capture(value, max_edge=max_edge)
        try:
            png = await self._fetch(artifact_id)
        except ToolException as exc:
            raise _refusal(exc) from None
        if not png.startswith(PNG_MAGIC):
            raise _malformed("capture")
        return Shot(png=png, frame=frame, design_saved=design_saved)

    async def act(
        self,
        bundle: str,
        window: int,
        request: ActRequest,
        *,
        since: float,
        expect_width: int,
        expect_height: int,
        pid: int | None = None,
    ) -> ActDone:
        args = {
            "bundle": bundle,
            "window": window,
            "since": since,
            "expect_width": expect_width,
            "expect_height": expect_height,
            **request.args(),
            **({} if pid is None else {"pid": pid}),
        }
        value = await self._call(self._act, args)
        if not isinstance(value, dict) or not _number(value.get("finishedAt")):
            raise _malformed("act")
        return ActDone(
            finished_at=float(value["finishedAt"]), design_saved=value.get("designSaved") is True
        )
