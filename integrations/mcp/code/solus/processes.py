"""Long-running processes started by `code.process_start`
(docs/api/code-command-execution.md §2.3).

At most 4 run at once; finished entries are kept 30 minutes, 16 entries in total.
Output is kept as complete lines (`LineOutput` rules) in a 256 KiB ring per process
and read back by cursor, at most 64 KiB per answer. `max_runtime_seconds` elapsed →
the group is stopped (`timed_out`). Stop = SIGTERM to the process group, SIGKILL
after 5 s. Server shutdown stops everything. Each start records
`{pid, pgid, start token}` under `~/.solus/code-processes/<workspace key>.json`; on
the next server start, entries still alive with the SAME start token are killed
(a recycled pid has a different token). Nothing is ever restarted. The git-metadata
digest is taken at start and compared whenever the process ends (exit, stop, timeout,
shutdown); entries and the stop result carry `git_metadata_changed` (§9.3). Time,
spawning, signals, tokens and the digest are injectable for tests.
"""

import json
import logging
import os
import signal
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from .git_guard import git_metadata_digest
from .process_os import (
    Child,
    Spawn,
    TreeTracker,
    default_killpg,
    default_spawn,
    start_token,
)
from .profiles import workspace_key
from .progress import LineOutput

logger = logging.getLogger("solus.code.processes")

MAX_RUNNING = 4
MAX_ENTRIES = 16
RETENTION_SECONDS = 30 * 60
RING_BYTES = 256 * 1024
MAX_ANSWER_BYTES = 64 * 1024
STOP_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.05
WATCH_SECONDS = 0.5
MAX_STATE_BYTES = 64 * 1024
RUNNING = "running"


def _read_some(handle: IO[bytes]) -> bytes:
    """Whatever is available now (a pipe), so lines surface while the process runs."""
    read1 = getattr(handle, "read1", None)
    return bytes(read1(8192)) if read1 is not None else handle.read(8192)


def _iso() -> str:
    return datetime.now(UTC).isoformat()


class _RingOutput(LineOutput):
    """`LineOutput` line rules without its one-shot budget: the ring bounds memory."""

    def _emit(self, stream: str, text: str) -> None:
        if self.callback is not None:
            self.callback(stream, text)


@dataclass
class Entry:
    process_id: str
    name: str | None
    argv: list[str]
    cwd: str
    sandbox: str | None
    started_at: str
    started: float
    deadline: float
    state: str = RUNNING
    pid: int | None = None
    exit_code: int | None = None
    ended_at: str | None = None
    ended: float | None = None
    child: Child | None = None
    seq: int = 0
    size: int = 0
    dropped_through: int = 0
    chunks: deque[dict[str, Any]] = field(default_factory=deque)
    readers: list[threading.Thread] = field(default_factory=list)
    output: _RingOutput | None = None
    tree: Any = None
    git_before: str | None = None
    git_metadata_changed: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "name": self.name,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "state": self.state,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "sandbox": self.sandbox,
            "git_metadata_changed": self.git_metadata_changed,
        }


