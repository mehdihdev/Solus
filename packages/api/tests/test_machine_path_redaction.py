"""Exact requested machine paths survive display filtering without a global exemption."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from solus_api.agent.tools.shapes import ToolResult
from solus_api.agent.tools.untrusted import REDACTED, redact_value
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import dispatch, fail_inflight, ingest_result

PATH = "verified-divider-product/uno_fsr_divider.kicad_pro"


def make_session():
    sent = []

    async def send(frame):
        sent.append(json.loads(frame))

    async def close(code):
        pass

    session = BridgeSession(
        session_id=uuid4().hex,
        user_id=uuid4(),
        team_id=uuid4(),
        project_id=uuid4(),
        companion_instance_id="i",
        companion_version="1",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(),
        send=send,
        close=close,
        max_inflight=8,
    )
    return session, sent


async def start(session, sent, tool="machine.write_file", path=PATH):
    task = asyncio.create_task(
        dispatch(
            session, tool, {"path": path, "content": "{}\n", "dry_run": True}, call_cap_bytes=10000
        )
    )
    while not sent:
        await asyncio.sleep(0)
    return task, sent[-1]["data"]["call_id"]


async def test_exact_requested_path_preserved_with_secret_keys_still_masked():
    session, sent = make_session()
    task, call_id = await start(session, sent)
    ingest_result(
        session,
        ToolResult.success(
            call_id, {"preview": [{"label": "File", "before": None, "after": PATH}], "token": PATH}
        ),
    )
    result = await task
    assert result.value["preview"][0]["after"] == PATH
    assert result.value["token"] == REDACTED
    assert not session.write_paths
    assert redact_value(PATH) == REDACTED


@pytest.mark.parametrize("tool", ["machine.read_file", "code.run", "kicad.add_symbol"])
async def test_other_tools_have_no_path_exemption(tool):
    session, sent = make_session()
    task, call_id = await start(session, sent, tool)
    ingest_result(session, ToolResult.success(call_id, {"path": PATH}))
    assert (await task).value["path"] == REDACTED


async def test_different_path_and_entropic_component_remain_masked():
    session, sent = make_session()
    path = "folder/abcdefghijklmnopqrstuvwxyz0123456789ABCD.txt"
    task, call_id = await start(session, sent, path=path)
    ingest_result(session, ToolResult.success(call_id, {"path": path, "unrelated": PATH}))
    assert (await task).value == {"path": REDACTED, "unrelated": REDACTED}


async def test_foreign_session_cannot_use_context_and_cancel_cleans_up():
    session, sent = make_session()
    foreign, _ = make_session()
    task, call_id = await start(session, sent)
    future = asyncio.get_running_loop().create_future()
    foreign.inflight[call_id] = future
    ingest_result(foreign, ToolResult.success(call_id, {"path": PATH}))
    assert (await future).value["path"] == REDACTED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not session.write_paths


async def test_disconnect_cleans_context():
    session, sent = make_session()
    task, _ = await start(session, sent)
    fail_inflight(session, "disconnected")
    assert not session.write_paths
    with pytest.raises(Exception, match="disconnected"):
        await task


@pytest.mark.parametrize(
    "path",
    [
        "../folder/file.txt",
        "/folder/file.txt",
        "folder//file.txt",
        "folder/./file.txt",
        "https://example.com/file.txt",
        "folder/api_key.txt",
        "folder/credentials.json",
        "folder/base64+payload=",
        "folder/back\\slash",
        "folder/line\nbreak",
        "folder/ trailing",
        "folder/" + "x" * 401,
        "single.txt",
        "folder/abcdefghijklmnopqrstuvwxyz0123456789ABCD.txt",
    ],
)
def test_display_validator_refuses_unsafe_or_secret_context(path):
    from solus_api.agent.tools.untrusted import safe_relative_display_path

    assert safe_relative_display_path(path) is None


async def test_real_native_preview_passes_complete_cloud_wrapper(tmp_path):
    from solus_api.agent.tools.machine_writes import MachineWriteTool
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_companion.machine.file_write import preview

    (tmp_path / "verified-divider-product").mkdir()
    args = {"path": PATH, "content": "{}\n", "create_dirs": False}
    plan = preview(tmp_path, **args)
    session, _ = make_session()

    async def send(frame):
        call = json.loads(frame)["data"]
        ingest_result(session, ToolResult.success(call["call_id"], plan))

    session.send = send

    class Raw:
        descriptor = ToolDescriptor(
            name="machine.write_file",
            description="write",
            params={"type": "object"},
            returns={"type": "object"},
        )

        async def invoke(self, args):
            result = await dispatch(session, "machine.write_file", args, call_cap_bytes=10000)
            return result.value

    rows = await MachineWriteTool(Raw()).preview(args)
    assert rows[0]["after"] == PATH and rows[-1]["after"] == "{}\n"
    assert not (tmp_path / PATH).exists()


async def test_path_context_uses_sent_argument_snapshot_not_mutable_caller_dict():
    session, sent = make_session()
    session.slots = asyncio.Semaphore(0)
    args = {"path": PATH, "content": "{}\n", "dry_run": True}
    task = asyncio.create_task(dispatch(session, "machine.write_file", args, call_cap_bytes=10000))
    while session.entered == 0:
        await asyncio.sleep(0)
    args["path"] = "another-folder/completely_different_file.kicad_pro"
    session.slots.release()
    while not sent:
        await asyncio.sleep(0)
    call = sent[0]["data"]
    assert call["args"]["path"] == PATH
    ingest_result(session, ToolResult.success(call["call_id"], {"path": PATH}))
    assert (await task).value["path"] == PATH
