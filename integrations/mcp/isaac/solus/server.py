"""Low-level MCP entry point: strict raw JSON inputs, fixed owned tool roster."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "solus"

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from .actions import Limits, Load, MutationUnverifiedError, Pose, Run
from .controller import Controller
from .models import EntityId, Strict


class Empty(Strict):
    pass


class Start(Strict):
    dry_run: bool


class Stop(Start):
    session_id: EntityId


class LoadCall(Load):
    session_id: EntityId


class LimitsCall(Limits):
    session_id: EntityId


class PoseCall(Pose):
    session_id: EntityId


class RunCall(Run):
    session_id: EntityId


SCHEMAS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Stop,
    "load_model": LoadCall,
    "set_joint_limits": LimitsCall,
    "set_sensor_pose": PoseCall,
    "run_routine": RunCall,
}
DEADLINES = {"load_model": 150, "set_joint_limits": 10, "set_sensor_pose": 10, "run_routine": 40}


def _advertised_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline this server's closed Pydantic definitions for the bridge ref gate."""
    definitions = schema.get("$defs", {})

    def expand(value: Any, active: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        siblings = {key: item for key, item in value.items() if key not in {"$defs", "$ref"}}
        if "$ref" in value:
            ref = value["$ref"]
            if (
                not isinstance(ref, str)
                or not ref.startswith("#/$defs/")
                or ref in active
                or ref[8:] not in definitions
            ):
                raise ValueError("schema must contain only acyclic local definitions")
            target = expand(definitions[ref[8:]], active | {ref})
            return {**target, **expand(siblings, active)}
        return {key: expand(item, active) for key, item in siblings.items()}

    return dict(expand(schema))


def tool_specs() -> list[Tool]:
    return [
        Tool(
            name=name,
            description="Owned Isaac "
            + name.replace("_", " ")
            + ". Graph arguments are supplied only by the authenticated Solus adapter.",
            inputSchema=_advertised_schema(schema.model_json_schema()),
        )
        for name, schema in SCHEMAS.items()
    ]


class ToolService:
    def __init__(self, workspace: Path) -> None:
        self.controller = Controller(workspace)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in SCHEMAS:
            raise ValueError("unknown tool")
        model = SCHEMAS[name].model_validate(arguments)
        values = model.model_dump()
        with self.controller.lock:
            if name == "probe":
                return self.controller.probe()
            if name == "status":
                state = self.controller.status()
                if state["state"] == "running":
                    state.update(self.controller.exchange("status", {}, timeout=5)["result"])
                return state
            if name == "start":
                return self.controller.start(dry_run=values["dry_run"])
            if name == "stop":
                return self.controller.stop(values["session_id"], dry_run=values["dry_run"])
            return self._action(name, values)

    def _action(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        if values.pop("session_id") != self.controller.session:
            raise ValueError("session unavailable")
        try:
            result = self.controller.exchange(name, values, timeout=DEADLINES[name])["result"]
        except (ValueError, OSError, TimeoutError) as error:
            if not values["dry_run"]:
                raise MutationUnverifiedError() from error
            raise
        if not isinstance(result, dict):
            raise ValueError("invalid worker result")
        return result

    def close(self) -> None:
        self.controller.close()


def wire_result(result: dict[str, Any]) -> dict[str, Any]:
    """Encode only declared digest fields; preserve all other redaction behavior."""

    def encode(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: encode(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        if (
            key in {"fingerprint", "graph_digest", "runtime_fingerprint", "sha256"}
            and isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value)
        ):
            return ":".join(value[i : i + 16] for i in range(0, 64, 16))
        return value

    return {name: encode(value, name) for name, value in result.items()}


async def serve() -> None:
    workspace = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if not workspace or not Path(workspace).is_absolute():
        raise ValueError("workspace unavailable")
    service = ToolService(Path(workspace))
    server = Server("solus-isaac")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        return tool_specs()

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            result = await asyncio.to_thread(service.call, name, arguments)
        except asyncio.CancelledError:
            # Cancelling an await does not stop its worker thread. Close the exact
            # owned controller; its event interrupts pipe waits before bounded kill.
            await asyncio.shield(asyncio.to_thread(service.close))
            raise
        except MutationUnverifiedError as error:
            result = error.result
        except (ValueError, OSError, TimeoutError):
            result = {"ok": False, "reason": "isaac_operation_refused"}
        result = wire_result(result)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, allow_nan=False))],
            structuredContent=result,
            isError=False,
        )

    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        service.close()


if __name__ == "__main__":
    asyncio.run(serve())
