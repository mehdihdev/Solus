"""SOLUSDEV-326: `ThinkingRelay` — a turn's thought summary as masked, bounded frames."""

from __future__ import annotations

from collections.abc import Sequence

from solus_api.agent.stream import THINKING_CHUNK_CAP, THINKING_TURN_CAP, AgentEvent
from solus_api.agent.thinking import ThinkingRelay

_SECRET = "sk-ant-api03-" + "A" * 40


def _joined_text(events: Sequence[AgentEvent]) -> str:
    return "".join(e.data["text"] for e in events)


def test_relay_holds_text_until_a_sentence_ends_so_a_secret_is_masked_whole() -> None:
    relay = ThinkingRelay()
    half = len(_SECRET) // 2

    early = relay.feed(f"The key is {_SECRET[:half]}")
    late = relay.feed(f"{_SECRET[half:]}. Next I read the netlist and the pin map for U3. ")
    rest = relay.flush()

    assert early == []
    streamed = _joined_text([*late, *rest])
    assert _SECRET not in streamed
    assert streamed.startswith("The key is [REDACTED]")
    assert "netlist" in streamed


def test_relay_stops_at_the_turn_cap() -> None:
    relay = ThinkingRelay()
    sentence = "word " * 40 + ". "
    out: list[AgentEvent] = []
    for _ in range(THINKING_TURN_CAP // len(sentence) + 20):
        out += relay.feed(sentence)
    out += relay.flush()

    assert len(_joined_text(out)) <= THINKING_TURN_CAP
    assert all(len(e.data["text"]) <= THINKING_CHUNK_CAP for e in out)


def test_relay_spans_rounds_against_one_cap() -> None:
    relay = ThinkingRelay()
    relay.feed("a" * 10 + ". ")
    first = relay.flush()
    relay.feed("b" * 10 + ". ")
    second = relay.flush()

    assert _joined_text(first).startswith("a") and _joined_text(second).startswith("b")
    assert relay.used == len(_joined_text(first)) + len(_joined_text(second))


def test_relay_without_a_sentence_end_releases_past_the_force_point_at_whitespace() -> None:
    relay = ThinkingRelay()

    out = relay.feed("word " * 200)

    assert out and _joined_text(out).endswith(" ")
    assert all(len(e.data["text"]) <= THINKING_CHUNK_CAP for e in out)


def test_relay_cuts_one_long_release_into_frames_at_whitespace() -> None:
    relay = ThinkingRelay()

    out = relay.feed("token " * 1000 + ". ")

    assert len(out) > 1
    assert all(not e.data["text"].startswith("oken") for e in out)


def test_spent_relay_ignores_more_input() -> None:
    relay = ThinkingRelay()
    relay.used = THINKING_TURN_CAP

    assert relay.feed("More thinking here, plenty of it. " * 5) == []
    assert relay.flush() == []
