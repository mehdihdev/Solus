"""JSON Lines protocol of `solus-companion runtime …` — mcp-fork-runtime.md §6.

The models ARE the schema: the emitter only writes lines built from them, and
`parse_line` applies the reader rules (drop oversize / non-JSON / wrong `v` /
unknown `type` / any schema violation). The golden fixtures round-trip
byte-for-byte through `parse_line` → `encode_line`."""

import json
import logging
import re
from typing import Annotated, BinaryIO, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    ValidationError,
)

from solus_companion.runtime.errors import DetailCode, ErrorCode
from solus_companion.runtime.roots import FORK_NAME_PATTERN

logger = logging.getLogger("solus.companion.runtime")

MAX_LINE_BYTES = 4096
MAX_MESSAGE_CHARS = 300

ForkName = Annotated[str, Field(pattern=FORK_NAME_PATTERN)]
Count = Annotated[StrictInt, Field(ge=0)]
#: Reported versions are short and printable; the SUPPORTED shape is narrower (probe.py).
Version = Annotated[str, Field(pattern=r"^[0-9][0-9A-Za-z.+-]{0,31}$")]
SupportedVersion = Annotated[str, Field(pattern=r"^3\.1[23]\.\d+$")]
Message = Annotated[str, Field(max_length=MAX_MESSAGE_CHARS)]


class _Line(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1


class CandidateLine(_Line):
    type: Literal["candidate"] = "candidate"
    #: Bounded only by the OS here; a line that cannot fit is withheld by the emitter.
    path: Annotated[str, Field(min_length=1, max_length=32768)]
    version: Version | None
    implementation: Literal["cpython", "pypy", "unknown"]
    source: Literal["path", "py_launcher", "registry", "known_location", "managed"]
    supported: StrictBool
    reason: ErrorCode | None


class StatusLine(_Line):
    type: Literal["status"] = "status"
    fork: ForkName
    state: Literal["ready", "needs_setup", "unsupported_platform"]
    detail: DetailCode | None
    base_version: SupportedVersion | None
    managed: StrictBool


class ProgressLine(_Line):
    type: Literal["progress"] = "progress"
    fork: ForkName | None
    step: Literal["download", "verify", "extract", "venv", "install", "check", "stamp"]
    done: Count
    total: Count | None


class ForkResultLine(_Line):
    type: Literal["fork_result"] = "fork_result"
    fork: ForkName
    outcome: Literal["ok", "failed", "skipped"]
    error_code: ErrorCode | None
    message: Message


class ErrorLine(_Line):
    type: Literal["error"] = "error"
    error_code: ErrorCode
    message: Message


class DoneLine(_Line):
    type: Literal["done"] = "done"
    outcome: Literal["ok", "partial", "failed", "cancelled"]
    ok: Count
    failed: Count
    skipped: Count


RuntimeLine = Annotated[
    CandidateLine | StatusLine | ProgressLine | ForkResultLine | ErrorLine | DoneLine,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[RuntimeLine] = TypeAdapter(RuntimeLine)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clip(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    """A message safe for the wire: control characters replaced, length capped."""
    flat = _CONTROL.sub(" ", text)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def parse_line(raw: bytes) -> RuntimeLine | None:
    """One stdout line, or None when the reader rules say drop it."""
    if len(raw) > MAX_LINE_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:  # includes UnicodeDecodeError
        return None
    # `v` must be PRESENT, not merely defaulted (the model default serves emitters).
    if not isinstance(data, dict) or "v" not in data:
        return None
    try:
        return _ADAPTER.validate_python(data)
    except ValidationError:
        return None


def encode_line(line: RuntimeLine) -> bytes | None:
    """Compact UTF-8 JSON + newline, or None if it would exceed the line cap."""
    body = json.dumps(line.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False)
    raw = (body + "\n").encode("utf-8")
    return raw if len(raw) <= MAX_LINE_BYTES else None


class Emitter:
    """The one writer of stdout. A line that cannot fit is WITHHELD (logged to
    stderr) — a truncated path would be a lie the desktop might act on."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.withheld = 0

    def emit(self, line: RuntimeLine) -> bool:
        raw = encode_line(line)
        if raw is None:
            self.withheld += 1
            logger.warning("withheld an oversize %s line", line.type)
            return False
        self._stream.write(raw)
        self._stream.flush()
        return True
