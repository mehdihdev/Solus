"""The computer-use toolset, translated onto the closed drive vocabulary.

ADR-041 §5 (and its 2026-10-26 amendment): the model only PROPOSES, through
Anthropic's `computer_toolset_20260801`. Solus code maps each proposal onto one
`solus-input act` verb, and every member outside the vocabulary is switched off
in the request. Three outcomes, all decided here, none by the model:

- `ActRequest` / `Capture`: run it (the helper still checks everything again);
- `Unsupported`: answered as an error so the model can try a supported form
  (it still spends one action of the step's budget);
- `OutOfBounds`: a point outside the captured window ends the step (§5 bounds).

Pure: no I/O, no SDK. Coordinates arrive in screenshot pixels and leave in
window points (sol-drive.md §4: `pointsWidth / imageWidth`).
"""

import base64
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal

TOOLSET_NAME: Final = "computer"

#: Members the drive vocabulary can express (ADR-041 §5).
ENABLED_MEMBERS: Final = frozenset(
    {
        "screenshot",
        "left_click",
        "right_click",
        "double_click",
        "left_click_drag",
        "mouse_move",
        "scroll",
        "type",
        "key",
        "wait",
    }
)
#: Everything else the toolset offers, withheld rather than refused at runtime.
DISABLED_MEMBERS: Final = frozenset(
    {
        "zoom",
        "middle_click",
        "triple_click",
        "left_mouse_down",
        "left_mouse_up",
        "cursor_position",
        "hold_key",
    }
)
TOOLSET: Final[dict[str, Any]] = {
    "type": "computer_toolset_20260801",
    "configs": {member: {"enabled": False} for member in sorted(DISABLED_MEMBERS)},
}

#: Mirrors the helper's bounds (solus-input Runner.swift) so a bad proposal is
#: answered here instead of becoming a step-ending helper refusal.
MAX_SCROLL: Final = 50
MAX_WAIT_MS: Final = 2000

#: The helper's key names (Policy.swift `KeyMap`). The helper's ChordPolicy
#: still decides which chords may be pressed; this only rejects names it would
#: not know at all.
_KEYS: Final = frozenset(
    set("abcdefghijklmnopqrstuvwxyz0123456789")
    | set("=-][';\\,./`")
    | {"return", "tab", "space", "delete", "escape", "forwarddelete", "home", "end"}
    | {"pageup", "pagedown", "left", "right", "down", "up"}
    | {f"f{n}" for n in range(1, 13)}
)
#: xdotool-style names the model uses → helper names. "Delete" is FORWARD delete
#: there; the helper's "delete" is backspace.
_KEY_ALIASES: Final = {
    "enter": "return",
    "kp_enter": "return",
    "esc": "escape",
    "backspace": "delete",
    "delete": "forwarddelete",
    "page_up": "pageup",
    "prior": "pageup",
    "page_down": "pagedown",
    "next": "pagedown",
    "minus": "-",
    "equal": "=",
}
_MODIFIERS: Final = {
    "super": "cmd",
    "cmd": "cmd",
    "command": "cmd",
    "meta": "cmd",
    "shift": "shift",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "option",
    "option": "option",
}
_MODIFIER_ORDER: Final = ("cmd", "ctrl", "option", "shift")
_SCROLL: Final = {"up": (0, 1), "down": (0, -1), "left": (1, 0), "right": (-1, 0)}


@dataclass(frozen=True)
class Frame:
    """The capture the model's coordinates refer to."""

    image_width: int
    image_height: int
    points_width: int
    points_height: int


@dataclass(frozen=True)
class Capture:
    """Take a fresh screenshot of the bound window."""


