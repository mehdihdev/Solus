"""Low-level MCP entry point: strict raw JSON inputs, fixed owned tool roster.

SOLUSDEV-322 P4-T1 adds the user's-own-stage tools (`list_stages open_stage find_articulations
spawn_at read_state control save_stage put_asset`): stage paths are confined to
`SOLUS_SIM_ROOTS` (`stages.py`), models arrive through the chunked store (`assets.ModelStore`),
`open_stage` is the one way a stage session starts, and `save_stage` is the one write into the
user's files (the worker exports privately; this process copies through `write_stage_file`).
Nothing raises across the wire: every refusal is `{ok: false, code, reason}`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Final

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "solus"

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import Field

from .actions import Limits, Load, MutationUnverifiedError, Pose, Run
from .assets import MAX_FILE_BYTES, ModelStore
from .controller import Controller
from .models import (
    EntityId,
    FindArticulations,
    ListStages,
    OpenStage,
    PutAsset,
    ReadState,
    SaveStage,
    SpawnAt,
    StageControl,
    Strict,
)
from .stages import (
    list_stage_files,
    open_stage_file,
    resolve_stage,
    stage_file_size,
    stage_roots,
    write_stage_file,
)


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


class OpenStageCall(OpenStage):
    dry_run: bool


class FindArticulationsCall(FindArticulations):
    session_id: EntityId


class StageCall(Strict):
    """A mutation inside the owned stage session: like the graph-bound calls it names the scene
    generation it was planned against, so a stale plan is refused before any effect."""

    session_id: EntityId
    expected_scene_generation: Annotated[int, Field(ge=0, le=1000)]
    dry_run: bool


class SpawnAtCall(StageCall, SpawnAt):
    pass


class ReadStateCall(ReadState):
    session_id: EntityId


class ControlCall(StageCall, StageControl):
    pass


class SaveStageCall(StageCall, SaveStage):
    pass


SCHEMAS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Stop,
    "load_model": LoadCall,
    "set_joint_limits": LimitsCall,
    "set_sensor_pose": PoseCall,
    "run_routine": RunCall,
    "list_stages": ListStages,
    "open_stage": OpenStageCall,
    "find_articulations": FindArticulationsCall,
    "spawn_at": SpawnAtCall,
    "read_state": ReadStateCall,
    "control": ControlCall,
    "save_stage": SaveStageCall,
    "put_asset": PutAsset,
}
DEADLINES = {
    "load_model": 150,
    "set_joint_limits": 10,
    "set_sensor_pose": 10,
    "run_routine": 40,
    "open_stage": 100,
    "find_articulations": 20,
    "spawn_at": 150,
    "read_state": 20,
    "control": 50,
    "save_stage": 50,
}
ROUTINE_GRACE_S: Final = 10
READS: Final = frozenset({"find_articulations", "read_state"})
_DIGEST_FIELDS: Final = frozenset(
    {"fingerprint", "graph_digest", "runtime_fingerprint", "sha256", "model_sha256", "frame_sha256"}
)


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


def _row(label: str, before: str | None, after: str | None) -> dict[str, str | None]:
    return {"label": label, "before": before, "after": after}


class ToolService:
    def __init__(self, workspace: Path) -> None:
        self.controller = Controller(workspace)
        self.store = ModelStore(self.controller.workspace)
        self.stage_root: Path | None = None

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in SCHEMAS:
            raise ValueError("unknown tool")
        model = SCHEMAS[name].model_validate(arguments)
        values = model.model_dump()
        with self.controller.lock:
            if name == "probe":
                return self.controller.probe()
            if name == "status":
                return self._status()
            if name == "start":
                return self.controller.start(dry_run=values["dry_run"])
            if name == "stop":
                return self.controller.stop(values["session_id"], dry_run=values["dry_run"])
            if name == "put_asset":
                assert isinstance(model, PutAsset)
                return self.store.put_chunk(model)
            stage = {
                "list_stages": self._list_stages,
                "open_stage": self._open_stage,
                "save_stage": self._save_stage,
            }
            if name in stage:
                return stage[name](values)
            return self._action(name, values)

    def _status(self) -> dict[str, Any]:
        state = self.controller.status()
        if state["state"] == "running":
            state.update(self.controller.exchange("status", {}, timeout=5)["result"])
        return state

    def _action(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        if values.pop("session_id") != self.controller.session:
            raise ValueError("session unavailable")
        if name == "spawn_at" and not self.store.has(values["model_sha256"]):
            # Named so the API wrapper knows to push the model (P4-T2), like the gazebo fork;
            # answered before the worker so no scene generation is spent on a missing model.
            return {
                "ok": False,
                "code": "model_not_verified",
                "reason": "model is not verified: push it with put_asset first",
            }
        mutating = name not in READS and not values["dry_run"]
        try:
            result = self.controller.exchange(name, values, timeout=self._deadline(name, values))[
                "result"
            ]
        except (ValueError, OSError, TimeoutError) as error:
            if mutating:
                raise MutationUnverifiedError() from error
            raise
        if not isinstance(result, dict):
            raise ValueError("invalid worker result")
        return result

    @staticmethod
    def _deadline(name: str, values: dict[str, Any]) -> float:
        if name == "run_routine":
            return float(values["routine_spec"]["duration_s"]) + ROUTINE_GRACE_S
        return DEADLINES[name]

    # --- the user's own stage ----------------------------------------------------------------

    def _list_stages(self, _: dict[str, Any]) -> dict[str, Any]:
        roots = stage_roots()
        return {
            "ok": True,
            "roots": len(roots),
            "stages": [{"path": f.path} for f in list_stage_files(roots)],
        }

    def _open_stage(self, values: dict[str, Any]) -> dict[str, Any]:
        root, rel = resolve_stage(values["stage_ref"])
        if values["dry_run"]:
            start = self.controller.start(dry_run=True)
            rows = [
                _row("Stage", None, rel),
                _row("Stage file", None, "opened in place; nothing is written until save_stage"),
                *start["preview"],
            ]
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"runtime": start["fingerprint"], "stage_ref": rel},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return {
                "ok": True,
                "dry_run": True,
                "preview": rows,
                "fingerprint": fingerprint,
                "runtime": start["runtime"],
            }
        started = self.controller.start(dry_run=False)
        arguments = {
            "expected_scene_generation": 0,
            "dry_run": False,
            "stage_path": str(root / rel),
            "stage_ref": rel,
        }
        result = self.controller.exchange("open_stage", arguments, timeout=DEADLINES["open_stage"])[
            "result"
        ]
        if not isinstance(result, dict) or result.get("ok") is not True:
            # A stage that fails to open leaves no session behind.
            self.controller.stop(started["session_id"], dry_run=False)
            return result if isinstance(result, dict) else {"ok": False, "reason": "stage_refused"}
        self.stage_root = root
        return {
            "ok": True,
            **self.controller.status(),
            "runtime_fingerprint": started["runtime_fingerprint"],
            "stage_ref": rel,
            "stage": result.get("readback"),
        }

    def _save_stage(self, values: dict[str, Any]) -> dict[str, Any]:
        root = self.stage_root or (stage_roots()[0] if stage_roots() else None)
        if root is None:
            raise ValueError("SOLUS_SIM_ROOTS names no directory to save into")
        dest = values["dest"]
        size = stage_file_size(root, dest)
        values["dest_state"] = "absent" if size is None else f"exists ({size} bytes)"
        result = self._action("save_stage", values)
        if values["dry_run"] or result.get("ok") is not True:
            return result
        private = self.controller.private
        readback = result.get("readback")
        if private is None or not isinstance(readback, dict):
            raise MutationUnverifiedError()
        data = self._private_export(Path(private.name), str(readback.get("export")))
        write_stage_file(root, dest, data)
        return {**result, "dest": dest, "bytes": len(data)}

    @staticmethod
    def _private_export(private: Path, name: str) -> bytes:
        """The worker's export, read O_NOFOLLOW from the controller's own private directory."""
        if "/" in name or not name.startswith("stage-export-"):
            raise ValueError("unexpected export name")
        fd = open_stage_file(private, name)
        try:
            if os.fstat(fd).st_size > MAX_FILE_BYTES:
                raise ValueError("exported stage too large")
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1 << 16):
                chunks.append(chunk)
        finally:
            os.close(fd)
        return b"".join(chunks)

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
            key in _DIGEST_FIELDS
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
            result = {
                "ok": False,
                "code": "isaac_operation_refused",
                "reason": "isaac_operation_refused",
            }
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
