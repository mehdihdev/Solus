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

Interactive processes (§11.1) run on a Solus-owned pseudo-terminal: one reader
cleans the master's output into the same ring (`terminal.TerminalText`), the entry
reports `awaiting_input` after 1.5 s of quiet at a prompt (each new detection bumps
`prompt_seq`), and `input` writes bounded printable text (+ Enter) to the master.
The master is closed when the process ends, is stopped, or the server shuts down.
"""

import json
import logging
import os
import select
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
    PtySpawn,
    Spawn,
    TreeTracker,
    default_killpg,
    default_pty_spawn,
    default_spawn,
    start_token,
)
from .profiles import workspace_key
from .progress import LineOutput
from .terminal import QUIET_SECONDS, TerminalText, input_refusal, prompt_tail, write_input

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
#: How often the terminal reader re-checks whether it must stop.
READ_POLL_SECONDS = 0.1
READER_JOIN_SECONDS = 1.0


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
    interactive: bool = False
    master_fd: int | None = None
    terminal: TerminalText | None = None
    recent: deque[str] = field(default_factory=lambda: deque(maxlen=5))
    last_output: float = 0.0
    awaiting_input: bool = False
    prompt_seq: int = 0
    io_lock: threading.Lock = field(default_factory=threading.Lock)
    closing: threading.Event = field(default_factory=threading.Event)

    def summary(self) -> dict[str, Any]:
        tail = None
        if self.terminal is not None:
            tail = prompt_tail(self.recent, self.terminal.pending_line)
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
            "interactive": self.interactive,
            "awaiting_input": self.awaiting_input,
            "prompt_seq": self.prompt_seq,
            "prompt_tail": tail,
        }


def input_result(process_id: str, sent_chars: int, reason: str | None) -> dict[str, Any]:
    """The `process_input` result shape."""
    return {
        "ok": reason is None,
        "process_id": process_id,
        "sent_chars": sent_chars,
        "reason": reason,
    }


class Registry:
    """The processes of one `code` server (one workspace). Thread-safe."""

    def __init__(
        self,
        root: Path,
        *,
        spawn: Spawn = default_spawn,
        pty_spawn: PtySpawn = default_pty_spawn,
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
        self._pty_spawn = pty_spawn
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
        interactive: bool = False,
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
                interactive=interactive,
                last_output=now,
            )
            self._entries[entry.process_id] = entry
            try:
                if interactive:
                    child, entry.master_fd = self._pty_spawn(argv, cwd, env)
                else:
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

    def _append(self, entry: Entry, stream: str, text: str) -> None:
        with self._lock:
            entry.seq += 1
            entry.chunks.append({"seq": entry.seq, "stream": stream, "text": text})
            entry.recent.append(text)
            entry.size += len(text.encode("utf-8"))
            while entry.size > RING_BYTES and entry.chunks:
                dropped = entry.chunks.popleft()
                entry.size -= len(dropped["text"].encode("utf-8"))
                entry.dropped_through = dropped["seq"]

    def _attach_output(self, entry: Entry, child: Child) -> None:
        if entry.master_fd is not None:
            entry.terminal = TerminalText(lambda text: self._append(entry, "stdout", text))
            reader = threading.Thread(target=self._pump_terminal, args=(entry,), daemon=True)
            reader.start()
            entry.readers.append(reader)
            return
        entry.output = _RingOutput(lambda stream, text: self._append(entry, stream, text))
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

    def _pump_terminal(self, entry: Entry) -> None:
        """Read the PTY master until EOF/EIO (the last slave closed) or `closing`;
        then close the master. Output clears `awaiting_input`."""
        fd, terminal = entry.master_fd, entry.terminal
        try:
            while fd is not None and terminal is not None and not entry.closing.is_set():
                ready, _, _ = select.select([fd], [], [], READ_POLL_SECONDS)
                if not ready:
                    continue
                try:
                    block = os.read(fd, 8192)
                except BlockingIOError:
                    continue
                if not block:
                    return
                with self._lock:
                    terminal.feed(block)
                    entry.last_output = self._clock()
                    entry.awaiting_input = False
        except (OSError, ValueError):
            return  # EIO once the terminal's last slave closed
        finally:
            self._close_master(entry)

    @staticmethod
    def _close_master(entry: Entry) -> None:
        with entry.io_lock:
            if entry.master_fd is not None:
                try:
                    os.close(entry.master_fd)
                finally:
                    entry.master_fd = None

    def _join_readers(self, entry: Entry) -> None:
        for reader in entry.readers:
            reader.join(timeout=READER_JOIN_SECONDS)
        if not entry.interactive:
            return
        # A descendant may still hold the terminal: stop reading, then close.
        entry.closing.set()
        for reader in entry.readers:
            reader.join(timeout=READER_JOIN_SECONDS)
        if not any(reader.is_alive() for reader in entry.readers):
            self._close_master(entry)

    def _finish(self, entry: Entry, state: str) -> None:
        self._join_readers(entry)
        changed = self._git_digest(self._root) != entry.git_before
        if changed:
            logger.warning("process %s changed .git/hooks or .git/config", entry.process_id)
        with self._lock:
            entry.git_metadata_changed = changed
            if entry.output is not None:
                entry.output.finish()
            if entry.terminal is not None:
                entry.terminal.finish()
            entry.awaiting_input = False
            child = entry.child
            entry.exit_code = child.poll() if child is not None else None
            if entry.state == RUNNING:
                entry.state = state
            entry.ended_at, entry.ended = _iso(), self._clock()
            self._tokens.pop(entry.process_id, None)
            self._persist()

    def _signal_and_wait(self, entries: list[Entry], grace_seconds: float) -> None:
        """SIGTERM every group, wait up to `grace_seconds`, SIGKILL what is left."""
        for entry in entries:
            if entry.tree is not None:
                entry.tree.observe(force=True)
            if entry.pid is not None:
                self._killpg(entry.pid, signal.SIGTERM)
            if entry.tree is not None:
                entry.tree.kill(signal.SIGTERM)
        deadline = self._clock() + grace_seconds
        while self._clock() < deadline and any(self._alive(e) for e in entries):
            self._sleep(POLL_SECONDS)
        for entry in entries:
            if self._alive(entry) and entry.pid is not None:
                self._killpg(entry.pid, signal.SIGKILL)
                self._wait_dead(entry)
            if entry.tree is not None:
                entry.tree.observe(force=True)
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

    def _halt(
        self, entries: list[Entry], state: str, grace_seconds: float = STOP_GRACE_SECONDS
    ) -> None:
        with self._lock:
            for entry in entries:
                if entry.state == RUNNING:
                    entry.state = state
        self._signal_and_wait(entries, grace_seconds)
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

    def stop_all(self, *, grace_seconds: float = STOP_GRACE_SECONDS) -> None:
        """Stop everything; server shutdown passes a short grace (§9.13)."""
        with self._lock:
            running = [e for e in self._entries.values() if e.state == RUNNING]
        if running:
            self._halt(running, "stopped", grace_seconds)
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
            else:
                self._refresh_prompt(entry, now)
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

    def _refresh_prompt(self, entry: Entry, now: float) -> None:
        """§11.1: quiet ≥ 1.5 s at a prompt → awaiting; each new detection bumps the seq."""
        with self._lock:
            terminal = entry.terminal
            waiting = (
                terminal is not None
                and entry.state == RUNNING
                and now - entry.last_output >= QUIET_SECONDS
                and terminal.prompting()
            )
            if waiting and not entry.awaiting_input:
                entry.prompt_seq += 1
            entry.awaiting_input = waiting

    # --- input ------------------------------------------------------------------------

    @staticmethod
    def _input_refusal(entry: Entry | None, text: str, enter: bool) -> str | None:
        if entry is None:
            return "unknown process"
        if entry.state != RUNNING:
            return "process is not running"
        if not entry.interactive or entry.terminal is None:
            return "process is not interactive"
        refusal = input_refusal(text)
        if refusal is not None:
            return refusal
        return None if text or enter else "nothing to send"

    def input(self, process_id: str, text: str, *, enter: bool = True) -> dict[str, Any]:
        """Write `text` (+ "\n" when `enter`) to an interactive process's terminal."""
        self.sweep()
        with self._lock:
            entry = self._entries.get(process_id)
            reason = self._input_refusal(entry, text, enter)
            if reason is not None or entry is None or entry.terminal is None:
                return input_result(process_id, 0, reason)
            # Before writing: the terminal's echo must not read as a new prompt.
            entry.terminal.mark_answered(len(text))
            entry.awaiting_input = False
            entry.last_output = self._clock()
        data = (text + ("\n" if enter else "")).encode("utf-8")
        with entry.io_lock:
            if entry.master_fd is None:
                return input_result(process_id, 0, "the process's terminal is closed")
            try:
                sent = write_input(entry.master_fd, data)
            except OSError:
                sent = 0
        if sent < len(data):
            partial = len(data[:sent].decode("utf-8", errors="ignore"))
            return input_result(process_id, partial, "the process did not accept the input")
        return input_result(process_id, len(text) + int(enter), None)

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
