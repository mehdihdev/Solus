"""Bounded, isolated, ephemeral command progress; never an execution result."""

import json
import uuid

from solus_api.agent.command_output import OutputStore
from solus_api.bridge.frames import FrameViolation, InboundFrame, parse_frame


def test_progress_requires_strict_bounded_payload():
    data = {"call_id": "call", "sequence": 1, "stream": "stdout", "text": "hello"}
    assert isinstance(
        parse_frame(
            json.dumps({"type": "tool_output", "data": data}),
            control_cap=32768,
            tool_result_cap=262144,
        ),
        InboundFrame,
    )
    for key, value in [("text", "x" * 2049), ("sequence", True), ("stream", "html")]:
        assert isinstance(
            parse_frame(
                json.dumps({"type": "tool_output", "data": {**data, key: value}}),
                control_cap=32768,
                tool_result_cap=262144,
            ),
            FrameViolation,
        )


def test_store_is_scope_bound_bounded_and_expires():
    clock = [0.0]
    store = OutputStore(clock=lambda: clock[0], ttl=10, capacity=2)
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    buffer = store.start(key)
    buffer.append("stdout", "hello\n")
    assert store.read(key, 0)["chunks"][0]["text"] == "hello\n"
    assert store.read((uuid.uuid4(), key[1], key[2]), 0)["chunks"] == []
    assert store.read(key, 1)["chunks"] == []
    for _ in range(300):
        buffer.append("stderr", "x" * 2047 + "\n")
    result = store.read(key, 0)
    assert len(result["chunks"]) <= 256 and result["truncated"]
    buffer.finish()
    buffer.append("stdout", "late")
    assert store.read(key, 0)["complete"]
    clock[0] = 11
    assert store.read(key, 0)["chunks"] == []


def test_store_redacts_and_does_not_replace_existing_execution():
    store = OutputStore()
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    buffer = store.start(key)
    buffer.append("stdout", "Authorization: Bearer abcdef123456789\n")
    assert "abcdef123456789" not in str(store.read(key, 0))
    assert store.start(key) is buffer


def test_split_secret_is_not_published_before_line_is_redacted() -> None:
    store = OutputStore()
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    buffer = store.start(key)
    for fragment in ["api_", "key=", "example-value"]:
        buffer.append("stdout", fragment)
        assert store.read(key, 0)["chunks"] == []
    buffer.append("stdout", "\n")
    assert "example-value" not in str(store.read(key, 0))
    buffer.append("stderr", "last line")
    buffer.finish()
    assert store.read(key, 0)["chunks"][-1]["text"] == "last line"


def test_oversized_line_is_suppressed_without_growing_pending_memory() -> None:
    store = OutputStore()
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    buffer = store.start(key)
    for _ in range(1000):
        buffer.append("stdout", "z" * 2048)
    buffer.append("stdout", "\nokay\n")
    result = store.read(key, 0)
    assert result["truncated"]
    assert len(str(result)) < 1000
    assert result["chunks"] == []


def test_secret_prefix_continued_on_next_line_is_withheld() -> None:
    for prefix in ["api_key=\n", "Authorization: Bearer\n", "password:\r"]:
        store = OutputStore()
        key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        buffer = store.start(key)
        buffer.append("stdout", prefix)
        assert store.read(key, 0)["chunks"] == []
        buffer.append("stdout", "example-value\n")
        assert "example-value" not in str(store.read(key, 0))


def test_expanded_redaction_chunks_reconstruct_the_complete_line() -> None:
    from solus_api.agent.tools.untrusted import redact_text

    store = OutputStore()
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    line = "token=x " * 250 + "\n"
    store.start(key).append("stdout", line)
    chunks = store.read(key, 0)["chunks"]
    assert all(len(chunk["text"]) <= 2048 for chunk in chunks)
    assert "".join(chunk["text"] for chunk in chunks) == redact_text(line)


def test_oversized_secret_prefix_cannot_expose_continuation() -> None:
    store = OutputStore()
    key = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    buffer = store.start(key)
    buffer.append("stdout", "api_key=" + " " * 2048 + "\nexample-value\n")
    assert "example-value" not in str(store.read(key, 0))
    assert store.read(key, 0)["truncated"]
