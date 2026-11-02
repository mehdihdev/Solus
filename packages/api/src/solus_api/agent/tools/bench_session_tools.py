"""SOL bench session operations: `bench.session_start` / `bench.session_stop` (SOLUSDEV-319).
docs/api/bench-view.md §6, §6.1.

The start card shows, after the frozen five rows, one row per config field that is not at its
default and changes what is opened (every field but `provider` and `window_seconds`, which have
their own rows). Values are escaped single lines; an inline MJCF shows only a digest and size.
Because the card is re-rendered from the stored args at decision time, a change to any of them
diverges the card and the gate refuses it as stale.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.bench_tools_common import (
    CELL_CAP,
    BenchScope,
    Caller,
    api_tool_error,
    as_uuid,
    cell,
    invalid,
    row,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.livebench.sessions import SessionNotFoundError, SessionStillStartingError
from solus_api.livebench.sessions_shared import (
    RUNNER_ABSENT,
    BenchSessionIn,
    emit_session_event,
    resolve_session,
    start_resolved_session,
)

_OWN_ROWS: Final = frozenset({"provider", "window_seconds"})
_LABELS: Final[dict[str, str]] = {
    "scene_name": "Scene",
    "mjcf_xml": "MJCF",
    "sample_hz": "Sample rate",
    "duration_seconds": "Duration",
    "topics": "Topics",
    "mcap_path": "MCAP file",
    "serial_number": "Serial number",
    "confirmed_device_path": "Device path",
    "baud": "Baud",
    "driver_id": "Driver",
    "driver_params": "Driver params",
    "robot_entity_id": "Robot id",
    "entity_id": "Hardware id",
    "recording": "Recording",
    "realtime": "Realtime",
}
_UNITS: Final[dict[str, str]] = {"sample_hz": "Hz", "duration_seconds": "s"}


def _shown(name: str, value: Any) -> str:
    if name == "mjcf_xml":
        data = str(value).encode()
        return f"sha256 {hashlib.sha256(data).hexdigest()[:12]} ({len(data)} bytes)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g} {_UNITS.get(name, '')}".strip()
    if isinstance(value, dict):
        return _faithful(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        )
    if isinstance(value, list):
        return _faithful(", ".join(str(v) for v in value))
    return _faithful(str(value))


def _faithful(text: str) -> str:
    """The card row for `text`; when the cell cuts or cleans it, a digest of the full value
    goes with it, so two values sharing a shown prefix never render the same row."""
    shown = cell(text)
    if shown == text:
        return shown
    digest = f" · sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]}"
    return cell(text, CELL_CAP - len(digest)) + digest


def config_rows(config: BaseModel) -> list[dict[str, Any]]:
    """One row per non-default field that affects what is opened (module docstring)."""
    rows: list[dict[str, Any]] = []
    for name, field in type(config).model_fields.items():
        value = getattr(config, name)
        if name in _OWN_ROWS or value == field.get_default(call_default_factory=True):
            continue
        rows.append(row(_LABELS.get(name, name), _shown(name, value)))
    return rows


class BenchSessionOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = Caller(session, scope)

    def _local(self) -> Any:
        local = getattr(self.state, "bench_local", None)
        if local is None:
            raise ToolException(
                f"source_unavailable: {RUNNER_ABSENT}", code=ToolErrorCode.UNAVAILABLE
            )
        return local

    async def _resolved(self, args: dict[str, Any]) -> tuple[BenchSessionIn, Any]:
        await self.caller.require_member()
        local = self._local()
        try:
            body = BenchSessionIn.model_validate(args)
        except ValidationError as exc:
            raise invalid(exc) from None
        try:
            resolved = await resolve_session(
                local,
                self.state.settings,
                self.session,
                self.scope.project_id,
                body,
                self.scope.user_id,
            )
        except APIError as exc:
            raise api_tool_error(exc) from None
        return body, resolved

    async def start_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        body, resolved = await self._resolved(args)
        manager = self.state.bench_sessions
        cap = getattr(manager, "_cap", None)
        if cap is not None and len(manager.list(self.scope.project_id, status="active")) >= cap:
            raise ToolException(
                f"too_many_sessions: {cap} sessions already active in this project",
                code=ToolErrorCode.UNAVAILABLE,
            )
        provider = body.config.provider
        target = (
            "Simulator"
            if body.mode == "sim"
            else "Robot"
            if provider in ("robot", "replay")
            else "Device"
        )
        return [
            row("Action", "Start session"),
            row("Source", provider),
            row("Mode", body.mode),
            row(target, cell(resolved.label)),
            row("Window", f"{body.config.window_seconds:g} s"),
            *config_rows(body.config),
        ]

    async def start(self, args: dict[str, Any]) -> dict[str, Any]:
        body, resolved = await self._resolved(args)
        try:
            record = await start_resolved_session(
                self.state.bench_sessions, self.scope.project_id, body, resolved, self.scope.user_id
            )
        except APIError as exc:
            raise api_tool_error(exc) from None
        await self._emit(record, started=True)
        await self.session.commit()
        return dict(record.model_dump(mode="json"))

    def _record(self, args: dict[str, Any]) -> Any:
        manager = getattr(self.state, "bench_sessions", None)
        if manager is None:
            raise ToolException(
                f"source_unavailable: {RUNNER_ABSENT}", code=ToolErrorCode.UNAVAILABLE
            )
        try:
            record = manager.get(self.scope.project_id, as_uuid(args["session_id"]))
        except SessionNotFoundError:
            raise ToolException("Session not found.", code=ToolErrorCode.NOT_FOUND) from None
        if record.status == "starting":
            raise ToolException(
                "session_starting: Session is still starting", code=ToolErrorCode.UNAVAILABLE
            )
        return record

    def check_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """`stored_args`: an unknown or starting session is refused before parking."""
        self._record(args)
        return args

    async def stop_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        await self.caller.require_member()
        record = self._record(args)
        return [
            row("Action", "Stop session"),
            row("Session", "stopped", cell(record.label)),
            row("Provider", None, record.provider),
        ]

    async def stop(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        self._record(args)
        try:
            record = await self.state.bench_sessions.stop(
                self.scope.project_id, as_uuid(args["session_id"])
            )
        except SessionNotFoundError:
            raise ToolException("Session not found.", code=ToolErrorCode.NOT_FOUND) from None
        except SessionStillStartingError:
            raise ToolException(
                "session_starting: Session is still starting", code=ToolErrorCode.UNAVAILABLE
            ) from None
        await self._emit(record, started=False)
        await self.session.commit()
        return dict(record.model_dump(mode="json"))

    async def _emit(self, record: Any, *, started: bool) -> None:
        emit_session_event(
            self.session,
            user=await self.caller.user(),
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            started=started,
            record=record,
            actor="sol",
        )
