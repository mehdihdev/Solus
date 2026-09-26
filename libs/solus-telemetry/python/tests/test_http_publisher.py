"""Authenticated, bounded copies never perform I/O on the controller thread."""

import json
import threading
from unittest.mock import patch

import pytest
from solus_telemetry import HttpPublisher

PROJECT = "01a0a765-9fcf-7752-8cdf-f807c3133490"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "http://localhost",
        "https://u:p@example.com",
        "https://example.com/?x=1",
        "https://example.com/#x",
        "https://example.com/path",
        "file:///tmp/a",
        "http://127.0.0.1\n",
    ],
)
def test_rejects_unsafe_destinations(url: str) -> None:
    with pytest.raises(ValueError):
        HttpPublisher(url, PROJECT, "test-token")


def test_submit_copies_values_and_stamps_before_background_delivery() -> None:
    delivered = threading.Event()
    requests = []

    def post(self: HttpPublisher, body: bytes) -> dict[str, int]:
        requests.append(json.loads(body))
        delivered.set()
        return {"accepted": 1, "unresolved": 0, "rejected": 0}

    with patch.object(HttpPublisher, "_post", post):
        publisher = HttpPublisher(
            "http://127.0.0.1:8000", PROJECT, "test-token", clock_us=lambda: 123
        )
        values = {"joint.position": 2.0}
        assert publisher.submit("usb:board/1", values, {"joint.position": "deg"})
        values["joint.position"] = 7.0
        assert delivered.wait(3)
        publisher.close(timeout=3)
    packet = requests[0]["packets"][0]
    assert packet["values"] == {"joint.position": 2.0}
    assert packet["seq"] == 0
    assert packet["ts_us"] == 123
    assert publisher.counters.accepted == 1
    assert "test-token" not in repr(publisher)
    assert not publisher.submit("usb:board/1", values)


def test_queue_bounded_while_network_stalls_and_failures_not_retried() -> None:
    entered, release = threading.Event(), threading.Event()
    requests = []

    def post(self: HttpPublisher, body: bytes) -> dict[str, int]:
        requests.append(body)
        entered.set()
        assert release.wait(5)
        raise OSError("sensitive details never logged")

    with patch.object(HttpPublisher, "_post", post):
        publisher = HttpPublisher("https://example.com", PROJECT, "test-token", capacity=1)
        publisher.submit("a", {"p": 1})
        assert entered.wait(3)
        assert publisher.submit("a", {"p": 2})
        assert not publisher.submit("a", {"p": 3})
        assert publisher.counters.dropped == 1
        assert not publisher.close(timeout=0)
        release.set()
        assert publisher.close(timeout=3)
    assert len(requests) == 1
    assert publisher.counters.errors == 1
    assert publisher.counters.dropped == 3


def test_server_acceptance_is_not_inferred_from_successful_http() -> None:
    delivered = threading.Event()

    def post(self: HttpPublisher, body: bytes) -> dict[str, int]:
        delivered.set()
        return {"accepted": 0, "unresolved": 1, "rejected": 0}

    with patch.object(HttpPublisher, "_post", post):
        publisher = HttpPublisher("https://example.com", PROJECT, "test-token")
        publisher.submit("unknown", {"p": 1})
        assert delivered.wait(3)
        publisher.close(timeout=3)
    assert publisher.counters.accepted == 0
    assert publisher.counters.unresolved == 1


def test_invalid_sample_is_dropped_without_throwing_into_control_loop() -> None:
    publisher = HttpPublisher("https://example.com", PROJECT, "test-token")
    assert not publisher.submit("a", {"p": float("nan")})
    publisher.close()
    assert publisher.counters.invalid == 1


@pytest.mark.parametrize(
    "status,raw", [(302, b""), (401, b""), (200, b"x" * 65537), (200, b'{"data":[]}')]
)
def test_transport_never_follows_redirect_or_accepts_bad_response(status: int, raw: bytes) -> None:
    from unittest.mock import MagicMock

    connection = MagicMock()
    connection.getresponse.return_value.status = status
    connection.getresponse.return_value.read.return_value = raw
    with patch("solus_telemetry.http.http.client.HTTPSConnection", return_value=connection):
        publisher = HttpPublisher("https://example.com", PROJECT, "test-token")
        publisher.close()
        with pytest.raises(ValueError):
            publisher._post(b'{"packets":[]}')
    assert connection.request.call_count == 1
    connection.close.assert_called_once()


def test_http_uses_direct_connection_and_exact_authenticated_project_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    monkeypatch.setenv("HTTP_PROXY", "http://untrusted.invalid")
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = b'{"data":{"accepted":1,"unresolved":0,"rejected":0}}'
    with patch(
        "solus_telemetry.http.http.client.HTTPConnection", return_value=connection
    ) as factory:
        publisher = HttpPublisher("http://127.0.0.1:8000", PROJECT, "test-token")
        publisher.close()
        assert publisher._post(b'{"packets":[]}')["accepted"] == 1
    factory.assert_called_once_with("127.0.0.1", 8000, timeout=2.0)
    assert connection.request.call_args.args[1] == f"/api/v1/projects/{PROJECT}/bench/telemetry"
    assert connection.request.call_args.args[3]["Authorization"] == "Bearer test-token"


def test_stale_samples_dropped_and_sequences_are_per_device() -> None:
    with patch("solus_telemetry.http.time.monotonic", return_value=10):
        publisher = HttpPublisher("https://example.com", PROJECT, "test-token", interval=60)
        publisher.submit("a", {"p": 1})
        publisher.submit("b", {"p": 1})
        publisher.submit("a", {"p": 2})
        packets = [json.loads(p) for p in publisher._batch()]
        assert [p["seq"] for p in packets] == [0, 0, 1]
        publisher.submit("a", {"p": 3})
    with patch("solus_telemetry.http.time.monotonic", return_value=20):
        assert publisher._batch() == []
    publisher.close()
    assert publisher.counters.dropped == 1


@pytest.mark.parametrize(
    "counts",
    [
        {"accepted": True, "unresolved": 0, "rejected": 0},
        {"accepted": 2, "unresolved": 0, "rejected": 0},
    ],
)
def test_invalid_acknowledgement_counts_failure(counts: dict[str, int]) -> None:
    delivered = threading.Event()

    def post(self: HttpPublisher, body: bytes) -> dict[str, int]:
        delivered.set()
        return counts

    with patch.object(HttpPublisher, "_post", post):
        publisher = HttpPublisher("https://example.com", PROJECT, "test-token")
        publisher.submit("a", {"p": 1})
        assert delivered.wait(3)
        publisher.close(timeout=3)
    assert publisher.counters.errors == 1
    assert publisher.counters.accepted == 0
