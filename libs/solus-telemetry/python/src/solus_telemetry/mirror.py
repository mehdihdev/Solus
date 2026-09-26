"""Opt-in, bounded observation of explicitly selected synchronous host I/O methods.

Only ordinary instance methods returning built-in dictionaries are supported. The adapter
selects dictionary keys; it never calls user extractors or performs another hardware read.
Socket I/O and JSON encoding run on a daemon, independently of the control caller.
"""

from __future__ import annotations

import inspect
import math
import queue
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from types import MappingProxyType
from typing import Any

from solus_telemetry import MAX_SIGNALS, format_line


@dataclass(frozen=True)
class MethodAdapter:
    method: str
    signals: Mapping[str, str]
    argument: int | str | None = None

    def __post_init__(self) -> None:
        if not self.method.isidentifier() or self.method.startswith("_"):
            raise ValueError("Select a public method")
        if not 1 <= len(self.signals) <= MAX_SIGNALS:
            raise ValueError("Select 1..256 signals")
        if any(
            not isinstance(key, str) or not key or len(key) > 128 for key in self.signals.values()
        ):
            raise ValueError("Mapping keys must be bounded strings")
        if self.argument is not None and (
            isinstance(self.argument, bool)
            or not isinstance(self.argument, (int, str))
            or isinstance(self.argument, int)
            and not 0 <= self.argument <= 64
            or isinstance(self.argument, str)
            and not self.argument.isidentifier()
        ):
            raise ValueError("Select a positional or keyword argument")
        format_line("validation", dict.fromkeys(self.signals, 0.0), ts_us=0)
        object.__setattr__(self, "signals", MappingProxyType(dict(self.signals)))


@dataclass(frozen=True)
class MirrorConfig:
    device_id: str
    port: int
    methods: tuple[MethodAdapter, ...]
    units: Mapping[str, str] = field(default_factory=dict)
    capacity: int = 128

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Select a loopback UDP port")
        if type(self.capacity) is not int or not 1 <= self.capacity <= 1024:
            raise ValueError("Queue capacity must be 1..1024")
        if not 1 <= len(self.methods) <= 16:
            raise ValueError("Select 1..16 methods")
        if len({method.method for method in self.methods}) != len(self.methods):
            raise ValueError("Select each method once")
        signals = {signal: 0.0 for method in self.methods for signal in method.signals}
        format_line(self.device_id, signals, ts_us=0, units=self.units)
        object.__setattr__(self, "methods", tuple(self.methods))
        object.__setattr__(self, "units", MappingProxyType(dict(self.units)))


@dataclass(frozen=True)
class MirrorCounters:
    sent: int
    dropped: int
    errors: int


class MirrorHandle:
    """Owned wrappers and daemon lifecycle. Close discards pending samples without joining."""

    def __init__(
        self, robot: object, config: MirrorConfig, sink: Callable[[bytes], object] | None
    ) -> None:
        self._robot = robot
        self._config = config
        self._queue: queue.Queue[tuple[int, dict[str, float]]] = queue.Queue(config.capacity)
        self._closed = threading.Event()
        self._sent = self._dropped = self._errors = 0
        self._owned: list[tuple[str, object, bool, object]] = []
        originals = []
        if not hasattr(robot, "__dict__"):
            raise ValueError("Adapter requires an ordinary mutable instance")
        for adapter in config.methods:
            original = getattr(robot, adapter.method, None)
            if not callable(original) or inspect.iscoroutinefunction(original):
                raise ValueError("Adapter requires an existing synchronous method")
            if getattr(original, "__solus_mirror__", False):
                raise ValueError("Method is already mirrored")
            originals.append((adapter, original))
        try:
            for adapter, original in originals:
                wrapper = self._wrap(adapter, original)
                present = adapter.method in vars(robot)
                previous = vars(robot).get(adapter.method)
                setattr(robot, adapter.method, wrapper)
                self._owned.append((adapter.method, wrapper, present, previous))
        except Exception:
            self.close()
            raise
        self._thread = threading.Thread(
            target=self._run, args=(sink,), daemon=True, name="solus-host-mirror"
        )
        try:
            self._thread.start()
        except Exception:
            self.close()
            raise

    @property
    def counters(self) -> MirrorCounters:
        return MirrorCounters(self._sent, self._dropped, self._errors)

    def _wrap(self, adapter: MethodAdapter, original: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(original)
        def observed(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            if not self._closed.is_set():
                try:
                    source = (
                        result
                        if adapter.argument is None
                        else (
                            args[adapter.argument]
                            if isinstance(adapter.argument, int)
                            else kwargs[adapter.argument]
                        )
                    )
                    # Exact dict avoids invoking arbitrary Mapping methods on the control path.
                    if type(source) is not dict:
                        raise ValueError("Observation requires a built-in dictionary")
                    values = {}
                    for signal, key in adapter.signals.items():
                        value = source[key]
                        if type(value) not in (int, float) or not math.isfinite(value):
                            raise ValueError("Observation must be finite numeric data")
                        values[signal] = value
                    self._queue.put_nowait((time.time_ns() // 1000, values))
                except Exception:
                    self._dropped += 1
            return result

        observed.__solus_mirror__ = True  # type: ignore[attr-defined]
        return observed

    def _run(self, sink: Callable[[bytes], object] | None) -> None:
        sock = None
        seq = 0
        try:
            if sink is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)

                def send(data: bytes) -> object:
                    assert sock is not None
                    return sock.sendto(data, ("127.0.0.1", self._config.port))

                sink = send
            while not self._closed.is_set():
                try:
                    timestamp, values = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                if self._closed.is_set():
                    break
                try:
                    units = {
                        name: self._config.units[name]
                        for name in values
                        if name in self._config.units
                    }
                    line = format_line(
                        self._config.device_id, values, ts_us=timestamp, seq=seq, units=units
                    )
                    seq += 1
                    sink(line.encode("ascii"))
                    self._sent += 1
                except Exception:
                    self._errors += 1
        except Exception:
            self._errors += 1
        finally:
            if sock is not None:
                sock.close()

    def close(self) -> None:
        self._closed.set()
        for name, wrapper, present, previous in self._owned:
            if vars(self._robot).get(name) is wrapper:
                if present:
                    setattr(self._robot, name, previous)
                else:
                    delattr(self._robot, name)
        self._owned.clear()


def mirror(
    robot: object, *, config: MirrorConfig, sink: Callable[[bytes], object] | None = None
) -> MirrorHandle:
    """Install an explicit adapter. The optional sink is for embedding/testing only."""
    return MirrorHandle(robot, config, sink)
