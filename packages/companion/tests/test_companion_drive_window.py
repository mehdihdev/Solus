"""Frontmost-app driving in the companion (docs/architecture/sol-drive.md §2.2,
"Companion (A2)"): `pid` on capture/act, driving without a linked workspace,
`front.documentDir` kept local, and the saved-file watch for window-bound apps."""

import logging
from pathlib import Path
from typing import Any

import pytest
from solus_companion.drive.save_watch import document_folder, folder_fingerprint
from solus_companion.drive.server import DriveServer
from solus_companion.watch import MAX_ENTRIES
from test_companion_drive import (  # noqa: F401 — _stop_desktops is an autouse fixture
    _stop_desktops,
    calls,
    desktop_relay,
    echo_helper,
    make_helper,
    text_of,
    within,
    workspace_of,
)

TITLE = "secret-board.kicad_sch — Untrusted Title"
BOUNDS = {"x": 10, "y": 20, "width": 800, "height": 600}
CAPTURE = {"bundle": "com.example.Editor", "window": 7, "pid": 4242}
ACT = {
    "bundle": "com.example.Editor",
    "window": 7,
    "pid": 4242,
    "since": 1.0,
    "verb": "click",
    "x": 1,
    "y": 40,
}


def window_front(document_dir: str | None = "sub", **extra: Any) -> dict[str, Any]:
    return {
        "drivable": True,
        "binding": "window",
        "bundleId": "com.example.Editor",
        "name": "Editor",
        "pid": 4242,
        "windowId": 7,
        "title": TITLE,
        "bounds": BOUNDS,
        "documentDir": document_dir,
        **extra,
    }


def identify_reply(front: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": True,
        "now": 1.0,
        "unsignedDev": False,
        "trust": {"accessibility": True, "screenRecording": True},
        "front": front,
    }


def stepping_helper(
    tmp_path: Path, front: dict[str, Any] | None, *, writes: Path | None = None
) -> Path:
    """identify answers with `front`; act optionally writes `writes`, then succeeds."""
    write = f"    pathlib.Path({str(writes)!r}).write_text('changed')\n" if writes else ""
    return make_helper(
        tmp_path,
        "if argv[0] == 'identify':\n"
        f"    print(json.dumps({identify_reply(front)!r}))\n"
        "else:\n" + write + "    print(json.dumps({'ok': True, 'finishedAt': 2.0}))\n",
    )


def server_for(helper: Path, *, linked: bool = True) -> DriveServer:
    return DriveServer(
        desktop_relay(helper),
        enabled=True,
        workspace=workspace_of(helper) if linked else None,
        platform="darwin",
        emit=lambda _: None,
    )


# --- pid ------------------------------------------------------------------------------


async def test_capture_passes_pid_as_one_argument_after_the_window(tmp_path: Path) -> None:
    server = server_for(echo_helper(tmp_path, {"ok": False, "code": "x", "message": ""}))
    await server.call_tool("capture", CAPTURE)
    assert calls(tmp_path) == [
        [
            "capture",
            *within(tmp_path),
            "--bundle",
            "com.example.Editor",
            "--window",
            "7",
            "--pid",
            "4242",
            "--max-edge",
            "1568",
        ]
    ]


async def test_act_passes_pid_as_one_argument_after_the_window(tmp_path: Path) -> None:
    server = server_for(stepping_helper(tmp_path, window_front(None)))
    await server.call_tool("identify", {})
    await server.call_tool("act", ACT)
    argv = calls(tmp_path)[1]
    assert argv[:9] == [
        "act",
        *within(tmp_path),
        "--bundle",
        "com.example.Editor",
        "--window",
        "7",
        "--pid",
        "4242",
    ]
    assert all(isinstance(token, str) for token in argv)


async def test_capture_without_pid_sends_no_pid_flag(tmp_path: Path) -> None:
    server = server_for(echo_helper(tmp_path, {"ok": False, "code": "x", "message": ""}))
    await server.call_tool("capture", {"bundle": "org.kicad.kicad", "window": 7})
    assert "--pid" not in calls(tmp_path)[0]


@pytest.mark.parametrize("pid", [1, 2**31 - 1])
async def test_pid_range_edges_are_accepted(tmp_path: Path, pid: int) -> None:
    server = server_for(echo_helper(tmp_path, {"ok": False, "code": "x", "message": ""}))
    await server.call_tool("capture", {**CAPTURE, "pid": pid})
    argv = calls(tmp_path)[0]
    assert argv[argv.index("--pid") + 1] == str(pid)


