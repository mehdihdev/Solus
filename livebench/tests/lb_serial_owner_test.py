"""SOLUSDEV-326 serial owner: one holder per serial device in the API process.

Busy used to look like silence, and every open reset the board. A second claim is now a typed
`DeviceBusyError` naming the holder only to the member it works for, in its own project (generic
to a teammate, across projects, and for a claim with no project or no member); an interrogation
listens on its own member's session port through a listen-only copy that never steals the
session's bytes; and every port the owner opens has HUPCL cleared, so closing it no longer drops
DTR and the next open does not restart an auto-reset board.
Ports here are pyserial `loop://` or fakes — never a device.
"""

from __future__ import annotations

import errno
import os
import termios
import threading
import time
from collections.abc import Callable

import pytest
import serial
from livebench.hardware.serial_owner import (
    LISTEN_BUFFER_BYTES,
    Claimant,
    HeldPort,
    PortListener,
    SerialOwner,
    claiming,
    current_claimant,
)
from solus_api.livebench.sessions import DeviceBusyError

REF = "usb:5B42134331"
SESSION = Claimant("session", "project-a", "alice")
INTERROGATION = Claimant("interrogation", "project-a", "alice")
UPLOAD = Claimant("upload", "project-a", "alice")


def _loop(timeout: float = 0.05) -> serial.Serial:
    return serial.serial_for_url("loop://", 115200, timeout=timeout)


def _never() -> serial.Serial:
    raise AssertionError("the port must not be opened again")


def _busy(call: Callable[[], object]) -> DeviceBusyError:
    with pytest.raises(DeviceBusyError) as raised:
        call()
    return raised.value


def test_one_holder_per_device_and_a_second_claim_names_the_holder() -> None:
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, _loop)
    assert isinstance(held, HeldPort)

    again = _busy(lambda: owner.hold(REF, SESSION, _never))
    assert (again.device_ref, again.holder) == (REF, "session")
    assert "busy" in str(again) and REF in str(again)
    assert _busy(lambda: owner.claim(REF, UPLOAD, _never)).holder == "session"
    other = owner.hold("usb:OTHER", SESSION, _loop)  # another device is its own holder

    held.close()
    owner.hold(REF, SESSION, _loop).close()  # released on close: the next claim opens
    other.close()


def test_a_holder_of_another_project_is_only_ever_busy() -> None:
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, _loop)
    elsewhere = Claimant("session", "project-b", "alice")  # the same member, another project
    assert _busy(lambda: owner.hold(REF, elsewhere, _never)).holder is None
    stranger = Claimant("interrogation", "project-b", "alice")
    assert _busy(lambda: owner.claim(REF, stranger, _never)).holder is None
    unscoped = Claimant("interrogation")
    assert _busy(lambda: owner.claim(REF, unscoped, _never)).holder is None
    held.close()


def test_a_teammates_holder_is_only_ever_busy_and_never_listened_to() -> None:
    """Two members of one project are strangers to the owner: a teammate's session may be on
    hardware kept out of the graph and hidden from this member (docs/api/hardware.md §1a), so it
    is never named to them and they never listen to it. A claim with a project but no member is
    nobody's, like one with no project."""
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, _loop)  # alice's session
    busy = _busy(lambda: owner.hold(REF, Claimant("session", "project-a", "bob"), _never))
    assert busy.holder is None and str(busy) == f"{REF} is busy: something else has it open."
    bob_listens = Claimant("interrogation", "project-a", "bob")
    assert _busy(lambda: owner.claim(REF, bob_listens, _never)).holder is None  # no listener
    memberless = Claimant("interrogation", "project-a")
    assert _busy(lambda: owner.claim(REF, memberless, _never)).holder is None
    held.close()
    with owner.holding(REF, Claimant("upload", "project-a", "bob")):  # nor the other way round
        assert _busy(lambda: owner.hold(REF, SESSION, _never)).holder is None
    with owner.holding(REF, Claimant("upload", "project-a")):
        assert _busy(lambda: owner.hold(REF, SESSION, _never)).holder is None