@dataclass(frozen=True)
class ActRequest:
    """One `drive.act` call, in window points (the companion's ActArgs)."""

    verb: Literal["click", "move", "drag", "scroll", "key", "type", "wait"]
    x: int | None = None
    y: int | None = None
    to_x: int | None = None
    to_y: int | None = None
    dx: int | None = None
    dy: int | None = None
    button: Literal["left", "right"] | None = None
    count: int | None = None
    chord: str | None = None
    text: str | None = None
    ms: int | None = None

    def args(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class Unsupported:
    reason: str


@dataclass(frozen=True)
class OutOfBounds:
    reason: str


Proposal = Capture | ActRequest | Unsupported | OutOfBounds


def _pixel(value: Any) -> tuple[int, int] | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        return value[0], value[1]
    return None


def _to_points(pixel: tuple[int, int], frame: Frame) -> tuple[int, int] | None:
    x, y = pixel
    if not (0 <= x < frame.image_width and 0 <= y < frame.image_height):
        return None
    return (
        x * frame.points_width // frame.image_width,
        y * frame.points_height // frame.image_height,
    )


def _point(args: dict[str, Any], key: str, frame: Frame) -> tuple[int, int] | Proposal:
    pixel = _pixel(args.get(key))
    if pixel is None:
        return Unsupported(f"`{key}` must be [x, y] in whole screenshot pixels")
    points = _to_points(pixel, frame)
    if points is None:
        return OutOfBounds(
            f"{pixel} is outside the {frame.image_width}x{frame.image_height} window"
        )
    return points


def chord_for(text: Any) -> str | None:
    """`ctrl+s` / `super+z` / `Return` → the helper's `cmd+z` form, or None."""
    if not isinstance(text, str) or not text:
        return None
    modifiers: set[str] = set()
    key: str | None = None
    for raw in text.split("+"):
        part = raw.strip().lower()
        if part in _MODIFIERS:
            if _MODIFIERS[part] in modifiers:
                return None
            modifiers.add(_MODIFIERS[part])
            continue
        name = _KEY_ALIASES.get(part, part)
        if key is not None or name not in _KEYS:
            return None
        key = name
    if key is None:
        return None
    return "+".join([m for m in _MODIFIER_ORDER if m in modifiers] + [key])


def _click(member: str, args: dict[str, Any], frame: Frame) -> Proposal:
    if args.get("text"):
        return Unsupported("modifier clicks are not available; press keys separately")
    point = _point(args, "coordinate", frame)
    if not isinstance(point, tuple):
        return point
    button: Literal["left", "right"] = "right" if member == "right_click" else "left"
    count = 2 if member == "double_click" else 1
    return ActRequest(verb="click", x=point[0], y=point[1], button=button, count=count)


def _drag(args: dict[str, Any], frame: Frame) -> Proposal:
    if args.get("text"):
        return Unsupported("modifier drags are not available")
    start = _point(args, "start_coordinate", frame)
    if not isinstance(start, tuple):
        return start
    end = _point(args, "coordinate", frame)
    if not isinstance(end, tuple):
        return end
    return ActRequest(verb="drag", x=start[0], y=start[1], to_x=end[0], to_y=end[1])


def _scroll(args: dict[str, Any], frame: Frame) -> Proposal:
    direction = _SCROLL.get(args.get("scroll_direction"))  # type: ignore[arg-type]
    amount = args.get("scroll_amount")
    if args.get("text") or direction is None:
        return Unsupported("scroll up, down, left or right, without modifiers")
    if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= MAX_SCROLL:
        return Unsupported(f"scroll_amount must be 1-{MAX_SCROLL}")
    point = _point(args, "coordinate", frame)
    if not isinstance(point, tuple):
        return point
    return ActRequest(
        verb="scroll", x=point[0], y=point[1], dx=direction[0] * amount, dy=direction[1] * amount
    )


def _key(args: dict[str, Any]) -> Proposal:
    if args.get("repeat", 1) != 1:
        return Unsupported("repeat is not available; press the key once per action")
    chord = chord_for(args.get("text"))
    if chord is None:
        return Unsupported("not a key this Mac helper knows")
    return ActRequest(verb="key", chord=chord)


def _wait(args: dict[str, Any]) -> Proposal:
    duration = args.get("duration")
    if not isinstance(duration, int | float) or isinstance(duration, bool):
        return Unsupported("duration must be a number of seconds")
    ms = round(duration * 1000)
    if not 0 <= ms <= MAX_WAIT_MS:
        return Unsupported(f"wait at most {MAX_WAIT_MS // 1000} s")
    return ActRequest(verb="wait", ms=ms)


def map_action(member: str, args: dict[str, Any], frame: Frame) -> Proposal:
    """Translate one proposed member call. Unknown members are Unsupported."""
    if member not in ENABLED_MEMBERS:
        return Unsupported(f"`{member}` is not available")
    if member == "screenshot":
        return Capture()
    if member in {"left_click", "right_click", "double_click"}:
        return _click(member, args, frame)
    if member == "left_click_drag":
        return _drag(args, frame)
    if member == "mouse_move":
        point = _point(args, "coordinate", frame)
        return (
            ActRequest(verb="move", x=point[0], y=point[1]) if isinstance(point, tuple) else point
        )
    if member == "scroll":
        return _scroll(args, frame)
    if member == "key":
        return _key(args)
    if member == "wait":
        return _wait(args)
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return Unsupported("type needs non-empty text")
    return ActRequest(verb="type", text=text)


def _result(tool_use_id: str, content: Any, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "toolset_name": TOOLSET_NAME,
        "content": content,
    }
    if is_error:
        result["is_error"] = True
    return result


def image_result(tool_use_id: str, png: bytes) -> dict[str, Any]:
    source = {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}
    return _result(tool_use_id, [{"type": "image", "source": source}])


def ok_result(tool_use_id: str) -> dict[str, Any]:
    return _result(tool_use_id, [{"type": "text", "text": "OK"}])


def error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return _result(tool_use_id, f"Error: {message}", is_error=True)


def skipped_result(tool_use_id: str) -> dict[str, Any]:
    """The toolset's required answer for a call after a failed one in a batch."""
    return _result(
        tool_use_id, "Not executed: an earlier computer action in this turn failed.", is_error=True
    )