@pytest.mark.parametrize("pid", [0, -1, 2**31, "4242", True, 4242.0])
@pytest.mark.parametrize("tool", ["capture", "act"])
async def test_a_bad_pid_never_reaches_the_helper(tmp_path: Path, tool: str, pid: Any) -> None:
    server = server_for(stepping_helper(tmp_path, window_front(None)))
    server._bound = True  # as after identify, so act is judged on its arguments only
    base = CAPTURE if tool == "capture" else ACT
    result = await server.call_tool(tool, {**base, "pid": pid})
    assert result.isError and text_of(result).startswith("invalid_arguments: ")
    assert calls(tmp_path) == []


def test_pid_is_in_the_advertised_schemas_with_its_range(tmp_path: Path) -> None:
    inventory = server_for(echo_helper(tmp_path, {"ok": True})).inventory()
    assert inventory is not None
    schemas = {tool["name"]: tool["input_schema"] for tool in inventory["tools"]}
    for name in ("capture", "act"):
        pid = schemas[name]["properties"]["pid"]
        integer = next(option for option in pid["anyOf"] if option.get("type") == "integer")
        assert integer["minimum"] == 1 and integer["maximum"] == 2**31 - 1
        assert "pid" not in schemas[name].get("required", [])


# --- no linked workspace -----------------------------------------------------------------


def test_without_a_workspace_drive_is_advertised_and_ready(tmp_path: Path) -> None:
    server = server_for(echo_helper(tmp_path, {"ok": True}), linked=False)
    assert server.inventory() is not None
    assert server.status_entry()["state"] == "ready"
    assert server.status_entry()["detail"] is None


async def test_without_a_workspace_no_within_is_sent(tmp_path: Path) -> None:
    server = server_for(stepping_helper(tmp_path, window_front(None)), linked=False)
    assert not (await server.call_tool("identify", {})).isError
    await server.call_tool("capture", CAPTURE)  # the stand-in has no image; argv is the point
    assert not (await server.call_tool("act", ACT)).isError
    for argv in calls(tmp_path):
        assert "--within" not in argv
    assert calls(tmp_path)[0] == ["identify"]


async def test_without_a_workspace_act_still_needs_the_identify_bind(tmp_path: Path) -> None:
    server = server_for(stepping_helper(tmp_path, window_front(None)), linked=False)
    result = await server.call_tool("act", ACT)
    assert result.isError and text_of(result).startswith("not_bound: ")
    assert calls(tmp_path) == []


# --- identify: documentDir and title stay local --------------------------------------------


async def test_identify_is_forwarded_without_document_dir_or_title(tmp_path: Path) -> None:
    server = server_for(stepping_helper(tmp_path, window_front("sub")))
    result = await server.call_tool("identify", {})
    assert not result.isError
    assert result.structuredContent is not None
    front = result.structuredContent["front"]
    assert "documentDir" not in front
    assert "title" not in front
    expected = {k: v for k, v in window_front("sub").items() if k not in ("documentDir", "title")}
    assert front == expected
    assert "documentDir" not in text_of(result)
    assert TITLE not in text_of(result)  # the window title never leaves the machine
    assert "sub" not in text_of(result).replace("subdir", "")  # the folder never leaves


async def test_identify_with_no_front_is_forwarded_as_is(tmp_path: Path) -> None:
    server = server_for(stepping_helper(tmp_path, None))
    result = await server.call_tool("identify", {})
    assert result.structuredContent == identify_reply(None)


