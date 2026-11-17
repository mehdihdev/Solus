"""One holder per serial device in this process (SOLUSDEV-326; docs/architecture/
hardware-onboarding.md "Identity, leases and telemetry").

Busy used to look like silence, and every open reset the board. Every serial open in the local API
process — a session, an interrogation, an upload — now claims its device here first:

- One holder per device ref. Another claim raises `DeviceBusyError` naming the holder only when
  both are one member working in one project, else only "busy": for a teammate's holder (it may
  be on hardware kept out of the graph and hidden from this member; docs/api/hardware.md §1a),
  another project's, and whenever either claim names no project or no member (such a claim is
  nobody's). The one share: an interrogation of a device the same member's session holds in the
  same project listens on that session's port (`PortListener`), a copy of every byte the session
  reads. It never writes onto the session's bus and never re-rates it.
- Every port the owner opens has HUPCL cleared, so its last close no longer drops DTR and the next
  open no longer restarts an auto-reset board (DTR wired to RESET through a capacitor). The FIRST
  open after the board is plugged in still raises DTR once: benign, the board has just powered up.
  The kernel keeps a tty's termios across opens until the device goes away, so a replugged board
  starts with HUPCL set again and its first open clears it again.
- Another program holding the port (pyserial's `exclusive` flock, or TIOCEXCL) is busy too, with
  no holder named.
- Whether an open would restart a running board (`opening_restarts`, P2-T4) is answered with no
  port opened: a held device opens nothing; a node the owner already opened, the same node it
  cleared HUPCL on (device number, inode and change time), keeps DTR asserted; a node younger
  than `FRESH_PLUG_S` is a board that has just powered up. Anything else may restart it.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import termios
import threading
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from solus_api.livebench.sessions import DeviceBusyError, SerialPurpose

logger = logging.getLogger(__name__)

#: What a listener keeps of the session's stream, newest bytes first: device input is untrusted
#: and a slow listener must not grow without bound.
LISTEN_BUFFER_BYTES: Final = 64 * 1024
DEFAULT_LISTEN_TIMEOUT_S: Final = 0.1
#: How recently a device node may have appeared and still be a board that has just powered up,
#: whose reset on open is benign. A knob: the watcher sees a plug-in within about a second.
FRESH_PLUG_S: Final = 15.0
_BUSY_ERRNOS: Final = frozenset({errno.EBUSY, errno.EAGAIN})
#: A device node's identity for one plug-in: device number, inode and change time. The kernel
#: makes a new node when the device comes back, so a replugged board never matches.
Node = tuple[int, int, int]


@dataclass(frozen=True)
class Claimant:
    """Who opens a serial device: what for, the project it works in (`scope`) and the member it
    works for (`member`, the requesting user)."""

    purpose: SerialPurpose = "session"
    scope: str | None = None
    member: str | None = None

    @classmethod
    def of(cls, purpose: SerialPurpose, project_id: UUID | None, user_id: UUID | None) -> Claimant:
        """`user_id`'s claim in `project_id` (the API's ids); a missing one makes it nobody's."""
        return cls(
            purpose, str(project_id) if project_id else None, str(user_id) if user_id else None
        )

    def _same_member(self, holder: Claimant) -> bool:
        """Both are one named member working in one named project. A claim missing either is
        nobody's: two such claims (say, proposes from two projects) are strangers, and so are two
        members of one project."""
        return (
            self.scope is not None
            and self.member is not None
            and (self.scope, self.member) == (holder.scope, holder.member)
        )

    def listens_to(self, holder: Claimant) -> bool:
        """An interrogation listens on its own member's session in its project, and nothing else."""
        return (
            self.purpose == "interrogation"
            and holder.purpose == "session"
            and self._same_member(holder)
        )

    def refused(self, device_ref: str, holder: Claimant) -> DeviceBusyError:
        """Busy, with the holder named only to the member it works for, in its project."""
        return DeviceBusyError(device_ref, holder.purpose if self._same_member(holder) else None)


_SESSION: Final = Claimant()  # frozen: safe to share as the context variable's default
_CLAIMANT: ContextVar[Claimant] = ContextVar("serial_claimant", default=_SESSION)


