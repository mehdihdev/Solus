"""Exercise SDK and installer boundaries without invoking vendor runtime code."""

import asyncio
import json
import os
import sys
import threading
import types
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus import actions, scene, server, worker


def make_service_type(tmp_path, captured):
    class Service:
        def __init__(self, path):
            assert path == tmp_path

        def call(self, name, args):
            if name == "uncertain":
                raise actions.MutationUnverifiedError(2)
            if name == "invalid":
                raise ValueError("private")
            return {"ok": True}

        def close(self):
            captured["closed"] = True

    return Service


@pytest.mark.parametrize("cancel", [False, True])
def test_sdk_transport_preserves_uncertainty_sanitizes_errors_and_closes(
    tmp_path, monkeypatch, cancel
):
    captured = {}

    service_type = make_service_type(tmp_path, captured)

    class SDK:
        def __init__(self, name):
            assert name == "solus-isaac"

        def list_tools(self):
            return lambda fn: captured.setdefault("list", fn)

        def call_tool(self, **kwargs):
            assert kwargs == {"validate_input": False}
            return lambda fn: captured.setdefault("call", fn)

        def create_initialization_options(self):
            return None

        async def run(self, *args):
            assert len(await captured["list"]()) == 8
            for name in ("status", "invalid", "uncertain"):
                captured[name] = json.loads((await captured["call"](name, {})).content[0].text)
            if cancel:
                raise asyncio.CancelledError

    @asynccontextmanager
    async def transport():
        yield object(), object()

    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(server, "ToolService", service_type)
    monkeypatch.setattr(server, "Server", SDK)
    monkeypatch.setattr(server, "stdio_server", transport)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(server.serve())
    else:
        asyncio.run(server.serve())
    assert captured["closed"]
    assert captured["status"] == {"ok": True}
    assert captured["invalid"] == {"ok": False, "reason": "isaac_operation_refused"}
    assert captured["uncertain"]["execution_started"] is True


def test_worker_bootstrap_binds_workspace_journal_and_closes_descriptors(tmp_path, monkeypatch):
    observed = {}

    class App:
        def __init__(self, config, **kwargs):
            assert config["headless"] is True

        def close(self):
            observed["closed"] = True

    class Engine:
        generation = 0

        def __init__(self, native, assets, cwd, *, revision_store):
            observed["store"] = revision_store

        def status(self):
            return {"loaded": False}

    monkeypatch.setitem(sys.modules, "isaacsim", types.SimpleNamespace(SimulationApp=App))
    monkeypatch.setattr(scene, "NativeScene", lambda app: object())
    monkeypatch.setattr(actions, "ActionEngine", Engine)
    read_request, write_request = os.pipe()
    read_reply, write_reply = os.pipe()
    workspace = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    os.close(write_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            str(read_request),
            str(write_reply),
            "00000000-0000-4000-8000-000000000001",
            str(workspace),
            str(tmp_path / "configured-runtime"),
        ],
    )
    try:
        worker.main()
        assert json.loads(os.read(read_reply, 1000))["ready"] is True
        assert observed["closed"] and observed["store"] is not None
        for descriptor in (read_request, write_reply, workspace):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        os.close(read_reply)


def test_sdk_requires_absolute_workspace(monkeypatch):
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", "relative")
    with pytest.raises(ValueError):
        asyncio.run(server.serve())


@asynccontextmanager
async def empty_transport():
    yield object(), object()


def test_cancelled_sdk_request_closes_owned_session(tmp_path, monkeypatch):
    captured = {}
    started = threading.Event()
    released = threading.Event()

    class Service:
        def __init__(self, path):
            pass

        def call(self, name, args):
            started.set()
            released.wait(2)
            return {"ok": True}

        def close(self):
            released.set()

    class SDK:
        def __init__(self, name):
            pass

        def list_tools(self):
            return lambda fn: fn

        def call_tool(self, **kwargs):
            return lambda fn: captured.setdefault("call", fn)

        def create_initialization_options(self):
            return None

        async def run(self, *args):
            task = asyncio.create_task(captured["call"]("run_routine", {}))
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert released.is_set(), "cancelled tool left native work alive"

    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(server, "ToolService", Service)
    monkeypatch.setattr(server, "Server", SDK)
    monkeypatch.setattr(server, "stdio_server", empty_transport)
    asyncio.run(server.serve())
