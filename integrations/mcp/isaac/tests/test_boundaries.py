"""Exercise SDK and installer boundaries without invoking vendor runtime code."""

import asyncio
import json
import os
import sys
import threading
import types
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus import actions, scene, server, worker

#: An MCP SDK decorator factory: `server.list_tools()` / `server.call_tool()` return a decorator.
Decorator = Callable[[Callable[..., Any]], Any]


def make_service_type(tmp_path: Path, captured: dict[str, Any]) -> type[Any]:
    class Service:
        def __init__(self, path: Path) -> None:
            assert path == tmp_path

        def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name == "uncertain":
                raise actions.MutationUnverifiedError(2)
            if name == "invalid":
                raise ValueError("private")
            return {"ok": True}

        def close(self) -> None:
            captured["closed"] = True

    return Service


@pytest.mark.parametrize("cancel", [False, True])
def test_sdk_transport_preserves_uncertainty_sanitizes_errors_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    captured: dict[str, Any] = {}

    service_type = make_service_type(tmp_path, captured)

    class SDK:
        def __init__(self, name: str) -> None:
            assert name == "solus-isaac"

        def list_tools(self) -> Decorator:
            return lambda fn: captured.setdefault("list", fn)

        def call_tool(self, **kwargs: Any) -> Decorator:
            assert kwargs == {"validate_input": False}
            return lambda fn: captured.setdefault("call", fn)

        def create_initialization_options(self) -> None:
            return None

        async def run(self, *args: Any) -> None:
            assert len(await captured["list"]()) == 16
            for name in ("status", "invalid", "uncertain"):
                captured[name] = json.loads((await captured["call"](name, {})).content[0].text)
            if cancel:
                raise asyncio.CancelledError

    @asynccontextmanager
    async def transport() -> AsyncIterator[tuple[object, object]]:
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
    assert captured["invalid"] == {
        "ok": False,
        "code": "isaac_operation_refused",
        "reason": "isaac_operation_refused",
    }
    assert captured["uncertain"]["execution_started"] is True


def test_worker_bootstrap_binds_workspace_journal_and_closes_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, Any] = {}

    class App:
        def __init__(self, config: dict[str, Any], **kwargs: Any) -> None:
            assert config["headless"] is True

        def close(self) -> None:
            observed["closed"] = True

    class Engine:
        generation = 0

        def __init__(
            self, native: object, assets: Path, cwd: Path, *, revision_store: object
        ) -> None:
            observed["store"] = revision_store

        def status(self) -> dict[str, Any]:
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


def test_sdk_requires_absolute_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", "relative")
    with pytest.raises(ValueError):
        asyncio.run(server.serve())


@asynccontextmanager
async def empty_transport() -> AsyncIterator[tuple[object, object]]:
    yield object(), object()


def test_cancelled_sdk_request_closes_owned_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    started = threading.Event()
    released = threading.Event()

    class Service:
        def __init__(self, path: Path) -> None:
            pass

        def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            started.set()
            released.wait(2)
            return {"ok": True}

        def close(self) -> None:
            released.set()

    class SDK:
        def __init__(self, name: str) -> None:
            pass

        def list_tools(self) -> Decorator:
            return lambda fn: fn

        def call_tool(self, **kwargs: Any) -> Decorator:
            return lambda fn: captured.setdefault("call", fn)

        def create_initialization_options(self) -> None:
            return None

        async def run(self, *args: Any) -> None:
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