@contextlib.contextmanager
def claiming(claimant: Claimant) -> Iterator[None]:
    """Serial opens inside this block, on this thread, claim their device for `claimant`; any
    other open is a session's. The claim rides a context variable, never the open parameters:
    a stored config can never name one, and no channel or proposal ever reports one."""
    token = _CLAIMANT.set(claimant)
    try:
        yield
    finally:
        _CLAIMANT.reset(token)


def current_claimant() -> Claimant:
    return _CLAIMANT.get()


class RawPort(Protocol):
    """The slice of pyserial the owner drives (a fake in tests)."""

    baudrate: int

    def read(self, size: int = 1, /) -> bytes: ...

    def readline(self, size: int | None = -1, /) -> bytes: ...

    def write(self, data: bytes, /) -> int | None: ...

    def reset_input_buffer(self) -> None: ...

    def close(self) -> None: ...


class HeldPort:
    """The holder's open port. Every byte it reads is copied to each listener; closing it releases
    the device."""

    def __init__(
        self, raw: RawPort, claimant: Claimant, release: Callable[[HeldPort], None]
    ) -> None:
        self.claimant = claimant
        self._raw = raw
        self._release = release
        self._lock = threading.Lock()
        self._listeners: tuple[PortListener, ...] = ()
        self._closed = False

    @property
    def port(self) -> str | None:
        """The path the port was opened at (a line reader names its topic by it)."""
        path = getattr(self._raw, "port", None)
        return path if isinstance(path, str) else None

    @property
    def baudrate(self) -> int:
        return self._raw.baudrate

    @baudrate.setter
    def baudrate(self, baud: int) -> None:
        self._raw.baudrate = baud  # pyserial re-rates the open port in place: no DTR pulse

    def read(self, size: int = 1, /) -> bytes:
        return self._copied(self._raw.read(size))

    def readline(self, size: int | None = -1, /) -> bytes:
        return self._copied(self._raw.readline(size))

    def write(self, data: bytes, /) -> int | None:
        return self._raw.write(data)

    def reset_input_buffer(self) -> None:
        self._raw.reset_input_buffer()

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            with self._lock:
                listeners, self._listeners, self._closed = self._listeners, (), True
            for listener in listeners:
                listener.end()
            self._release(self)

    def listen(self, timeout_s: float) -> PortListener:
        listener = PortListener(self, timeout_s)
        with self._lock:
            if self._closed:
                listener.end()
            else:
                self._listeners = (*self._listeners, listener)
        return listener

    def unlisten(self, listener: PortListener) -> None:
        with self._lock:
            self._listeners = tuple(kept for kept in self._listeners if kept is not listener)

    def _copied(self, data: bytes) -> bytes:
        if data:
            for listener in self._listeners:  # a tuple swapped under the lock: reads need none
                listener.feed(data)
        return data


class PortListener:
    """A listen-only view of a session's port: a bounded copy of what the session reads. It never
    writes onto the session's bus and never re-rates its port."""

    def __init__(self, held: HeldPort, timeout_s: float) -> None:
        self._held = held
        self._timeout_s = timeout_s
        self._ready = threading.Condition()
        self._buffer = b""
        self._ended = False

    @property
    def baudrate(self) -> int:
        return self._held.baudrate

    @baudrate.setter
    def baudrate(self, baud: int) -> None:
        """Ignored: the session's rate stays, and reads back unchanged."""

    def feed(self, data: bytes) -> None:
        with self._ready:
            self._buffer = (self._buffer + data)[-LISTEN_BUFFER_BYTES:]
            self._ready.notify_all()

    def end(self) -> None:
        with self._ready:
            self._ended = True
            self._ready.notify_all()

    def read(self, size: int = 1, /) -> bytes:
        with self._ready:
            self._ready.wait_for(lambda: self._buffer or self._ended, self._timeout_s)
            data, self._buffer = self._buffer[:size], self._buffer[size:]
            return data

    def write(self, data: bytes, /) -> int | None:
        raise PermissionError("a listener never writes onto the session's port")

    def reset_input_buffer(self) -> None:
        with self._ready:
            self._buffer = b""

    def close(self) -> None:
        self._held.unlisten(self)


@dataclass(eq=False)
class _Reservation:
    """A claim whose port is still opening, or an upload whose own tool opens the port."""

    claimant: Claimant


