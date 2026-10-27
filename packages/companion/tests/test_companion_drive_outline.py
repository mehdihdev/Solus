"""Outline geometry (docs/architecture/sol-drive.md §3, slice 3): after an ok
identify, capture or act that carries window bounds, the companion writes one
`drive_window` line to stdout for the desktop's amber outline — numbers only."""

import base64
import io
import json
import math
from pathlib import Path
from typing import Any

import pytest
from solus_companion.drive.helper import DriveHelper
from solus_companion.drive.outline import outline_line, stdout_writer
from solus_companion.drive.server import DriveServer
from solus_companion.watch import saved_design_fingerprint
from test_companion_drive import PNG, echo_helper, workspace_of

BOUNDS = {"x": 10, "y": 20.5, "width": 800, "height": 600}
LINE = '{"type":"drive_window","bounds":{"x":10,"y":20.5,"width":800,"height":600}}'
ACT = {"bundle": "org.kicad.kicad", "window": 7, "since": 1.0, "verb": "wait", "ms": 0}
CAPTURE = {"bundle": "org.kicad.kicad", "window": 7}


def outlined(tmp_path: Path, reply: dict[str, Any]) -> tuple[DriveServer, list[str]]:
    lines: list[str] = []
    helper = echo_helper(tmp_path, reply)
    server = DriveServer(
        DriveHelper(helper),
        enabled=True,
        workspace=workspace_of(helper),
        platform="darwin",
        emit=lines.append,
    )
    server._designs_at_bind = saved_design_fingerprint(server.workspace)
    return server, lines


def capture_reply(**extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "png": base64.b64encode(PNG).decode(),
        "imageWidth": 1568,
        "imageHeight": 1176,
        "pointsWidth": 800,
        "pointsHeight": 600,
        **extra,
    }


# --- the line itself -------------------------------------------------------------


def test_outline_line_is_exactly_the_four_numbers() -> None:
    assert outline_line(BOUNDS) == LINE
    assert json.loads(LINE) == {"type": "drive_window", "bounds": BOUNDS}


def test_outline_line_drops_extra_keys_never_forwarding_text() -> None:
    hostile = {**BOUNDS, "title": "secret.kicad_sch", "bundleId": "org.kicad.kicad"}
    line = outline_line(hostile)
    assert line == LINE
    assert "secret" not in line and "kicad" not in line


@pytest.mark.parametrize(
    "bounds",
    [
        None,
        "10,20,800,600",
        [10, 20, 800, 600],
        {"x": 10, "y": 20, "width": 800},
        {**BOUNDS, "x": "10"},
        {**BOUNDS, "y": True},
        {**BOUNDS, "width": math.nan},
        {**BOUNDS, "height": math.inf},
        {**BOUNDS, "x": -math.inf},
        {**BOUNDS, "width": 0},
        {**BOUNDS, "height": -5},
        {**BOUNDS, "x": 10**9},
        {**BOUNDS, "width": None},
    ],
)
def test_malformed_bounds_give_no_line(bounds: Any) -> None:
    assert outline_line(bounds) is None


def test_stdout_writer_writes_one_terminated_line_and_flushes() -> None:
    class Stream(io.StringIO):
        flushed = 0

        def flush(self) -> None:
            self.flushed += 1

    stream = Stream()
    stdout_writer(stream)(LINE)
    assert stream.getvalue() == LINE + "\n"
    assert stream.flushed == 1


def test_stdout_writer_survives_a_closed_stream() -> None:
    stream = io.StringIO()
    stream.close()
    stdout_writer(stream)(LINE)  # the desktop hung up: never fail the tool call


# --- when the server writes it ------------------------------------------------------


async def test_ok_identify_with_a_window_writes_its_bounds(tmp_path: Path) -> None:
    server, lines = outlined(
        tmp_path, {"ok": True, "allowed": True, "window": {"id": 7, "bounds": BOUNDS}}
    )
    assert not (await server.call_tool("identify", {})).isError
    assert lines == [LINE]


async def test_identify_without_a_window_writes_nothing(tmp_path: Path) -> None:
    server, lines = outlined(tmp_path, {"ok": True, "allowed": False})
    await server.call_tool("identify", {})
    assert lines == []


async def test_ok_capture_writes_its_bounds_and_keeps_them_out_of_the_metadata(
    tmp_path: Path,
) -> None:
    server, lines = outlined(tmp_path, capture_reply(bounds=BOUNDS))
    result = await server.call_tool("capture", CAPTURE)
    assert not result.isError
    assert lines == [LINE]


async def test_a_bad_capture_writes_nothing(tmp_path: Path) -> None:
    server, lines = outlined(tmp_path, {**capture_reply(bounds=BOUNDS), "png": "bm90IGEgcG5n"})
    assert (await server.call_tool("capture", CAPTURE)).isError
    assert lines == []


async def test_ok_act_writes_its_bounds(tmp_path: Path) -> None:
    server, lines = outlined(tmp_path, {"ok": True, "finishedAt": 2.0, "bounds": BOUNDS})
    assert not (await server.call_tool("act", ACT)).isError
    assert lines == [LINE]


async def test_a_refused_act_writes_nothing(tmp_path: Path) -> None:
    server, lines = outlined(tmp_path, {"ok": False, "code": "moved", "bounds": BOUNDS})
    assert (await server.call_tool("act", ACT)).isError
    assert lines == []


async def test_malformed_bounds_in_a_reply_write_nothing_and_still_succeed(
    tmp_path: Path,
) -> None:
    server, lines = outlined(
        tmp_path, {"ok": True, "finishedAt": 2.0, "bounds": {**BOUNDS, "width": "wide"}}
    )
    assert not (await server.call_tool("act", ACT)).isError
    assert lines == []


def test_the_default_writer_is_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    server = DriveServer(None, enabled=True, workspace=tmp_path, platform="darwin")
    server.emit(LINE)
    assert capsys.readouterr().out == LINE + "\n"
