"""BYO-license credential relay (MCP-05 / bridge-protocol.md Addendum C).

stdin credential lines → exactly one `credential_submit` frame; inbound
`credential_ack` frames surface on the supervisor's status entries. The
hygiene invariant proven throughout: the secret VALUE (a sentinel, never a
real license) appears in NO log record on ANY path — key NAMES are allowed.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from solus_companion.channel import STOP_SUPERSEDED, run_channel
from solus_companion.config import (
    CompanionConfig,
    ServerLaunch,  # noqa: I001 — grouped with config imports
    TokenBox,
    apply_token_line,
)
from solus_companion.credentials import (
    MAX_CONTROL_FRAME_BYTES,
    MAX_PENDING_SUBMITS,
    CredentialAck,
    CredentialRelay,
    credential_submit_frame,
    parse_credential_ack,
    surface_ack,
)
from solus_companion.supervisor import ServerState, Supervisor
from websockets.asyncio.server import ServerConnection, serve

SENTINEL = "SENTINEL-NOT-A-REAL-LICENSE"
KEY_NAME = "altium_license"


def _line(server: str = "altium", secrets: dict[str, Any] | Any = None, **extra: Any) -> bytes:
    payload: dict[str, Any] = {"type": "credential", "server": server}
    payload["secrets"] = {KEY_NAME: SENTINEL} if secrets is None else secrets
    payload.update(extra)
    return json.dumps(payload).encode()


def _relay(known: frozenset[str] = frozenset({"altium"})) -> CredentialRelay:
    return CredentialRelay(known_servers=known)


def _attached_box(relay: CredentialRelay) -> TokenBox:
    box = TokenBox("tok-1")
    box.credentials = relay
    return box


def _assert_no_sentinel_logged(caplog: pytest.LogCaptureFixture) -> None:
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()


# --- stdin line → exactly one credential_submit frame -------------------------


async def test_well_formed_line_yields_exactly_one_submit_frame() -> None:
    relay = _relay()
    apply_token_line(_attached_box(relay), _line())
    assert relay.pending == 1
    frame = json.loads(await relay.next_frame())
    # Addendum C shape, exactly.
    assert frame == {
        "type": "credential_submit",
        "data": {"server": "altium", "secrets": {KEY_NAME: SENTINEL}},
    }
    assert relay.pending == 0  # exactly one — nothing else queued


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        (b'{"type":"credential","secrets":{"k":"v"}}', "malformed"),  # no server
        (_line(server=123), "malformed"),  # type: ignore[arg-type]
        (_line(server=""), "malformed"),
        (_line(server="not_discovered"), "unknown_server"),
        (b'{"type":"credential","server":"altium"}', "malformed"),  # no secrets
        (_line(secrets=[]), "malformed"),  # not an object
        (_line(secrets={}), "malformed"),  # empty
        (_line(secrets={KEY_NAME: 42}), "malformed"),  # non-string value
        (_line(secrets={KEY_NAME: None}), "malformed"),
        (_line(secrets={"": SENTINEL}), "malformed"),  # empty key name
        (_line(bonus="field"), "malformed"),  # unexpected extra field
    ],
)
async def test_malformed_lines_dropped_and_counted(line: bytes, kind: str) -> None:
    relay = _relay()
    apply_token_line(_attached_box(relay), line)  # must not raise
    assert relay.pending == 0
    assert relay.dropped[kind] == 1


async def test_oversize_frame_dropped_and_counted() -> None:
    relay = _relay()
    huge = "x" * (MAX_CONTROL_FRAME_BYTES + 1)
    apply_token_line(_attached_box(relay), _line(secrets={KEY_NAME: huge}))
    assert relay.pending == 0
    assert relay.dropped["oversize"] == 1


def test_oversize_stdin_line_dropped_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-parse guard: a giant raw line is refused before json.loads."""

    def boom(raw: object) -> object:
        raise AssertionError("oversize line must not be parsed")

    monkeypatch.setattr("solus_companion.config.json.loads", boom)
    relay = _relay()
    apply_token_line(_attached_box(relay), b"x" * (64 * 1024))  # must not raise
    assert relay.pending == 0


async def test_credential_line_without_relay_is_ignored() -> None:
    box = TokenBox("tok-1")  # no relay attached
    apply_token_line(box, _line())  # must not raise
    assert box() == "tok-1"  # token untouched