def test_an_interrogation_listens_on_its_own_members_session_port() -> None:
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, _loop)
    listener = owner.claim(REF, INTERROGATION, _never, timeout_s=0.05)
    assert isinstance(listener, PortListener)

    held.write(b"1.0,2.0\n")
    assert held.read(64) == b"1.0,2.0\n"  # the session still reads every byte
    assert listener.read(64) == b"1.0,2.0\n"  # and the listener hears a copy
    held.write(b'{"a": 1}\n')
    assert held.readline() == b'{"a": 1}\n'  # a line reader's bytes are copied too
    assert listener.read(64) == b'{"a": 1}\n'

    with pytest.raises(PermissionError):
        listener.write(b"\xff\xff\x01")  # a listener never writes onto the session's bus
    listener.baudrate = 9600
    assert listener.baudrate == held.baudrate == 115200  # nor re-rates its port

    held.write(b"stale\n")
    held.read(64)
    listener.reset_input_buffer()  # clears the listener's copy only
    assert listener.read(64) == b""

    listener.close()
    assert _busy(lambda: owner.hold(REF, SESSION, _never)).holder == "session"
    held.write(b"after\n")
    assert held.read(64) == b"after\n"
    held.close()


def test_only_a_session_is_listened_to() -> None:
    owner = SerialOwner()
    probing = owner.hold(REF, INTERROGATION, _loop)
    assert _busy(lambda: owner.claim(REF, INTERROGATION, _never)).holder == "interrogation"
    probing.close()
    with owner.holding(REF, UPLOAD):
        assert _busy(lambda: owner.claim(REF, INTERROGATION, _never)).holder == "upload"


def test_a_listener_hears_the_end_when_the_session_closes() -> None:
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, _loop)
    listener = owner.claim(REF, INTERROGATION, _never, timeout_s=5.0)
    held.close()
    started = time.monotonic()
    assert listener.read(64) == b""
    assert time.monotonic() - started < 1.0  # an ended listener never waits out its timeout


class _ChunkPort:
    """A raw port that returns a fixed chunk on every read."""

    baudrate = 115200

    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk

    def read(self, size: int = 1, /) -> bytes:
        return self.chunk

    def readline(self, size: int | None = -1, /) -> bytes:
        return self.chunk

    def write(self, data: bytes, /) -> int | None:
        return len(data)

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


def test_a_listeners_copy_is_bounded_and_keeps_the_newest_bytes() -> None:
    owner = SerialOwner()
    held = owner.hold(REF, SESSION, lambda: _ChunkPort(b"a" * 40_000 + b"z"))
    listener = owner.claim(REF, INTERROGATION, _never, timeout_s=0.05)
    held.read(1)
    held.read(1)
    copy = listener.read(10**6)
    assert len(copy) == LISTEN_BUFFER_BYTES and copy.endswith(b"z")
    held.close()


@pytest.mark.parametrize(
    "error",
    [
        serial.SerialException(errno.EAGAIN, "Could not exclusively lock port"),
        OSError(errno.EBUSY, "Device or resource busy"),
    ],
)
def test_another_program_holding_the_port_is_busy_and_releases_the_claim(
    error: OSError,
) -> None:
    owner = SerialOwner()

    def taken() -> serial.Serial:
        raise error

    busy = _busy(lambda: owner.hold(REF, SESSION, taken))
    assert busy.holder is None and busy.__cause__ is error
    owner.hold(REF, SESSION, _loop).close()  # the failed open held nothing


def test_an_open_that_fails_otherwise_propagates_and_releases_the_claim() -> None:
    owner = SerialOwner()

    def absent() -> serial.Serial:
        raise serial.SerialException(errno.ENOENT, "could not open port")

    with pytest.raises(serial.SerialException):
        owner.hold(REF, SESSION, absent)
    owner.hold(REF, SESSION, _loop).close()


def test_an_upload_holds_the_device_with_no_port_of_ours() -> None:
    owner = SerialOwner()
    with owner.holding(REF, UPLOAD):
        assert _busy(lambda: owner.hold(REF, SESSION, _never)).holder == "upload"
    owner.hold(REF, SESSION, _loop).close()
    held = owner.hold(REF, SESSION, _loop)
    with pytest.raises(DeviceBusyError) as refused, owner.holding(REF, UPLOAD):
        pass
    assert refused.value.holder == "session"
    held.close()


def test_unscoped_claimants_never_name_each_other() -> None:
    """A claim with no project (a propose, today) works for nobody's project: it is never told
    what holds the device, and what it holds is never named, not even to another unscoped claim."""
    owner = SerialOwner()
    with owner.holding(REF, Claimant("upload")):
        assert _busy(lambda: owner.claim(REF, Claimant("interrogation"), _never)).holder is None
        assert _busy(lambda: owner.hold(REF, SESSION, _never)).holder is None
    probing = owner.hold(REF, Claimant("interrogation"), _loop)
    assert _busy(lambda: owner.claim(REF, Claimant("interrogation"), _never)).holder is None
    with pytest.raises(DeviceBusyError) as refused, owner.holding(REF, Claimant("upload")):
        pass
    assert refused.value.holder is None
    probing.close()


