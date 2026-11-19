"""JSON Lines protocol — mcp-fork-runtime.md §6 against the golden fixtures."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from solus_companion.runtime.protocol import (
    MAX_LINE_BYTES,
    CandidateLine,
    DoneLine,
    Emitter,
    ErrorLine,
    ForkResultLine,
    ProgressLine,
    StatusLine,
    clip,
    encode_line,
    parse_line,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mcp_runtime"
GOLDEN = sorted(p for p in FIXTURES.glob("*.jsonl") if p.name != "malformed.jsonl")


def _lines(path: Path) -> list[bytes]:
    return [line + b"\n" for line in path.read_bytes().splitlines()]


@pytest.mark.parametrize("fixture", GOLDEN, ids=lambda p: p.name)
def test_every_golden_line_parses_and_round_trips_byte_for_byte(fixture: Path) -> None:
    for raw in _lines(fixture):
        parsed = parse_line(raw)
        assert parsed is not None, raw
        assert encode_line(parsed) == raw


def test_golden_files_end_with_exactly_one_done() -> None:
    for fixture in GOLDEN:
        parsed = [parse_line(raw) for raw in _lines(fixture)]
        assert isinstance(parsed[-1], DoneLine)
        assert sum(isinstance(p, DoneLine) for p in parsed) == 1


def test_malformed_fixture_drops_five_and_keeps_two() -> None:
    parsed = [parse_line(raw) for raw in _lines(FIXTURES / "malformed.jsonl")]
    kept = [p for p in parsed if p is not None]
    assert parsed.count(None) == 5
    assert [type(p) for p in kept] == [StatusLine, DoneLine]


@pytest.mark.parametrize(
    "raw",
    [
        b"[1,2]\n",
        b'{"v":1,"type":"done","outcome":"ok","ok":1.0,"failed":0,"skipped":0}\n',
        b'{"v":1,"type":"done","outcome":"ok","ok":-1,"failed":0,"skipped":0}\n',
        b'{"v":1,"type":"done","outcome":"ok","ok":1,"failed":0,"skipped":0,"x":1}\n',
        b'{"v":1,"type":"status","fork":"Bad","state":"ready","detail":null,'
        b'"base_version":null,"managed":false}\n',
        b'{"v":1,"type":"error","error_code":"made_up","message":""}\n',
        b"\xff\xfe\n",
    ],
)
def test_lines_outside_the_schema_are_dropped(raw: bytes) -> None:
    assert parse_line(raw) is None


def test_status_detail_is_a_needs_setup_code() -> None:
    line = StatusLine(
        fork="kicad",
        state="needs_setup",
        detail="needs_setup:stamp_mismatch",
        base_version=None,
        managed=False,
    )
    assert parse_line(encode_line(line) or b"") == line


def test_emitter_writes_bounded_lines_only() -> None:
    out = io.BytesIO()
    emitter = Emitter(out)
    emitter.emit(ProgressLine(fork=None, step="download", done=1, total=None))
    emitter.emit(
        CandidateLine(
            path="/" + "p" * 5000,
            version=None,
            implementation="unknown",
            source="path",
            supported=False,
            reason="python_probe_failed",
        )
    )
    emitter.emit(ErrorLine(error_code="internal", message=clip("é" * 1000)))
    lines = out.getvalue().splitlines(keepends=True)
    assert len(lines) == 2  # the oversize candidate is withheld, never truncated into a lie
    assert emitter.withheld == 1
    for line in lines:
        assert len(line) <= MAX_LINE_BYTES
        assert parse_line(line) is not None


def test_clip_bounds_and_strips_control_characters() -> None:
    clipped = clip("a\x00b\nc" + "x" * 400)
    assert len(clipped) == 300
    assert "\x00" not in clipped and "\n" not in clipped
    assert clipped.endswith("…")
    assert clip("short") == "short"


def test_fork_result_message_is_capped_by_the_model() -> None:
    with pytest.raises(ValueError):
        ForkResultLine(fork="kicad", outcome="ok", error_code=None, message="x" * 301)


def test_encode_is_compact_and_starts_with_version() -> None:
    raw = encode_line(DoneLine(outcome="ok", ok=0, failed=0, skipped=0))
    assert raw is not None
    assert raw.startswith(b'{"v":1,"type":"done"')
    assert json.loads(raw)["v"] == 1