async def test_backlog_beyond_cap_is_dropped_and_counted() -> None:
    relay = _relay()
    box = _attached_box(relay)
    for _ in range(MAX_PENDING_SUBMITS + 1):
        apply_token_line(box, _line())
    assert relay.pending == MAX_PENDING_SUBMITS
    assert relay.dropped["backlog"] == 1


async def test_secret_value_never_logged_on_any_path(caplog: pytest.LogCaptureFixture) -> None:
    """caplog at DEBUG across accept + every drop path: the sentinel VALUE is
    in NO record; the key NAME (allowed) is."""
    caplog.set_level(logging.DEBUG)
    relay = _relay()
    box = _attached_box(relay)
    apply_token_line(box, _line())  # accepted
    apply_token_line(box, _line(server="not_discovered"))  # unknown server
    apply_token_line(box, _line(secrets={KEY_NAME: SENTINEL, "other": 42}))  # malformed
    apply_token_line(box, _line(secrets={KEY_NAME: SENTINEL + "y" * MAX_CONTROL_FRAME_BYTES}))
    apply_token_line(box, b'{"type":"credential","server":"altium","secrets":' + b"x")  # bad JSON
    _assert_no_sentinel_logged(caplog)
    assert any(KEY_NAME in record.getMessage() for record in caplog.records)


# --- credential_ack parsing and surfacing -------------------------------------


def test_parse_credential_ack_valid() -> None:
    raw = json.dumps(
        {
            "type": "credential_ack",
            "data": {"server": "altium", "ok": True, "stored": [KEY_NAME], "error": None},
        }
    )
    ack = parse_credential_ack(raw)
    assert ack == CredentialAck(server="altium", ok=True, stored=(KEY_NAME,), error=None)


def test_parse_credential_ack_error_reason() -> None:
    raw = json.dumps(
        {
            "type": "credential_ack",
            "data": {"server": "altium", "ok": False, "stored": [], "error": "unknown keys: x"},
        }
    )
    ack = parse_credential_ack(raw)
    assert ack is not None
    assert not ack.ok
    assert ack.error == "unknown keys: x"


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        "not json",
        "[]",
        '{"type":"credential_ack"}',
        '{"type":"credential_ack","data":[]}',
        '{"type":"other","data":{"server":"altium","ok":true,"stored":[],"error":null}}',
        '{"type":"credential_ack","data":{"ok":true,"stored":[],"error":null}}',
        '{"type":"credential_ack","data":{"server":"altium","ok":"yes","stored":[],"error":null}}',
        '{"type":"credential_ack","data":{"server":"altium","ok":true,"stored":[1],"error":null}}',
        '{"type":"credential_ack","data":{"server":"altium","ok":true,"stored":[],"error":42}}',
    ],
)
def test_parse_credential_ack_malformed_returns_none(raw: str | bytes) -> None:
    assert parse_credential_ack(raw) is None


def _supervised_altium() -> Supervisor:
    return Supervisor([ServerLaunch(name="altium", command=Path("/nowhere/launch"))])


def test_surface_ack_ok_updates_supervisor_status_detail() -> None:
    supervisor = _supervised_altium()
    supervisor.status_changed.clear()
    surface_ack(CredentialAck("altium", True, (KEY_NAME,), None), supervisor)
    handle = supervisor.handles["altium"]
    assert handle.detail == f"license stored ({KEY_NAME})"
    assert handle.state is ServerState.NOT_LAUNCHED  # detail only — no state change
    assert supervisor.status_changed.is_set()  # rides the existing status frames


def test_surface_ack_error_updates_supervisor_status_detail() -> None:
    supervisor = _supervised_altium()
    surface_ack(CredentialAck("altium", False, (), "unknown keys: x"), supervisor)
    assert supervisor.handles["altium"].detail == "license not stored: unknown keys: x"


def test_surface_ack_unsupervised_server_and_bare_object_do_not_raise() -> None:
    surface_ack(CredentialAck("ghost", True, (KEY_NAME,), None), _supervised_altium())
    surface_ack(CredentialAck("altium", True, (KEY_NAME,), None), object())  # protocol fakes


def test_ack_and_surface_never_log_the_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    surface_ack(CredentialAck("altium", True, (KEY_NAME,), None), _supervised_altium())
    surface_ack(CredentialAck("altium", False, (), "storage failed"), _supervised_altium())
    _assert_no_sentinel_logged(caplog)
    assert any(KEY_NAME in record.getMessage() for record in caplog.records)


# --- end to end through the channel -------------------------------------------


