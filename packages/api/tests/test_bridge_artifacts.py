"""Bulk artifact transfer over the bridge (SOLUS-CAD-00c).

`metadata-extraction.md` §2.1 requires bulk export bytes to ride an
`ArtifactRef` (`ArtifactStorage.CLIENT`), never inlined into a tool result. The
companion drops nothing now: it stages the bytes and the cloud pulls them in
chunks. Without this a STEP export could not cross the bridge at all, and
CAD-02/03/04 had no live path.

Everything the companion sends is untrusted (CLAUDE.md §7), so the pull is
bounded three ways — total size, a whole-transfer deadline, and session death.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid

import pytest
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.frames import ArtifactChunkData
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import (
    fail_artifact_fetches,
    fetch_artifact,
    ingest_artifact_chunk,
)
from solus_api.models import utcnow


def _session(send_fail: bool = False) -> tuple[BridgeSession, list[str]]:
    sent: list[str] = []

    async def _send(payload: str) -> None:
        if send_fail:
            raise RuntimeError("socket gone")
        sent.append(payload)

    async def _close(code: int) -> None:
        return None

    session = BridgeSession(
        session_id="s1",
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        companion_instance_id="c1",
        companion_version="0",
        protocol_version=1,
        connected_at=utcnow(),
        token_exp=utcnow(),
        inventory=(),
        send=_send,
        close=_close,
        max_inflight=4,
    )
    return session, sent


def _fetch_id(frame: str) -> str:
    """`artifact_fetch` is OUTBOUND, so `parse_frame` would flag it as a
    violation — read the envelope directly instead."""
    return str(json.loads(frame)["data"]["fetch_id"])


async def _feed(session: BridgeSession, frame: str, *parts: tuple[bytes, bool]) -> None:
    """Push chunks in as the companion would, once the fetch is registered."""
    fetch_id = _fetch_id(frame)
    for payload, final in parts:
        ingest_artifact_chunk(
            session,
            ArtifactChunkData(
                fetch_id=fetch_id,
                data=base64.b64encode(payload).decode("ascii"),
                final=final,
            ),
        )


async def test_chunks_reassemble_in_order() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1"))
    await asyncio.sleep(0)

    await _feed(session, sent[0], (b"ISO-", False), (b"10303", False), (b"-21;", True))

    assert await task == b"ISO-10303-21;"


async def test_a_single_final_chunk_is_enough() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1"))
    await asyncio.sleep(0)

    await _feed(session, sent[0], (b"tiny", True))

    assert await task == b"tiny"


async def test_the_fetch_frame_names_the_requested_artifact() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "the-handle"))
    await asyncio.sleep(0)

    assert json.loads(sent[0])["type"] == "artifact_fetch"
    assert json.loads(sent[0])["data"]["artifact_id"] == "the-handle"

    await _feed(session, sent[0], (b"x", True))
    await task


async def test_an_error_chunk_fails_the_fetch_without_partial_bytes() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "gone"))
    await asyncio.sleep(0)

    ingest_artifact_chunk(
        session,
        ArtifactChunkData(fetch_id=_fetch_id(sent[0]), final=True, error="unknown artifact"),
    )

    with pytest.raises(ToolException) as excinfo:
        await task
    assert excinfo.value.code is ToolErrorCode.NOT_FOUND


async def test_oversized_transfer_is_cut_off_mid_stream() -> None:
    """The bound must bite while chunks are still arriving — not after the whole
    artifact has been reassembled in memory."""
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "big", max_bytes=8))
    await asyncio.sleep(0)

    await _feed(session, sent[0], (b"12345", False), (b"67890", False))

    with pytest.raises(ToolException) as excinfo:
        await task
    assert "transfer limit" in excinfo.value.message


async def test_a_stalled_transfer_times_out_rather_than_pinning_a_worker() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "slow", timeout_seconds=0.05))
    await asyncio.sleep(0)

    await _feed(session, sent[0], (b"first", False))  # then silence

    with pytest.raises(ToolException) as excinfo:
        await task
    assert excinfo.value.code is ToolErrorCode.TIMEOUT
    assert excinfo.value.retryable is True


async def test_malformed_base64_is_a_typed_failure() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1"))
    await asyncio.sleep(0)

    ingest_artifact_chunk(
        session, ArtifactChunkData(fetch_id=_fetch_id(sent[0]), data="!!!not base64!!!", final=True)
    )

    with pytest.raises(ToolException):
        await task


async def test_a_dead_socket_fails_the_fetch_fast() -> None:
    session, _sent = _session(send_fail=True)

    with pytest.raises(ToolException) as excinfo:
        await fetch_artifact(session, "a1")

    assert excinfo.value.code is ToolErrorCode.UNAVAILABLE
    assert excinfo.value.retryable is True


async def test_disconnect_unblocks_every_waiting_pull() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1"))
    await asyncio.sleep(0)

    fail_artifact_fetches(session)

    with pytest.raises(ToolException) as excinfo:
        await task
    assert "bridge offline" in excinfo.value.message


async def test_an_unknown_fetch_id_is_dropped_not_misrouted() -> None:
    """Replay defence: a chunk must never resolve someone else's pull, and the
    fetch_id space is separate from the tool-call id space by construction."""
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1", timeout_seconds=0.05))
    await asyncio.sleep(0)

    ingest_artifact_chunk(session, ArtifactChunkData(fetch_id="not-mine", data="", final=True))

    with pytest.raises(ToolException) as excinfo:
        await task
    assert excinfo.value.code is ToolErrorCode.TIMEOUT


async def test_every_fetch_registers_a_distinct_id() -> None:
    session, sent = _session()
    first = asyncio.create_task(fetch_artifact(session, "a1", timeout_seconds=0.05))
    second = asyncio.create_task(fetch_artifact(session, "a1", timeout_seconds=0.05))
    await asyncio.sleep(0)

    assert _fetch_id(sent[0]) != _fetch_id(sent[1])

    for task in (first, second):
        with pytest.raises(ToolException):
            await task


async def test_the_fetch_map_is_cleaned_up_on_every_path() -> None:
    session, sent = _session()
    task = asyncio.create_task(fetch_artifact(session, "a1"))
    await asyncio.sleep(0)
    await _feed(session, sent[0], (b"x", True))
    await task

    assert session.artifact_fetches == {}