class Registry:
    """The processes of one `code` server (one workspace). Thread-safe."""

    def __init__(
        self,
        root: Path,
        *,
        spawn: Spawn = default_spawn,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        killpg: Callable[[int, int], None] = default_killpg,
        start_token: Callable[[int], str | None] = start_token,
        tracker: Callable[[int], Any] = TreeTracker,
        watch: bool = True,
        git_digest: Callable[[Path], str] = git_metadata_digest,
    ) -> None:
        self._tracker = tracker
        self._git_digest = git_digest
        self._root = root
        self._spawn = spawn
        self._clock = clock
        self._sleep = sleep
        self._killpg = killpg
        self._token = start_token
        self._watch = watch
        self._lock = threading.RLock()
        self._entries: dict[str, Entry] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._watcher: threading.Thread | None = None

    # --- persistence ------------------------------------------------------------------

    def state_file(self) -> Path:
        home = Path(os.environ.get("HOME") or Path.home())
        return home / ".solus" / "code-processes" / f"{workspace_key(self._root)}.json"

    def _persist(self) -> None:
        path = self.state_file()
        record = {"schema_version": 1, "processes": list(self._tokens.values())}
        try:
            for directory in (path.parent.parent, path.parent):
                if not directory.exists():
                    directory.mkdir(mode=0o700)
            os.chmod(path.parent, 0o700)
            descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(descriptor, "w") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(record, handle)
            os.replace(temporary, path)
        except OSError as exc:
            logger.warning("process state not recorded: %s", type(exc).__name__)

    def reap_orphans(self) -> None:
        """Kill processes a previous server left running (same start token only)."""
        path = self.state_file()
        if not path.exists():
            return
        try:
            with open(path, "rb") as handle:
                record = json.loads(handle.read(MAX_STATE_BYTES))
            entries = record.get("processes") if isinstance(record, dict) else None
        except (OSError, ValueError):
            entries = None
        for item in entries if isinstance(entries, list) else []:
            self._reap_one(item)
        path.unlink(missing_ok=True)

    def _reap_one(self, item: object) -> None:
        if not isinstance(item, dict):
            return
        pid, pgid, token = item.get("pid"), item.get("pgid"), item.get("token")
        valid = all(isinstance(v, int) and not isinstance(v, bool) and v > 1 for v in (pid, pgid))
        if not valid or not isinstance(token, str) or not token:
            return
        assert isinstance(pid, int) and isinstance(pgid, int)
        if self._token(pid) == token:
            logger.warning("killing orphaned process group %d from a previous server", pgid)
            self._killpg(pgid, signal.SIGKILL)

    # --- lifecycle --------------------------------------------------------------------

    def start(
        self,
        argv: list[str],
        *,
        display_argv: list[str],
        cwd: Path,
        cwd_label: str,
        env: dict[str, str],
        name: str | None,
        max_runtime_seconds: int,
        sandbox: str | None,
    ) -> dict[str, Any]:
        self.sweep()
        with self._lock:
            if sum(e.state == RUNNING for e in self._entries.values()) >= MAX_RUNNING:
                return self.start_refusal(f"at most {MAX_RUNNING} processes may run at once")
            self._make_room()
            now = self._clock()
            entry = Entry(
                process_id=uuid.uuid4().hex,
                name=name,
                argv=list(display_argv),
                cwd=cwd_label,
                sandbox=sandbox,
                started_at=_iso(),
                started=now,
                deadline=now + max_runtime_seconds,
                git_before=self._git_digest(self._root),
            )
            self._entries[entry.process_id] = entry
            try:
                child = self._spawn(argv, cwd, env)
            except (OSError, ValueError) as exc:
                entry.state, entry.ended_at, entry.ended = "failed_to_start", _iso(), now
                return self.start_refusal(f"could not start: {type(exc).__name__}")
            entry.child, entry.pid = child, child.pid
            entry.tree = self._tracker(child.pid)
            self._tokens[entry.process_id] = {
                "pid": child.pid,
                "pgid": child.pid,
                "token": self._token(child.pid),
            }
            self._persist()
            self._attach_output(entry, child)
        self._ensure_watcher()
        return {
            "ok": True,
            "process_id": entry.process_id,
            "pid": entry.pid,
            "argv": list(entry.argv),
            "cwd": entry.cwd,
            "started_at": entry.started_at,
            "sandbox": sandbox,
            "reason": None,
        }

    @staticmethod
    def start_refusal(reason: str) -> dict[str, Any]:
        """The `process_start` refusal shape."""
        return {
            "ok": False,
            "process_id": None,
            "pid": None,
            "argv": [],
            "cwd": ".",
            "started_at": None,
            "sandbox": None,
            "reason": reason,
        }

    def _make_room(self) -> None:
        finished = sorted(
            (e for e in self._entries.values() if e.state != RUNNING), key=lambda e: e.started
        )
        while len(self._entries) >= MAX_ENTRIES and finished:
            self._entries.pop(finished.pop(0).process_id, None)

    def _attach_output(self, entry: Entry, child: Child) -> None:
        def append(stream: str, text: str) -> None:
            with self._lock:
                entry.seq += 1
                entry.chunks.append({"seq": entry.seq, "stream": stream, "text": text})
                entry.size += len(text.encode("utf-8"))
                while entry.size > RING_BYTES and entry.chunks:
                    dropped = entry.chunks.popleft()
                    entry.size -= len(dropped["text"].encode("utf-8"))
                    entry.dropped_through = dropped["seq"]

        entry.output = _RingOutput(append)
        for stream, handle in (("stdout", child.stdout), ("stderr", child.stderr)):
            if handle is not None:
                reader = threading.Thread(
                    target=self._pump, args=(entry.output, stream, handle), daemon=True
                )
                reader.start()
                entry.readers.append(reader)

    def _pump(self, output: _RingOutput, stream: str, handle: IO[bytes]) -> None:
        try:
            for block in iter(
                lambda: handle.read1(8192) if hasattr(handle, "read1") else handle.read(8192), b""
            ):
                with self._lock:
                    output.feed(stream, block)
        except (OSError, ValueError):
            return

    def _finish(self, entry: Entry, state: str) -> None:
        for reader in entry.readers:
            reader.join(timeout=1.0)
        changed = self._git_digest(self._root) != entry.git_before
        if changed:
            logger.warning("process %s changed .git/hooks or .git/config", entry.process_id)
        with self._lock:
            entry.git_metadata_changed = changed
            if entry.output is not None:
                entry.output.finish()
            child = entry.child
            entry.exit_code = child.poll() if child is not None else None
            if entry.state == RUNNING:
                entry.state = state
            entry.ended_at, entry.ended = _iso(), self._clock()
            self._tokens.pop(entry.process_id, None)
            self._persist()

    def _signal_and_wait(self, entries: list[Entry]) -> None:
        """SIGTERM every group, wait up to 5 s, SIGKILL what is left."""
        for entry in entries:
            if entry.tree is not None:
                entry.tree.observe()
            if entry.pid is not None:
                self._killpg(entry.pid, signal.SIGTERM)
            if entry.tree is not None:
                entry.tree.kill(signal.SIGTERM)
        deadline = self._clock() + STOP_GRACE_SECONDS
        while self._clock() < deadline and any(self._alive(e) for e in entries):
            self._sleep(POLL_SECONDS)
        for entry in entries:
            if self._alive(entry) and entry.pid is not None:
                self._killpg(entry.pid, signal.SIGKILL)
                self._wait_dead(entry)
            if entry.tree is not None:
                entry.tree.kill(signal.SIGKILL)

    def _wait_dead(self, entry: Entry) -> None:
        wait = getattr(entry.child, "wait", None)
        if wait is not None:
            try:
                wait(timeout=STOP_GRACE_SECONDS)
            except Exception:  # noqa: BLE001 - best effort after SIGKILL
                logger.warning("process %s did not exit after SIGKILL", entry.pid)

    @staticmethod
    def _alive(entry: Entry) -> bool:
        return entry.child is not None and entry.child.poll() is None

    def _halt(self, entries: list[Entry], state: str) -> None:
        with self._lock:
            for entry in entries:
                if entry.state == RUNNING:
                    entry.state = state
        self._signal_and_wait(entries)
        for entry in entries:
            self._finish(entry, state)

    def stop(self, process_id: str) -> dict[str, Any]:
        # A process that already exited on its own reports that, not "stopped".
        self.sweep()
        with self._lock:
            entry = self._entries.get(process_id)
        if entry is None:
            return {
                "ok": False,
                "process_id": process_id[:64],
                "state": None,
                "exit_code": None,
                "reason": "unknown process",
                "git_metadata_changed": False,
            }
        if entry.state == RUNNING:
            self._halt([entry], "stopped")
        return {
            "ok": True,
            "process_id": process_id,
            "state": entry.state,
            "exit_code": entry.exit_code,
            "reason": None,
            "git_metadata_changed": entry.git_metadata_changed,
        }

    def stop_all(self) -> None:
        with self._lock:
            running = [e for e in self._entries.values() if e.state == RUNNING]
        if running:
            self._halt(running, "stopped")
        self.state_file().unlink(missing_ok=True)

    def sweep(self) -> None:
        """Record exits, enforce max runtime, drop expired entries."""
        with self._lock:
            running = [e for e in self._entries.values() if e.state == RUNNING]
        now = self._clock()
        for entry in running:
            if entry.tree is not None:
                entry.tree.observe()
            if not self._alive(entry):
                self._finish(entry, "exited")
            elif now >= entry.deadline:
                self._halt([entry], "timed_out")
        with self._lock:
            for entry in list(self._entries.values()):
                expired = entry.ended is not None and now - entry.ended >= RETENTION_SECONDS
                if entry.state != RUNNING and expired:
                    self._entries.pop(entry.process_id, None)

    def _ensure_watcher(self) -> None:
        if not self._watch or (self._watcher is not None and self._watcher.is_alive()):
            return
        self._watcher = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher.start()

    def _watch_loop(self) -> None:
        while True:
            time.sleep(WATCH_SECONDS)
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 - the watcher must never die silently
                logger.exception("process sweep failed")
            with self._lock:
                if not any(e.state == RUNNING for e in self._entries.values()):
                    return

    # --- observation ------------------------------------------------------------------

    def status(self, process_id: str | None = None, cursor: int = 0) -> dict[str, Any]:
        self.sweep()
        with self._lock:
            ordered = sorted(self._entries.values(), key=lambda e: e.started)
            answer: dict[str, Any] = {"processes": [e.summary() for e in ordered]}
            if process_id is None:
                return answer
            entry = self._entries.get(process_id)
            answer["output"] = None if entry is None else self._page(entry, cursor)
            return answer

    @staticmethod
    def _page(entry: Entry, cursor: int) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = []
        size = 0
        last = cursor
        for chunk in entry.chunks:
            if chunk["seq"] <= cursor:
                continue
            size += len(chunk["text"].encode("utf-8"))
            if size > MAX_ANSWER_BYTES:
                break
            chunks.append(dict(chunk))
            last = chunk["seq"]
        return {
            "process_id": entry.process_id,
            "chunks": chunks,
            "cursor": last,
            "truncated": entry.dropped_through > cursor,
        }