async def test_identify_never_logs_the_window_title(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    server = server_for(stepping_helper(tmp_path, window_front("../escape")))
    await server.call_tool("identify", {})
    await server.call_tool("act", ACT)
    assert TITLE not in caplog.text
    assert "escape" not in caplog.text


# --- the saved-file watch ------------------------------------------------------------------


async def test_kicad_keeps_the_design_file_watch(tmp_path: Path) -> None:
    front = {**window_front(None), "binding": "project", "bundleId": "org.kicad.kicad"}
    helper = stepping_helper(tmp_path, front)
    ws = workspace_of(helper)
    (ws / "board.kicad_sch").write_text("(kicad_sch)")
    server = server_for(helper)
    await server.call_tool("identify", {})
    (ws / "notes.txt").write_text("not a design")
    ok = await server.call_tool("act", ACT)
    assert ok.structuredContent is not None and ok.structuredContent["designSaved"] is False
    (ws / "board.kicad_sch").write_text("(kicad_sch saved)")
    stopped = await server.call_tool("act", ACT)
    assert stopped.isError and text_of(stopped).startswith("design_saved: ")
    assert "design file" in text_of(stopped)


async def test_window_bound_with_document_dir_watches_that_folder(tmp_path: Path) -> None:
    helper = stepping_helper(tmp_path, window_front("sub"))
    ws = workspace_of(helper)
    (ws / "sub").mkdir()
    (ws / "sub" / "main.c").write_text("int main;")
    server = server_for(helper)
    await server.call_tool("identify", {})
    (ws / "elsewhere.txt").write_text("outside the document folder")
    ok = await server.call_tool("act", ACT)
    assert not ok.isError
    assert ok.structuredContent is not None and ok.structuredContent["designSaved"] is False
    (ws / "sub" / "main.c").write_text("int main(void);")  # any regular file counts
    stopped = await server.call_tool("act", ACT)
    assert stopped.isError and text_of(stopped).startswith("design_saved: ")
    assert "a file in this project changed" in text_of(stopped)
    assert len(calls(tmp_path)) == 2  # identify + the first act only


async def test_window_bound_act_that_writes_reports_design_saved(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    helper = stepping_helper(tmp_path, window_front(""), writes=ws / "new.txt")
    server = server_for(helper)
    await server.call_tool("identify", {})
    result = await server.call_tool("act", ACT)
    assert not result.isError
    assert result.structuredContent is not None and result.structuredContent["designSaved"] is True


async def test_window_bound_without_document_dir_has_the_watch_off(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    helper = stepping_helper(tmp_path, window_front(None), writes=ws / "board.kicad_sch")
    server = server_for(helper)
    await server.call_tool("identify", {})
    for _ in range(2):  # the write never stops a step: nothing is watched
        result = await server.call_tool("act", ACT)
        assert not result.isError
        assert result.structuredContent is not None
        assert result.structuredContent["designSaved"] is False


async def test_window_bound_without_a_workspace_has_the_watch_off(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.kicad_sch"
    helper = stepping_helper(tmp_path, window_front(None), writes=elsewhere)
    server = server_for(helper, linked=False)
    await server.call_tool("identify", {})
    for _ in range(2):
        result = await server.call_tool("act", ACT)
        assert not result.isError
        assert result.structuredContent is not None
        assert result.structuredContent["designSaved"] is False


@pytest.mark.parametrize("document_dir", ["../outside", "/etc", "sub/../../outside", 7, "a\x00b"])
async def test_a_document_dir_outside_the_workspace_turns_the_watch_off(
    tmp_path: Path, document_dir: Any
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    helper = stepping_helper(tmp_path, window_front(document_dir), writes=outside / "x.txt")
    server = server_for(helper)
    await server.call_tool("identify", {})
    result = await server.call_tool("act", ACT)
    assert result.structuredContent is not None and result.structuredContent["designSaved"] is False


async def test_a_new_identify_drops_the_previous_watch(tmp_path: Path) -> None:
    helper = stepping_helper(tmp_path, window_front(""))
    ws = workspace_of(helper)
    server = server_for(helper)
    await server.call_tool("identify", {})
    (ws / "a.txt").write_text("changed before the second bind")
    await server.call_tool("identify", {})
    result = await server.call_tool("act", ACT)
    assert not result.isError


# --- the folder resolution and fingerprint -------------------------------------------------


def test_document_folder_resolves_inside_the_workspace_only(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    (tmp_path / "out").mkdir()
    (ws / "link").symlink_to(tmp_path / "out")
    assert document_folder(ws, "") == ws.resolve()
    assert document_folder(ws, "sub") == (ws / "sub").resolve()
    for bad in ["link", "../out", "/tmp", "missing", None, 3, "x" * 5000]:
        assert document_folder(ws, bad) is None


def test_folder_fingerprint_sees_every_regular_file_but_the_exclusions(tmp_path: Path) -> None:
    (tmp_path / "a.c").write_text("1")
    before = folder_fingerprint(tmp_path)
    for skipped in [".git", "node_modules", ".history", "solus-artifacts"]:
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "f").write_text("x")
    (tmp_path / "_autosave-a.c").write_text("x")
    assert folder_fingerprint(tmp_path) == before
    (tmp_path / "b.txt").write_text("new")
    assert folder_fingerprint(tmp_path) != before


def test_folder_fingerprint_fails_closed_past_its_entry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_companion.drive.save_watch.MAX_ENTRIES", 3)
    for i in range(5):
        (tmp_path / f"{i}.txt").write_text("x")
    assert folder_fingerprint(tmp_path) == ""
    assert MAX_ENTRIES == 10_000


def test_folder_fingerprint_of_a_missing_folder_is_unobservable(tmp_path: Path) -> None:
    assert folder_fingerprint(tmp_path / "gone") == ""
