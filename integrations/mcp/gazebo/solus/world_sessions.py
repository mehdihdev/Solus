"""The fork's session registry: ONE owned simulator process per fork process (plan §1.4) and
any number of attached worlds the user started themselves.

Owned sessions hold the ``Popen`` the adapter returned; they are the only processes this fork
ever signals, by process group (``start_new_session=True`` in ``spawn_process``), and only
through that handle — never by name or pattern. Attached sessions hold no process: ``stop`` on
one is refused with ``not_owned`` (the API never cards it; the user started it, the user stops
it). Attached ids are ``attached-<uuid4>`` so they can never collide with an owned ``uuid4``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Final
from uuid import uuid4

from .adapters.adapter_base import Adapter, CliError

ATTACHED_PREFIX: Final = "attached-"


def is_attached_id(session_id: str) -> bool:
    return session_id.startswith(ATTACHED_PREFIX)


class SessionRefusedError(ValueError):
    """A registry refusal that becomes ``{ok: false, code, reason}`` on the wire."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass
class WorldSession:
    session_id: str
    adapter: Adapter
    world: str
    owned: bool
    world_ref: str | None = None
    gui: bool = False
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def summary(self) -> dict[str, object]:
        family = self.adapter.family
        return {
            "session_id": self.session_id,
            "owned": self.owned,
            "family": family.name,
            "version": family.version,
            "distro": family.distro,
            "world": self.world,
            "world_ref": self.world_ref,
            "gui": self.gui,
            "alive": self.alive if self.owned else None,
        }


class WorldSessions:
    READY_TIMEOUT_S: ClassVar[float] = 60.0
    READY_POLL_S: ClassVar[float] = 0.5
    TERM_WAIT_S: ClassVar[float] = 5.0

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.RLock()
        self._owned: WorldSession | None = None
        self._attached: dict[str, WorldSession] = {}

    # --- reads ---------------------------------------------------------------------------------

    def owned_alive(self) -> WorldSession | None:
        """The owned session while its process lives; a dead one is reconciled (dropped)."""
        with self.lock:
            if self._owned is not None and not self._owned.alive:
                self._owned = None
            return self._owned

    def get(self, session_id: str) -> WorldSession:
        with self.lock:
            owned = self.owned_alive()
            if owned is not None and owned.session_id == session_id:
                return owned
            attached = self._attached.get(session_id)
            if attached is None:
                raise SessionRefusedError("session_unavailable", "no such session; open or attach")
            return attached

    def all(self) -> list[WorldSession]:
        with self.lock:
            owned = self.owned_alive()
            return ([owned] if owned else []) + list(self._attached.values())

    # --- writes --------------------------------------------------------------------------------

    def open_world(
        self, adapter: Adapter, world_file: Path, *, world: str, world_ref: str, gui: bool
    ) -> WorldSession:
        with self.lock:
            busy = self.owned_alive()
            if busy is not None:
                raise SessionRefusedError(
                    "busy", f"Solus already runs world {busy.world!r}; stop it first"
                )
            if world in self._running_now(adapter):
                # A user-started world must never be re-labelled as owned: every later call
                # addresses the world by name, and the API cards nothing inside an owned one.
                raise SessionRefusedError(
                    "world_already_running",
                    f"a world named {world!r} is already running; attach to it instead",
                )
            process = adapter.start(world_file, gui=gui)
            session = WorldSession(
                session_id=str(uuid4()),
                adapter=adapter,
                world=world,
                owned=True,
                world_ref=world_ref,
                gui=gui,
                process=process,
            )
            try:
                self._wait_ready(session)
            except CliError:
                self._terminate(session)
                raise
            self._owned = session
            return session

    def attach(self, adapter: Adapter, world: str) -> WorldSession:
        if world not in adapter.running_worlds():
            raise SessionRefusedError("world_not_running", f"no running world named {world!r}")
        session = WorldSession(
            session_id=ATTACHED_PREFIX + str(uuid4()), adapter=adapter, world=world, owned=False
        )
        with self.lock:
            self._attached[session.session_id] = session
        return session

    def stop(self, session_id: str) -> WorldSession:
        with self.lock:
            session = self.get(session_id)
            if not session.owned:
                raise SessionRefusedError(
                    "not_owned",
                    "this world was started by you, not by Solus; stop it from where you "
                    "started it",
                )
            self._terminate(session)
            self._owned = None
            return session

    def close(self) -> None:
        """Kill the owned process group (if any) and forget every session."""
        with self.lock:
            if self._owned is not None:
                self._terminate(self._owned)
            self._owned = None
            self._attached.clear()

    # --- plumbing ------------------------------------------------------------------------------

    @staticmethod
    def _running_now(adapter: Adapter) -> list[str]:
        """Fail closed: an unlistable transport is NOT "nothing running"."""
        try:
            return adapter.running_worlds()
        except CliError as error:
            raise SessionRefusedError(
                "transport_unavailable",
                "could not list running worlds, so Solus cannot prove the world is free; "
                "retry or attach",
            ) from error

    def _wait_ready(self, session: WorldSession) -> None:
        """Readiness is the name appearing AFTER the owned process started; `open_world`
        proved it absent just before, so the appearance is ours and not the user's."""
        deadline = self.clock() + self.READY_TIMEOUT_S
        while True:
            status = session.process.poll() if session.process is not None else None
            if status is not None:
                raise CliError([], f"the simulator exited with status {status}")
            try:
                if session.world in session.adapter.running_worlds():
                    return
            except CliError:
                pass  # the transport is not up yet
            if self.clock() >= deadline:
                raise CliError(
                    [],
                    f"world {session.world!r} did not come up within {self.READY_TIMEOUT_S:g}s",
                )
            self.sleep(self.READY_POLL_S)

    def _terminate(self, session: WorldSession) -> None:
        process = session.process
        session.process = None
        if process is None or process.poll() is not None:
            return
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=self.TERM_WAIT_S)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=self.TERM_WAIT_S)
            except subprocess.TimeoutExpired:
                pass  # ponytail: unkillable child; the OS reaps it with the fork
