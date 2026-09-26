"""Best-effort observation publishing; never opens or commands a robot."""

import http.client
import ipaddress
import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from urllib.parse import urlsplit
from uuid import UUID

from . import _now_us, format_line


@dataclass(frozen=True)
class HttpCounters:
    """Packet counts, except errors (failed HTTP batches). Queued is not accepted."""

    submitted: int = 0
    accepted: int = 0
    unresolved: int = 0
    rejected: int = 0
    dropped: int = 0
    invalid: int = 0
    errors: int = 0


class HttpPublisher:
    """Copy completed observations into authenticated, project-scoped Live Bench ingest.

    Submission validates/copies memory only. A daemon sends at most one batch per second;
    failures are counted, never retried. Close discards pending observations. This is an
    observer, not durable recording or a control channel. Tokens are never logged.
    """

    def __init__(
        self,
        api_url: str,
        project_id: str,
        token: str,
        *,
        interval: float = 1.0,
        timeout: float = 2.0,
        capacity: int = 500,
        max_age: float = 2.0,
        clock_us: Callable[[], int] = _now_us,
    ) -> None:
        parsed = urlsplit(api_url)
        if (
            any(ord(c) <= 32 or ord(c) == 127 for c in api_url)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or "?" in api_url
            or "#" in api_url
        ):
            raise ValueError("api_url must be an HTTPS origin or literal loopback HTTP origin")
        if parsed.scheme == "http" and not ipaddress.ip_address(parsed.hostname).is_loopback:
            raise ValueError("HTTP requires a literal loopback address")
        if not token or any(ord(c) <= 32 or ord(c) >= 127 for c in token):
            raise ValueError("token must be a nonempty ASCII bearer credential")
        if any(not math.isfinite(v) for v in (interval, timeout, max_age)) or not (
            1 <= interval <= 60 and 0 < timeout <= 10 and 0 < max_age <= 60
        ):
            raise ValueError("interval 1..60, timeout >0..10, max_age >0..60 seconds required")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 500:
            raise ValueError("capacity must be 1..500 packets")
        self._host = parsed.hostname
        self._port = parsed.port
        self._https = parsed.scheme == "https"
        self._path = f"/api/v1/projects/{UUID(project_id)}/bench/telemetry"
        self._token = token
        self._interval, self._timeout, self._max_age = interval, timeout, max_age
        self._capacity, self._clock_us = capacity, clock_us
        self._queue: deque[tuple[float, bytes]] = deque()
        self._seq: dict[str, int] = {}
        self._counts = HttpCounters()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="solus-telemetry-http", daemon=True)
        self._thread.start()

    @property
    def counters(self) -> HttpCounters:
        """Immutable, thread-safe cumulative delivery snapshot."""
        with self._lock:
            return self._counts

    def _count(self, **increments: int) -> None:
        self._counts = replace(
            self._counts,
            **{name: getattr(self._counts, name) + amount for name, amount in increments.items()},
        )

    def submit(
        self, device_id: str, values: Mapping[str, float], units: Mapping[str, str] | None = None
    ) -> bool:
        """Queue a copy; False means invalid, full, or closed. Never waits for network I/O."""
        with self._lock:
            if self._stop.is_set():
                return False
            try:
                seq = self._seq.get(device_id, 0)
                line = (
                    format_line(device_id, values, ts_us=self._clock_us(), seq=seq, units=units)
                    .strip()
                    .encode("ascii")
                )
            except (ValueError, TypeError, OverflowError):
                self._count(invalid=1)
                return False
            # Bound device bookkeeping as well as samples. Callers configure stable identities.
            if device_id not in self._seq and len(self._seq) >= 500:
                self._count(invalid=1)
                return False
            self._seq[device_id] = seq + 1
            self._count(submitted=1)
            if len(self._queue) >= self._capacity:
                self._count(dropped=1)
                return False
            self._queue.append((time.monotonic(), line))
            return True

    def close(self, timeout: float = 0.25) -> bool:
        """Discard queued samples; False means an HTTP call is still finishing."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("close timeout must be finite and nonnegative")
        with self._lock:
            self._stop.set()
            self._count(dropped=len(self._queue))
            self._queue.clear()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _batch(self) -> list[bytes]:
        batch: list[bytes] = []
        size = 16
        with self._lock:
            now = time.monotonic()
            while self._queue:
                observed, packet = self._queue.popleft()
                if now - observed > self._max_age or size + len(packet) + 1 > 1024 * 1024:
                    self._count(dropped=1)
                    continue
                batch.append(packet)
                size += len(packet) + 1
        return batch

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            batch = self._batch()
            if not batch:
                continue
            try:
                counts = self._post(b'{"packets":[' + b",".join(batch) + b"]}")
                names = ("accepted", "unresolved", "rejected")
                if any(type(counts.get(name)) is not int or counts[name] < 0 for name in names):
                    raise ValueError("invalid ingest counts")
                if sum(counts[name] for name in names) != len(batch):
                    raise ValueError("inconsistent ingest counts")
                with self._lock:
                    self._count(**{name: counts[name] for name in names})
            except Exception:
                # Do not propagate transport errors into motor control or log credential-bearing
                # exception text. A failed batch is never replayed after reconnection.
                with self._lock:
                    self._count(errors=1, dropped=len(batch))

    def _post(self, body: bytes) -> dict[str, int]:
        connection_class = (
            http.client.HTTPSConnection if self._https else http.client.HTTPConnection
        )
        connection = connection_class(self._host, self._port, timeout=self._timeout)
        try:
            connection.request(
                "POST",
                self._path,
                body,
                {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            # http.client does not use environment proxies or follow redirects.
            if response.status != 200:
                raise ValueError("ingest HTTP failure")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized ingest response")
            data = json.loads(raw)["data"]
            if not isinstance(data, dict):
                raise ValueError("invalid ingest response")
            return data
        finally:
            connection.close()
