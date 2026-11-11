"""The adapter protocol every Gazebo family implements, plus the pieces they share.

Every subprocess is an argv list run with the scrubbed child environment (`PATH=/usr/bin:/bin`,
`LANG`, and the names in `solus/env.allow` — the launcher's own passthrough list); the binary is
always the pinned `Family.exe` (or a sibling in the same `bin_dir`), never a PATH lookup. Names
that end up in an argv or a protobuf text-format request pass :func:`check_name` first, so a
user string can never become an option (`-x`) or text-format syntax (`{`, `"`, `:`).

The fork never raises across the wire: :class:`Unsupported` and :class:`CliError` are caught by
the server and become ``{ok: false, code, reason}`` results. ``reason`` carries simulator stderr
only through :func:`stderr_detail`, which drops every absolute path (the user's home, the model
store, private temp files) before the text leaves the fork.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from ..family_detect import Family

ENV_ALLOW_FILE: Final = Path(__file__).resolve().parents[1] / "env.allow"
MAX_SAMPLES: Final = 200  # ponytail: a window keeps at most 200 evenly spaced samples
MAX_TEXT_FORMAT_BYTES: Final = 8 * 1024 * 1024
SERVICE_TIMEOUT_MS: Final = 5000
STATS_WINDOW_S: Final = 0.3
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
_TOPIC = re.compile(r"^/[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}$")
_TOKEN = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[{}:]|[^\s{}:]+")
_ESCAPE = re.compile(rb"\\(x[0-9a-fA-F]{1,2}|[0-7]{1,3}|.|$)", re.DOTALL)
_SIMPLE_ESCAPES: Final = {
    b"n": b"\n", b"t": b"\t", b"r": b"\r", b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v",
    b"\\": b"\\", b'"': b'"', b"'": b"'", b"?": b"?",
}  # fmt: skip
_ABS_PATH = re.compile(r"/[^\s\]\[\"']+")
MAX_REASON_CHARS: Final = 200

ControlAction = Literal["pause", "play", "step", "reset"]
RESET_SCOPES: Final = ("all", "time", "model_only")


class Unsupported(Exception):  # noqa: N818 — the plan's interface name (P3-T2); a result, not an error
    """A capability this family lacks → ``{"ok": False, "code": "unsupported_on", ...}``."""

    def __init__(self, family: str, version: str, sentence: str) -> None:
        super().__init__(sentence)
        self.family = family
        self.version = version
        self.sentence = sentence

    def wire(self) -> dict[str, object]:
        return {
            "ok": False,
            "code": "unsupported_on",
            "family": self.family,
            "version": self.version,
            "reason": self.sentence,
        }


class CliError(Exception):
    """The pinned CLI failed, timed out or answered something unparseable."""

    def __init__(self, argv: Sequence[str], reason: str) -> None:
        super().__init__(reason)
        self.argv = tuple(argv)
        self.reason = reason


@dataclass(frozen=True)
class WorldPose:
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def quaternion(self) -> tuple[float, float, float, float]:
        """(x, y, z, w) from roll/pitch/yaw, the ZYX convention SDF uses."""
        r, p, y = (a / 2 for a in self.rpy)
        cr, sr, cp, sp = math.cos(r), math.sin(r), math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)
        return (
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy,
        )


@dataclass(frozen=True)
class SceneJoint:
    name: str
    type: str | None
    parent_link: str | None
    child_link: str | None


@dataclass(frozen=True)
class SceneModel:
    name: str
    links: tuple[str, ...]
    joints: tuple[SceneJoint, ...]


@dataclass(frozen=True)
class Scene:
    world: str
    models: tuple[SceneModel, ...]


@dataclass(frozen=True)
class JointSample:
    joint: str
    position: float
    velocity: float | None
    sim_time_s: float | None
    paused: bool


@dataclass(frozen=True)
class Completed:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


#: ``run(argv, timeout_s)`` → the finished child; raises :class:`CliError` when it cannot run or
#: outlives the timeout. Tests inject a recording wrapper around :func:`run_argv`.
CliRunner = Callable[[list[str], float], Completed]


class Adapter(Protocol):
    family: Family

    def running_worlds(self) -> list[str]: ...
    def start(self, world_file: Path, *, gui: bool) -> subprocess.Popen[bytes]: ...
    def scene(self, world: str) -> Scene: ...
    def spawn(self, world: str, model_sdf_path: Path, name: str, pose: WorldPose) -> None: ...
    def joint_state(
        self, world: str, model: str, joints: Sequence[str] | None, window_s: float
    ) -> list[JointSample]: ...
    def set_targets(self, world: str, model: str, targets: Mapping[str, float]) -> None: ...
    def control(
        self, world: str, action: ControlAction, *, steps: int = 1, scope: str = "all"
    ) -> None: ...
    def save_world(self, world: str, root: Path, rel: str) -> None: ...
    def telemetry_argv(self, topic: str) -> list[str]: ...


# --- environment and subprocesses -------------------------------------------------------------


def passthrough_names() -> tuple[str, ...]:
    """Variable NAMES from ``solus/env.allow`` (one per line, ``#`` comments)."""
    names: list[str] = []
    for line in ENV_ALLOW_FILE.read_text().splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return tuple(names)


def sim_child_env(home: Path | None = None) -> dict[str, str]:
    """Scrubbed base plus the named passthrough, read from this process's (already scrubbed)
    environment; ``HOME`` only when the caller provides one."""
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    for name in passthrough_names():
        value = os.environ.get(name)
        if value:
            env[name] = value
    if home is not None:
        env["HOME"] = str(home)
    return env


def run_argv(argv: list[str], timeout: float) -> Completed:
    """The production :data:`CliRunner`: argv list, no shell, scrubbed env, stdin closed."""
    try:
        done = subprocess.run(  # noqa: S603 — argv list, pinned binary, no shell
            argv,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=sim_child_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as error:
        raise CliError(argv, f"{Path(argv[0]).name} timed out after {timeout:g}s") from error
    except OSError as error:
        raise CliError(argv, f"cannot execute {Path(argv[0]).name}") from error
    return Completed(
        tuple(argv),
        done.returncode,
        done.stdout.decode("utf-8", "replace"),
        done.stderr.decode("utf-8", "replace"),
    )


def spawn_process(argv: list[str], *, home: Path) -> subprocess.Popen[bytes]:
    """A simulator server in its own session (killed by process group by the owner only)."""
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(  # noqa: S603 — argv list, pinned binary, no shell
        argv,
        cwd=home,
        env=sim_child_env(home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def redact_paths(text: str) -> str:
    """Every absolute path in simulator output reduced to its last component."""
    return _ABS_PATH.sub(lambda m: Path(m.group()).name or "/", text)


def stderr_detail(stderr: str, fallback: str = "no output") -> str:
    """The last stderr line, path-redacted and bounded: the only stderr that reaches a reason."""
    lines = stderr.strip().splitlines()
    return redact_paths(lines[-1].strip())[:MAX_REASON_CHARS] if lines else fallback


# --- argv guards -----------------------------------------------------------------------------


def check_name(value: str) -> str:
    """A plain identifier: never option-shaped, never text-format syntax."""
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError(f"unsafe name {value!r}")
    return value


def name_ok(value: object) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def check_topic(value: str) -> str:
    if not isinstance(value, str) or _TOPIC.fullmatch(value) is None:
        raise ValueError(f"unsafe topic {value!r}")
    return value


def check_abs_path(path: Path) -> str:
    """An absolute path safe inside argv and a text-format string literal."""
    text = str(path)
    if not path.is_absolute() or any(c in text for c in '"\\\n\r') or not text.isprintable():
        raise ValueError("path must be absolute and plain")
    return text


def fmt_float(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return repr(number)


def finite(value: object) -> float | None:
    """A simulator number as a finite float, else ``None`` (diverged physics prints nan/inf;
    ``json.dumps(allow_nan=False)`` on the wire would raise on it)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def decimate(items: Sequence[Any], limit: int) -> list[Any]:
    """At most ``limit`` evenly spaced items, first and last kept."""
    if len(items) <= limit:
        return list(items)
    step = (len(items) - 1) / (limit - 1)
    return [items[round(i * step)] for i in range(limit)]


# --- protobuf text format ---------------------------------------------------------------------


def parse_text_format(text: str, *, max_depth: int = 16) -> dict[str, Any]:
    """``google::protobuf::TextFormat`` output → nested dicts; repeated keys become lists.
    Stray tokens (the conda build's ``goo.gle/debug*`` markers, unbalanced braces) are skipped."""
    if len(text) > MAX_TEXT_FORMAT_BYTES:
        raise ValueError("text-format output too large")
    doc, _ = _text_message(_TOKEN.findall(text), 0, 0, max_depth)
    return doc


def parse_cli_text(argv: Sequence[str], text: str) -> dict[str, Any]:
    """:func:`parse_text_format` over a CLI's stdout; its size/depth refusals become
    :class:`CliError` so nothing but the wire exceptions leaves an adapter."""
    try:
        return parse_text_format(text)
    except ValueError as error:
        tool = " ".join([Path(argv[0]).name, *argv[1:2]])
        raise CliError(argv, f"{tool} answered unparseable text format") from error


def text_items(doc: Mapping[str, Any], key: str) -> list[Any]:
    """The values of a possibly repeated field: ``[]``, ``[one]`` or the list."""
    value = doc.get(key)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text_message(
    tokens: list[str], index: int, depth: int, max_depth: int
) -> tuple[dict[str, Any], int]:
    if depth > max_depth:
        raise ValueError("text-format nesting too deep")
    doc: dict[str, Any] = {}
    while index < len(tokens):
        key = tokens[index]
        if key == "}":
            return doc, index + 1
        if key in ("{", ":") or index + 1 >= len(tokens):
            index += 1
            continue
        nxt = tokens[index + 1]
        opens_block = nxt == "{" or (nxt == ":" and tokens[index + 2 : index + 3] == ["{"])
        if opens_block:
            start = index + 2 if nxt == "{" else index + 3
            value, index = _text_message(tokens, start, depth + 1, max_depth)
        elif nxt == ":" and index + 2 < len(tokens):
            value, index = _text_scalar(tokens[index + 2]), index + 3
        else:
            index += 1
            continue
        _text_append(doc, key, value)
    return doc, index


def _text_append(doc: dict[str, Any], key: str, value: Any) -> None:
    if key not in doc:
        doc[key] = value
    elif isinstance(doc[key], list):
        doc[key].append(value)
    else:
        doc[key] = [doc[key], value]


def _unescape_one(match: re.Match[bytes]) -> bytes:
    esc = match.group(1)
    if esc[:1] == b"x" and len(esc) > 1:
        return bytes([int(esc[1:], 16)])
    if esc[:1].isdigit():
        value = int(esc, 8)
        return bytes([value]) if value < 256 else match.group(0)
    return _SIMPLE_ESCAPES.get(esc, match.group(0))  # unknown escape: kept literally


def _text_scalar(piece: str) -> Any:
    if piece[:1] in ('"', "'") and len(piece) >= 2:
        body = piece[1:-1] if piece[-1] == piece[0] else piece[1:]
        return _ESCAPE.sub(_unescape_one, body.encode("utf-8", "surrogateescape")).decode(
            "utf-8", "replace"
        )
    if piece in ("true", "false"):
        return piece == "true"
    try:
        return int(piece)
    except ValueError:
        pass
    try:
        return float(piece)
    except ValueError:
        return piece