class AckRecordingSupervisor:
    """The BridgeSupervisor protocol + note_license_ack, recording acks."""

    def __init__(self) -> None:
        self.status_changed = asyncio.Event()
        self.acks: list[tuple[str, bool, tuple[str, ...], str | None]] = []

    def inventory(self) -> list[dict[str, Any]]:
        return []

    def status_snapshot(self) -> list[dict[str, Any]]:
        return []

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> Any:
        raise AssertionError("no tool calls in this test")

    def note_license_ack(
        self, server: str, ok: bool, stored: tuple[str, ...], error: str | None
    ) -> None:
        self.acks.append((server, ok, stored, error))


async def test_channel_relays_submit_frame_and_surfaces_ack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Full loop: stdin line before dial → one credential_submit on the wire →
    server acks → the supervisor sees the ack. No sentinel in any log."""
    caplog.set_level(logging.DEBUG)
    captured: dict[str, Any] = {}
    relay = _relay()
    box = _attached_box(relay)
    apply_token_line(box, _line())

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        await ws.send('{"type":"hello_ack","data":{"protocol_version":1}}')
        while True:  # skip interleaved status frames
            frame = json.loads(await ws.recv())
            if frame["type"] == "credential_submit":
                captured["submit"] = frame
                break
        await ws.send(
            json.dumps(
                {
                    "type": "credential_ack",
                    "data": {"server": "altium", "ok": True, "stored": [KEY_NAME], "error": None},
                }
            )
        )
        await asyncio.sleep(0.1)  # let the companion process the ack
        await ws.close(4409, "superseded")

    supervisor = AckRecordingSupervisor()
    async with _stub_server(handler) as url:
        config = CompanionConfig(
            url=url, token_source=box, integrations_root=Path("."), instance_id="a" * 32
        )
        state = await asyncio.wait_for(
            run_channel(config, supervisor, backoff_base=0.01, max_attempts=3), timeout=10
        )
    assert state.stop_reason == STOP_SUPERSEDED
    assert captured["submit"] == {
        "type": "credential_submit",
        "data": {"server": "altium", "secrets": {KEY_NAME: SENTINEL}},
    }
    assert supervisor.acks == [("altium", True, (KEY_NAME,), None)]
    _assert_no_sentinel_logged(caplog)


async def test_run_channel_attaches_relay_from_discovered_servers() -> None:
    """A TokenBox without a relay gets one keyed to the discovered set."""
    box = TokenBox()  # empty: the channel idles, never dials

    async def handler(ws: ServerConnection) -> None:  # pragma: no cover — never dialed
        await ws.close()

    async with _stub_server(handler) as url:
        config = CompanionConfig(
            url=url,
            token_source=box,
            integrations_root=Path("."),
            instance_id="a" * 32,
            servers=(ServerLaunch(name="altium", command=Path("/nowhere/launch")),),
        )
        task = asyncio.create_task(run_channel(config, AckRecordingSupervisor()))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert box.credentials is not None
    assert box.credentials.known_servers == frozenset({"altium"})


def test_credential_submit_frame_is_compact_addendum_c_json() -> None:
    frame = credential_submit_frame("altium", {KEY_NAME: "v"})
    expected = (
        '{"type":"credential_submit","data":{"server":"altium","secrets":{"altium_license":"v"}}}'
    )
    assert frame == expected


@contextlib.asynccontextmanager
async def _stub_server(
    handler: Callable[[ServerConnection], Awaitable[None]],
) -> Any:
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


# --- M4 / T10: an oversize stdin line must not kill the control channel --------


async def test_oversize_stdin_line_is_dropped_and_the_loop_survives() -> None:
    """A line longer than the reader limit makes asyncio's readline raise
    ValueError (LimitOverrunError). The consume loop must drop it, count it,
    and keep reading — a subsequent valid token line must still apply."""
    from solus_companion.__main__ import STDIN_READER_LIMIT, _consume_token_lines

    box = TokenBox()  # empty: the valid line below must fill it
    reader = asyncio.StreamReader(limit=STDIN_READER_LIMIT)
    reader.feed_data(b"x" * (200 * 1024) + b"\n")  # 200 KiB — over the limit
    reader.feed_data(json.dumps({"type": "token", "access_token": "tok-after"}).encode() + b"\n")
    reader.feed_eof()

    await _consume_token_lines(reader, box)

    assert box() == "tok-after", "the loop died on the oversize line instead of resyncing"