class SerialOwner:
    """Device ref → its one holder, for the whole process. Ports open on worker threads; the lock
    is held only to look and to record, never across an open."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.Lock()
        self._holders: dict[str, HeldPort | _Reservation] = {}
        #: Device ref → the node the owner last cleared HUPCL on.
        # ponytail: one entry per device ever opened in this process; never pruned.
        self._quiet: dict[str, Node] = {}
        self._clock = clock

    def claim(
        self,
        device_ref: str,
        claimant: Claimant,
        open_port: Callable[[], RawPort],
        *,
        timeout_s: float = DEFAULT_LISTEN_TIMEOUT_S,
    ) -> HeldPort | PortListener:
        """The port `claimant` uses: a listener on its own member's session port for an
        interrogation (reads waiting at most `timeout_s`), else the device held (`hold`)."""
        with self._lock:
            held = self._holders.get(device_ref)
            if isinstance(held, HeldPort) and claimant.listens_to(held.claimant):
                return held.listen(timeout_s)
        return self.hold(device_ref, claimant, open_port)

    def hold(
        self, device_ref: str, claimant: Claimant, open_port: Callable[[], RawPort]
    ) -> HeldPort:
        """Hold the device for `claimant`, opening its port: one holder per device."""
        reservation = self._reserve(device_ref, claimant)
        try:
            raw = open_port()
        except BaseException as exc:
            self._release(device_ref, reservation)
            if isinstance(exc, OSError) and exc.errno in _BUSY_ERRNOS:
                raise DeviceBusyError(device_ref, None) from exc  # another program holds it
            raise
        node = _clear_hupcl(raw)
        held = HeldPort(raw, claimant, lambda port: self._release(device_ref, port))
        with self._lock:
            self._holders[device_ref] = held
            if node is not None:
                self._quiet[device_ref] = node
        return held

    def opening_restarts(self, device_ref: str, path: str) -> bool:
        """Whether claiming `device_ref`, whose node is at `path`, would open its port and so
        restart a running auto-reset board. Opens nothing (see the module docstring)."""
        with self._lock:
            held = device_ref in self._holders
            quiet = self._quiet.get(device_ref)
        if held:
            return False  # its member's session is listened to; anyone else's claim is busy
        try:
            status = os.stat(path)
        except OSError:
            return False  # not plugged in: the claim finds no port to open
        node = (status.st_rdev, status.st_ino, status.st_ctime_ns)
        return node != quiet and self._clock() - status.st_ctime > FRESH_PLUG_S

    @contextlib.contextmanager
    def holding(self, device_ref: str, claimant: Claimant) -> Iterator[None]:
        """Hold the device with no port of ours — an upload, whose own tool opens the port."""
        reservation = self._reserve(device_ref, claimant)
        try:
            yield
        finally:
            self._release(device_ref, reservation)

    def _reserve(self, device_ref: str, claimant: Claimant) -> _Reservation:
        with self._lock:
            holder = self._holders.get(device_ref)
            if holder is not None:
                raise claimant.refused(device_ref, holder.claimant)
            reservation = self._holders[device_ref] = _Reservation(claimant)
            return reservation

    def _release(self, device_ref: str, holder: HeldPort | _Reservation) -> None:
        with self._lock:
            if self._holders.get(device_ref) is holder:
                del self._holders[device_ref]


def _clear_hupcl(port: object) -> Node | None:
    """Keep DTR asserted across the port's last close (see the module docstring), and name the
    node that now holds it. A port with no tty under it (pyserial's `loop://`, a fake) has
    nothing to clear, and a node left unchanged is not named."""
    fileno = getattr(port, "fileno", None)
    if not callable(fileno):
        return None
    try:
        fd = fileno()
        attrs = termios.tcgetattr(fd)
        if attrs[2] & termios.HUPCL:
            attrs[2] &= ~termios.HUPCL
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        status = os.fstat(fd)
    except (OSError, ValueError, termios.error) as exc:
        logger.debug("HUPCL left unchanged: %s", type(exc).__name__)
        return None
    return status.st_rdev, status.st_ino, status.st_ctime_ns


#: The process-wide owner every serial open in livebench claims through.
SERIAL_OWNER: Final = SerialOwner()