class _TtyPort(_ChunkPort):
    """A raw port over a pseudo-terminal's fd: real termios, no device."""

    def __init__(self, fd: int) -> None:
        super().__init__(b"")
        self.fd = fd

    def fileno(self) -> int:
        return self.fd


def test_every_port_the_owner_opens_has_hupcl_cleared() -> None:
    master, slave = os.openpty()
    try:
        attrs = termios.tcgetattr(slave)
        attrs[2] |= termios.HUPCL
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        held = SerialOwner().hold(REF, SESSION, lambda: _TtyPort(slave))
        assert not termios.tcgetattr(slave)[2] & termios.HUPCL  # closing keeps DTR asserted
        held.close()
    finally:
        os.close(master)
        os.close(slave)


def test_a_claim_lasts_for_its_block_and_stays_on_its_thread() -> None:
    """The claimant rides a context variable, never the open parameters a config could carry."""
    seen: list[Claimant] = []
    with claiming(INTERROGATION):
        assert current_claimant() == INTERROGATION
        other = threading.Thread(target=lambda: seen.append(current_claimant()))
        other.start()
        other.join()
    assert current_claimant() == Claimant() and seen == [Claimant()]


def test_concurrent_claims_admit_exactly_one_holder() -> None:
    owner = SerialOwner()
    start = threading.Barrier(8)
    won: list[HeldPort] = []
    refused: list[DeviceBusyError] = []

    def slow() -> serial.Serial:
        time.sleep(0.05)
        return _loop()

    def claim() -> None:
        start.wait()
        try:
            won.append(owner.hold(REF, SESSION, slow))
        except DeviceBusyError as exc:
            refused.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(won) == 1 and len(refused) == 7
    won[0].close()


# ------------------------------------------------- would opening restart a running board?
# An inspection is free unless its open would restart a running auto-reset board (SOLUSDEV-326
# P2-T4): the owner's own port and a held device open nothing; a node the owner already opened
# keeps DTR asserted; a node plugged in moments ago is a board that just powered up.


def _pty() -> tuple[int, int, str]:
    master, slave = os.openpty()
    return master, slave, os.ttyname(slave)


def _aged(path: str, seconds: float) -> Callable[[], float]:
    """A wall clock `seconds` after the node at `path` last changed (its plug-in)."""
    changed = os.stat(path).st_ctime
    return lambda: changed + seconds


def test_opening_a_node_plugged_in_long_ago_restarts_its_board() -> None:
    master, slave, path = _pty()
    try:
        assert SerialOwner(clock=_aged(path, 3600)).opening_restarts(REF, path) is True
    finally:
        os.close(master)
        os.close(slave)


def test_opening_a_node_just_plugged_in_restarts_nothing_running() -> None:
    master, slave, path = _pty()
    try:
        assert SerialOwner(clock=_aged(path, 1)).opening_restarts(REF, path) is False
    finally:
        os.close(master)
        os.close(slave)


def test_a_node_the_owner_opened_keeps_dtr_and_reopens_without_a_restart() -> None:
    master, slave, path = _pty()
    try:
        owner = SerialOwner(clock=_aged(path, 3600))
        owner.hold(REF, SESSION, lambda: _TtyPort(slave)).close()
        assert owner.opening_restarts(REF, path) is False
    finally:
        os.close(master)
        os.close(slave)


def test_a_replugged_board_is_a_new_node_and_restarts_again() -> None:
    first_master, first_slave, first = _pty()
    master, slave, path = _pty()  # the same device ref, now behind another node
    try:
        owner = SerialOwner(clock=_aged(path, 3600))
        owner.hold(REF, SESSION, lambda: _TtyPort(first_slave)).close()
        assert owner.opening_restarts(REF, path) is True
        assert owner.opening_restarts(REF, first) is False
    finally:
        for fd in (first_master, first_slave, master, slave):
            os.close(fd)


def test_a_held_device_is_never_opened_again_so_nothing_restarts() -> None:
    """Its own member's session is listened to; anyone else's holder makes the claim busy."""
    master, slave, path = _pty()
    try:
        owner = SerialOwner(clock=_aged(path, 3600))
        with owner.holding(REF, UPLOAD):
            assert owner.opening_restarts(REF, path) is False
        held = owner.hold(REF, SESSION, _loop)  # a loop:// port records no node
        assert owner.opening_restarts(REF, path) is False
        held.close()
        assert owner.opening_restarts(REF, path) is True
    finally:
        os.close(master)
        os.close(slave)


def test_a_device_whose_node_is_gone_opens_nothing() -> None:
    assert SerialOwner().opening_restarts(REF, "/nonexistent/solus-test-node") is False
