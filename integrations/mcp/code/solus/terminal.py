"""Terminal text of interactive processes (docs/api/code-command-execution.md §11.1).

PTY output is decoded as UTF-8 with replacement; ANSI CSI/OSC/DCS and other escape
sequences (7- and 8-bit) and C0 controls other than `\\n`/`\\t` are removed; `\\r\\n`
becomes `\\n` and a lone `\\r` ends the line. Complete lines go to the caller's ring
(the `LineOutput` 2048-char rule applies); the trailing partial line is held and
exposed as `pending_line` (≤ 512 chars). Prompt detection, the bounded prompt tail and
input validation live here too. Pure apart from the master-fd write in `write_input`.
"""

import codecs
import os
import re
import select
import time
from collections.abc import Callable, Iterable

from .progress import MAX_LINE, SUPPRESSED

PENDING_CHARS = 512
TAIL_LINES = 5
TAIL_CHARS = 1024
QUIET_SECONDS = 1.5
MAX_INPUT_CHARS = 1024
#: An unterminated OSC/DCS string stops being discarded after this many chars.
MAX_STRING = 4096
INPUT_SECONDS = 2.0
INPUT_REFUSAL = (
    f"text must be at most {MAX_INPUT_CHARS} printable characters with no control characters"
)
PROMPT = re.compile(r"press (enter|return|any key)|\[y/n\]|\(y/n\)|continue\?", re.IGNORECASE)
PROMPT_ENDINGS = (":", "?", ">")

_TEXT, _ESC, _ESC_INTER, _CSI, _STRING, _STRING_ESC = range(6)
_ESC_CHAR = "\x1b"
#: 8-bit C1 introducers (as decoded code points).
_C1_CSI = "\x9b"
_C1_STRINGS = frozenset("\x90\x98\x9d\x9e\x9f")
_C1_ST = "\x9c"
_ESC_STRINGS = frozenset("]PX^_")


def looks_like_prompt(line: str) -> bool:
    """§11.1 prompt patterns on one line (case-insensitive, trimmed)."""
    text = line.strip()
    return bool(text) and (PROMPT.search(text) is not None or text.endswith(PROMPT_ENDINGS))


def _clean(text: str) -> str:
    return "".join(
        " " if char == "\t" else char for char in text if char in "\n\t" or char.isprintable()
    )


def prompt_tail(lines: Iterable[str], pending: str) -> str:
    """The last ≤ 5 lines plus the pending line, controls removed, ≤ 1024 chars."""
    recent = list(lines)[-TAIL_LINES:]
    return _clean("".join(recent) + pending)[-TAIL_CHARS:]


def input_refusal(text: object) -> str | None:
    """Why `text` may not be sent to a process (None when it may)."""
    if not isinstance(text, str) or len(text) > MAX_INPUT_CHARS or not text.isprintable():
        return INPUT_REFUSAL
    return None


def write_input(fd: int, data: bytes, seconds: float = INPUT_SECONDS) -> int:
    """Write `data` to a non-blocking master within `seconds`; bytes written."""
    deadline = time.monotonic() + seconds
    sent = 0
    while sent < len(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _, writable, _ = select.select([], [fd], [], remaining)
        if not writable:
            break
        try:
            sent += os.write(fd, data[sent:])
        except BlockingIOError:
            continue
    return sent


class TerminalText:
    """One interactive process's stateful cleaner: bytes in, complete lines out."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._state = _TEXT
        self._string_chars = 0
        self._line = ""
        self._discard = False
        self._cr = False
        self._answer_mark: int | None = None
        self.last_line = ""
        self.last_line_answered = False

    @property
    def pending_line(self) -> str:
        return "" if self._discard else self._line[-PENDING_CHARS:]

    def feed(self, data: bytes) -> None:
        for char in self._decoder.decode(data):
            self._char(char)

    def finish(self) -> None:
        for char in self._decoder.decode(b"", final=True):
            self._char(char)
        if self._cr:
            self._end_line()
        elif self._line and not self._discard:
            self._emit(self._line)
        self._line, self._discard, self._cr = "", False, False

    def mark_answered(self, chars: int) -> None:
        """Input was sent: the current line (plus its echo) no longer counts as a prompt."""
        self._answer_mark = len(self._line) + chars

    def prompting(self) -> bool:
        """The held partial line is unanswered output, or (none held) the last complete
        line was unanswered and looks like a prompt."""
        if self._line and not self._discard:
            mark = self._answer_mark
            return mark is None or len(self._line) > mark
        return not self.last_line_answered and looks_like_prompt(self.last_line)

    # --- the state machine ------------------------------------------------------------

    def _char(self, char: str) -> None:
        state = self._state
        if state == _TEXT:
            self._text(char)
        elif state == _ESC:
            self._escape(char)
        elif state == _ESC_INTER:
            if not "\x20" <= char <= "\x2f":
                self._state = _TEXT
        elif state == _CSI:
            if not "\x20" <= char <= "\x3f":
                self._state = _TEXT
                if not "\x40" <= char <= "\x7e":
                    self._text(char)
        else:
            self._string(char)

    def _escape(self, char: str) -> None:
        if char == _ESC_CHAR:
            return
        if char == "[":
            self._state = _CSI
        elif char in _ESC_STRINGS:
            self._state, self._string_chars = _STRING, 0
        elif "\x20" <= char <= "\x2f":
            self._state = _ESC_INTER
        else:
            self._state = _TEXT
            if char < " ":
                self._text(char)  # a stray ESC before a control: keep the control

    def _string(self, char: str) -> None:
        if char in ("\x07", _C1_ST) or (self._state == _STRING_ESC and char == "\\"):
            self._state = _TEXT
            return
        self._state = _STRING_ESC if char == _ESC_CHAR else _STRING
        self._string_chars += 1
        if self._string_chars > MAX_STRING:
            self._state = _TEXT

    def _text(self, char: str) -> None:
        if self._cr:
            self._cr = False
            self._end_line()
            if char == "\n":
                return
        if char == _ESC_CHAR:
            self._state = _ESC
        elif char == _C1_CSI:
            self._state = _CSI
        elif char in _C1_STRINGS:
            self._state, self._string_chars = _STRING, 0
        elif char == "\r":
            self._cr = True
        elif char == "\n":
            self._end_line()
        elif char == "\t" or char.isprintable() or char == " ":
            self._add(char)

    def _add(self, char: str) -> None:
        if self._discard:
            return
        self._line += char
        if len(self._line) > MAX_LINE:
            self._line, self._discard = "", True
            self._emit(SUPPRESSED)

    def _end_line(self) -> None:
        if not self._discard:
            self._emit(self._line + "\n")
        self.last_line = "" if self._discard else self._line
        self.last_line_answered = self._answer_mark is not None
        self._line, self._discard, self._answer_mark = "", False, None
