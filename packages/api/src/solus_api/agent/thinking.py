"""SOLUSDEV-326 — SOL's thought summary, streamed as `thinking` frames.

The provider adapters yield `Thinking` pieces (orchestration/providers.py) only on SOL's answer
rounds. A piece is model output, untrusted (CLAUDE.md §7), and a delta can end in the middle of a
word — or of a credential the model is quoting from synced content. `redact_text` judges whole
whitespace-split tokens and `label: value` assignments, so masking each delta on its own would let
the two halves of a key — or a label and its value — pass. `ThinkingRelay` therefore holds text back
until a sentence or line ends, never cuts after a secret label still waiting for its value
(`PENDING_SECRET_LABEL`), masks each release WHOLE, then cuts the masked text into frames of at most
`THINKING_CHUNK_CAP` at whitespace, and stops for the turn at `THINKING_TURN_CAP`. One relay spans
every round of a turn, so the cap is the turn's, not the round's. Nothing on the server reads a
frame back.
"""

from __future__ import annotations

import re
from typing import Final

from solus_api.agent.stream import (
    THINKING_CHUNK_CAP,
    THINKING_TURN_CAP,
    AgentEvent,
    AgentEventType,
)
from solus_api.agent.tools.untrusted import PENDING_SECRET_LABEL, redact_text

#: Held text is released once it reaches this many characters AND ends a sentence or line.
_RELEASE_AT: Final = 60
#: Past this many held characters with no sentence end, release through the last whitespace.
_FORCE_AT: Final = 600
#: A sentence end ('. ', '? ', '! ') or a line end: a safe place to cut, outside any token.
_BOUNDARY: Final = re.compile(r"[.?!]\s|\n")
_WHITESPACE: Final = re.compile(r"\s")


def _last_cut(text: str, pattern: re.Pattern[str]) -> int:
    """The index just past the last `pattern` match in `text`, or 0 when there is none."""
    ends = [match.end() for match in pattern.finditer(text)]
    return ends[-1] if ends else 0


def _label_safe(text: str, cut: int) -> int:
    """`cut` moved back before any secret label that would end the released text without its
    value, so the label waits for the value and both reach `redact_text` together."""
    while cut and (pending := PENDING_SECRET_LABEL.search(text, 0, cut)) is not None:
        cut = pending.start()
    return cut


def _pieces(text: str, size: int) -> list[str]:
    """`text` cut into pieces of at most `size`, each cut at whitespace where there is any."""
    pieces: list[str] = []
    while len(text) > size:
        cut = _last_cut(text[:size], _WHITESPACE) or size
        pieces.append(text[:cut])
        text = text[cut:]
    return [*pieces, text] if text else pieces


class ThinkingRelay:
    """One turn's thought summary, as masked and bounded `thinking` frames. `feed` each piece as
    it arrives; `flush` when the model starts answering, and at the end of each round."""

    def __init__(self) -> None:
        self._held = ""
        #: Characters this turn has streamed (after masking).
        self.used = 0

    @property
    def spent(self) -> bool:
        return self.used >= THINKING_TURN_CAP

    def feed(self, text: str) -> list[AgentEvent]:
        if self.spent:
            return []
        self._held += text
        cut = _last_cut(self._held, _BOUNDARY) if len(self._held) >= _RELEASE_AT else 0
        if not cut and len(self._held) > _FORCE_AT:
            cut = _last_cut(self._held, _WHITESPACE) or len(self._held)
        return self._release(_label_safe(self._held, cut))

    def flush(self) -> list[AgentEvent]:
        return self._release(len(self._held))

    def discard(self) -> None:
        """Drop text held back and never sent (a refused round that is asked again)."""
        self._held = ""

    def _release(self, cut: int) -> list[AgentEvent]:
        released, self._held = self._held[:cut], self._held[cut:]
        events: list[AgentEvent] = []
        # Masked whole BEFORE it is cut into frames, so no frame boundary splits what redaction
        # judges together; each frame then fits the cap without being cut again.
        for piece in _pieces(redact_text(released), THINKING_CHUNK_CAP):
            text = piece[: THINKING_TURN_CAP - self.used]
            if not text:
                self._held = ""
                break
            self.used += len(text)
            events.append(AgentEvent(type=AgentEventType.THINKING, data={"text": text}))
        return events
