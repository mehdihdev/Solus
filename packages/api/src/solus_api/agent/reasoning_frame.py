"""SOLUSDEV-321 P7 — the `<reasoning>` block SOL writes before it proposes a change.

The Build system prompt asks for one `<reasoning>{json}</reasoning>` block ahead of a proposal
(agent/prompt.py). The block is model OUTPUT, untrusted (CLAUDE.md §7), so it never reaches the
chat as text: `ReasoningParser` holds the text back from the moment a tag could be starting, takes
the block out of what streams as `token` frames — and `strip_reasoning` out of the closing
`message` — and makes it ONE `reasoning` frame when its JSON has the exact shape
(`AgentEvent.reasoning` masks and cuts every string). Anything else is dropped with one debug line
and never streamed: a malformed or oversize block, a second block in the same text, and a block
still open when the text ends — unless its body holds no `{`, does not open with `[` and never ran
past the cap, which is prose quoting the tag and streams back as written. A block's body is held
to `REASONING_BLOCK_CAP` characters plus a closing tag's length, so one that never closes cannot
grow the buffer. Nothing on the server reads
the frame back: it picks no tool, mode, scope or permission.
"""

from __future__ import annotations

import logging
import re
import string
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.stream import (
    REASONING_ITEMS_CAP,
    REASONING_PROPOSING_CAP,
    REASONING_TEXT_CAP,
    AgentEvent,
    AgentEventType,
)

logger = logging.getLogger("solus.agent.reasoning_frame")

#: The most characters a block's body may hold between its tags.
REASONING_BLOCK_CAP: Final = 4 * 1024
_OPEN: Final = "<reasoning>"
_CLOSE: Final = "</reasoning>"
#: ASCII case only, so a case fold never changes a string's length and shifts an offset.
_OPEN_TAG: Final = re.compile(re.escape(_OPEN), re.IGNORECASE | re.ASCII)
_CLOSE_TAG: Final = re.compile(re.escape(_CLOSE), re.IGNORECASE | re.ASCII)
_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

_Text = Annotated[str, Field(max_length=REASONING_TEXT_CAP)]


class _RuledOutShape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    what: _Text
    why: _Text


class _ReasoningShape(BaseModel):
    """The block's one JSON shape: anything else, or anything past a bound, is malformed."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    considered: list[_Text] = Field(max_length=REASONING_ITEMS_CAP)
    ruled_out: list[_RuledOutShape] = Field(max_length=REASONING_ITEMS_CAP)
    proposing: str = Field(max_length=REASONING_PROPOSING_CAP)


class ReasoningParser:
    """One model text's `token` frames with its `<reasoning>` blocks taken out, and the first
    block's `reasoning` frame when it is well formed. `feed` each chunk as it arrives, then
    `flush` once at the end of the text.

    ponytail: the first closing tag ends a block, so a JSON string quoting one cuts the block
    short — dropped as malformed, and the rest of its JSON streams as text; a string-aware scan
    is the upgrade if a model ever does that."""

    def __init__(self) -> None:
        #: Text not streamed yet because a tag may be starting in it.
        self._held = ""
        #: Inside a block, its body so far (only its tail once past the cap); None outside one.
        self._body: str | None = None
        self._oversize = False
        self._blocks = 0
        #: The opening tag as written, to give back a block that turns out to be prose.
        self._opened = ""

    def feed(self, chunk: str) -> list[AgentEvent]:
        """The frames `chunk` completes (possibly none)."""
        events: list[AgentEvent] = []
        rest: str | None = chunk
        while rest is not None:
            rest = self._outside(rest, events) if self._body is None else self._inside(rest, events)
        return events

    def flush(self) -> list[AgentEvent]:
        """The end of the text: a tag that never finished starting streams as the text it was. A
        block still open is dropped, never streamed — unless it never ran past the cap, holds no
        `{` and does not open with `[`: prose quoting the tag, which streams back as written (P7
        fix 1, M3; P7 fix 2, N1)."""
        text = self._held if self._body is None else self._unclosed(self._body)
        self._held, self._body = "", None
        return [AgentEvent.token(text)] if text else []

    def _unclosed(self, body: str) -> str:
        """What a block still open at the end gives back: nothing for a cut body or one that could
        be JSON (a brace anywhere — bare, behind a code fence — or an array), else the tag and the
        body exactly as they were written."""
        if self._oversize or "{" in body or body.lstrip().startswith("["):
            _dropped("never closed")
            return ""
        return self._opened + body

    def _outside(self, chunk: str, events: list[AgentEvent]) -> str | None:
        """Stream what can start no tag; return the text after an opening tag, else None."""
        text = self._held + chunk
        match = _OPEN_TAG.search(text)
        cut = match.start() if match else len(text) - _tag_prefix(text)
        if cut:
            events.append(AgentEvent.token(text[:cut]))
        if match is None:
            self._held = text[cut:]
            return None
        self._held, self._body, self._oversize = "", "", False
        self._opened = match.group(0)
        return text[match.end() :]

    def _inside(self, chunk: str, events: list[AgentEvent]) -> str | None:
        """Hold the block's body; at its closing tag judge it and return the text after it."""
        body = (self._body or "") + chunk
        match = _CLOSE_TAG.search(body)
        if match is None:
            # Past the cap, only what could start the closing tag is kept.
            over = len(body) >= REASONING_BLOCK_CAP + len(_CLOSE)
            self._body = body[-(len(_CLOSE) - 1) :] if over else body
            self._oversize = self._oversize or over
            return None
        self._judge(body[: match.start()], events)
        self._body = None
        return body[match.end() :]

    def _judge(self, body: str, events: list[AgentEvent]) -> None:
        """A closed block: its frame when it is the text's first, within the cap, well formed."""
        self._blocks += 1
        if self._blocks > 1 or self._oversize or len(body) > REASONING_BLOCK_CAP:
            _dropped("a second block" if self._blocks > 1 else "over the cap")
            return
        try:
            shape = _ReasoningShape.model_validate_json(body)
        except ValidationError:
            _dropped("malformed")
            return
        events.append(
            AgentEvent.reasoning(
                considered=shape.considered,
                ruled_out=[row.model_dump() for row in shape.ruled_out],
                proposing=shape.proposing,
            )
        )


def _tag_prefix(text: str) -> int:
    """How many of `text`'s last characters could be the start of an opening tag."""
    tail = text[-(len(_OPEN) - 1) :].translate(_ASCII_LOWER)
    return next((n for n in range(len(tail), 0, -1) if _OPEN.startswith(tail[-n:])), 0)


def _dropped(why: str) -> None:
    """One debug line for a block that is never shown: why, never what it held."""
    logger.debug("reasoning block dropped: %s", why)


async def reasoned_tokens(chunks: AsyncIterable[str]) -> AsyncIterator[AgentEvent]:
    """A model round's text as `token` frames, and its reasoning block as one `reasoning` frame
    where the block ends — ahead of the round's calls."""
    parser = ReasoningParser()
    async for chunk in chunks:
        for event in parser.feed(chunk):
            yield event
    for event in parser.flush():
        yield event


def strip_reasoning(text: str) -> str:
    """`text` with its reasoning blocks taken out exactly as its `token` frames were: the closing
    `message` must not show what the stream withheld."""
    parser = ReasoningParser()
    events = [*parser.feed(text), *parser.flush()]
    return "".join(event.data["text"] for event in events if event.type is AgentEventType.TOKEN)
