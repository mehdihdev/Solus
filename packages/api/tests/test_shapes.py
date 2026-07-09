"""The four agent-tool envelope shapes + ArtifactRef (SOLUS-W0-04).

These are pure value objects — no DB. They lock the contract SOL branches on:
`ToolResult.ok`, the ok/value/error invariant, and JSON-serializability
(model-consumability — a result must drop cleanly into the model context).
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from solus_api.agent.tools import (
    ArtifactRef,
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from solus_api.models import ArtifactStorage

_SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}


def test_descriptor_is_frozen_and_carries_the_interface() -> None:
    desc = ToolDescriptor(
        name="get_entity", description="Fetch a graph entity.", params=_SCHEMA, returns={}
    )
    assert desc.name == "get_entity"
    assert desc.timeout_seconds is None
    assert desc.requires_confirmation is False  # safe default: nothing gates unless declared
    with pytest.raises(ValidationError):
        desc.name = "other"  # frozen


def test_descriptor_can_flag_a_destructive_tool_for_confirmation() -> None:
    desc = ToolDescriptor(
        name="flash_firmware",
        description="Flash firmware to a connected board.",
        params=_SCHEMA,
        returns={},
        requires_confirmation=True,
    )
    assert desc.requires_confirmation is True  # the orchestrator gates on this before dispatch


def test_toolcall_generates_a_unique_call_id_but_accepts_an_explicit_one() -> None:
    a, b = ToolCall(tool="t", args={}), ToolCall(tool="t", args={})
    assert a.call_id and a.call_id != b.call_id  # unique per call, for correlation
    assert ToolCall(call_id="fixed", tool="t", args={}).call_id == "fixed"


def test_toolresult_success_and_failure_constructors() -> None:
    ok = ToolResult.success("c1", {"entity_id": "e"})
    assert ok.ok is True and ok.error is None and ok.value == {"entity_id": "e"}

    err = ToolResult.failure("c1", ToolError(code=ToolErrorCode.NOT_FOUND, message="gone"))
    assert err.ok is False and err.value is None and err.error is not None
    assert err.error.code is ToolErrorCode.NOT_FOUND
    assert err.error.retryable is False  # default: permanent


def test_toolresult_enforces_the_ok_xor_error_invariant() -> None:
    with pytest.raises(ValidationError):  # ok=True must carry a value, never an error
        ToolResult(
            call_id="c", ok=True, error=ToolError(code=ToolErrorCode.TOOL_ERROR, message="x")
        )
    with pytest.raises(ValidationError):  # ok=True without a value is malformed
        ToolResult(call_id="c", ok=True, value=None)
    with pytest.raises(ValidationError):  # ok=False must carry an error
        ToolResult(call_id="c", ok=False, value={"a": 1})


def test_toolresult_serializes_to_json_native_even_for_uuid_and_datetime() -> None:
    # Model-consumability: whatever a tool puts in `value`, the envelope must
    # serialize cleanly into the model context.
    result = ToolResult.success(
        "c1", {"id": uuid4(), "at": datetime(2026, 7, 5, tzinfo=UTC), "n": 3}
    )
    dumped = result.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert isinstance(dumped["value"]["id"], str)


def test_artifactref_references_bytes_it_never_inlines() -> None:
    ref = ArtifactRef(
        artifact_id=UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3301"),
        uri="s3://bucket/key.png",
        media_type="image/png",
        size_bytes=2048,
        storage=ArtifactStorage.S3,
        summary="a blurry frame of the gripper",
    )
    assert ref.storage is ArtifactStorage.S3
    assert ref.summary  # the model reasons on this without fetching the bytes
    dumped = ref.model_dump(mode="json")
    assert dumped["artifact_id"] == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    # size_bytes/summary are genuinely optional — a minimal ref defaults them to None.
    minimal = ArtifactRef(
        artifact_id=UUID("3f2504e0-4f89-41d3-9a0c-0305e82c3301"),
        uri="s3://bucket/key.bin",
        media_type="application/octet-stream",
        storage=ArtifactStorage.S3,
    )
    assert minimal.size_bytes is None and minimal.summary is None


def test_toolerrorcode_has_the_five_codes() -> None:
    assert {c.value for c in ToolErrorCode} == {
        "invalid_args",
        "not_found",
        "tool_error",
        "timeout",
        "unauthorized",
    }
