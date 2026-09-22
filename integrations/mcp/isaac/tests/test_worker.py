"""Protocol tests use in-memory transport, without importing or launching Isaac."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.actions import MutationUnverifiedError
from integrations.mcp.isaac.solus.worker import serve_frames


class Engine:
    generation = 3

    def status(self):
        return {"loaded": False, "scene_generation": 3}

    def dispatch(self, operation, args):
        if args.get("fail") == "uncertain":
            raise MutationUnverifiedError(4)
        raise ValueError("private diagnostic must not escape")


def frame(operation="status", sequence=1, generation="owned", arguments=None):
    return {
        "operation": operation,
        "sequence": sequence,
        "generation": generation,
        "arguments": arguments or {},
    }


def transport(frames):
    reader = io.BytesIO(b"".join(json.dumps(value).encode() + b"\n" for value in frames))
    writer = io.BytesIO()
    serve_frames(reader, writer, "owned", Engine())
    return [json.loads(row) for row in writer.getvalue().splitlines()]


def test_ready_status_and_stop_sequence():
    replies = transport([frame(), frame("stop", 2)])
    assert replies[0] == {"ready": True, "generation": "owned"}
    assert replies[1]["result"]["loaded"] is False
    assert replies[2]["sequence"] == 2 and replies[2]["ok"] is True


@pytest.mark.parametrize(
    "value",
    [
        frame(generation="foreign"),
        frame(sequence=2),
        frame(operation="exec"),
        {**frame(), "script": "evil.py"},
    ],
)
def test_protocol_violation_terminates(value):
    with pytest.raises(ValueError):
        transport([value])


def test_oversized_and_malformed_frames():
    for data in (b"x" * 131073, b"{broken}\n"):
        with pytest.raises(ValueError):
            serve_frames(io.BytesIO(data), io.BytesIO(), "owned", Engine())


def test_uncertain_write_is_preserved_and_refusal_sanitized():
    replies = transport(
        [frame("load_model", arguments={"fail": "uncertain"}), frame("set_joint_limits", 2)]
    )
    assert replies[1]["result"]["execution_started"] is True
    assert replies[1]["result"]["reason"] == "mutation_unverified"
    assert replies[2]["result"] == {"ok": False, "reason": "action_refused", "scene_generation": 3}
    assert "private diagnostic" not in str(replies)


def test_empty_pipe_ends_after_ready():
    assert transport([]) == [{"ready": True, "generation": "owned"}]


def test_oversized_engine_readback_cannot_cross_private_pipe():
    class LargeEngine:
        def status(self):
            return {"unexpected": "x" * 131072}

    data = json.dumps(frame()).encode() + b"\n"
    with pytest.raises(ValueError, match="reply too large"):
        serve_frames(io.BytesIO(data), io.BytesIO(), "owned", LargeEngine())
