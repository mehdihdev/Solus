"""Bench telemetry routes (LB-05) — §2.13 of the API plan.

Local bench runners (sim connectors, the serial/WS robot links) push LB-06 packet
batches here; the widget reads recent values, W0-07 summaries, and observer events.
Everything rides `ProjectCtx` — the same centralized auth + team scoping as every
other route — and the buffer/event state is keyed by project id, so cross-tenant
reads are impossible by construction (and proven by `test_bench_router.py`).

Trust boundary (§7): each packet decodes through the ratified LB-06 `from_wire`
(single error type); a hostile packet increments `rejected` and drops itself, never
the batch, never the route. Unresolved devices drop and count (`unresolved`) — the
LNK-06 rule that a stray device must not error a stream.

Streaming note: this is deliberately a poll/push REST surface. The WS/SSE upgrade
is scheduled by the API plan's later-phases line, and `sol-interface.md` §4
guarantees the windowed shapes carry over to continuous delivery without a
contract change.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from solus_api.agent.interfaces import TelemetryWindow
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.codec import PacketDecodeError, from_wire
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.sessions import (
    SessionManager,
    SessionNotFoundError,
    SessionStillStartingError,
)
from solus_api.livebench.sessions_shared import (
    RUNNER_ABSENT,
    BenchSessionIn,
    GazeboSimConfig,
    HardwareRealConfig,
    McapSimConfig,
    MujocoSimConfig,
    ReplayRealConfig,
    RobotRealConfig,
    SerialRealConfig,
    device_wire,
    emit_session_event,
    resolve_session,
    start_resolved_session,
)
from solus_api.models import GraphEntity, Role

_device_wire = device_wire  # kept importable: livebench/tests/lb_connection_headline_test.py

#: Session configs moved to `sessions_shared` (SOLUSDEV-319 B6); re-exported for importers.
__all__ = [
    "BenchEventRing",
    "BenchSessionIn",
    "GazeboSimConfig",
    "HardwareRealConfig",
    "McapSimConfig",
    "MujocoSimConfig",
    "ObserverEventIn",
    "ReplayRealConfig",
    "RobotRealConfig",
    "SerialRealConfig",
    "_device_wire",
    "get_bench_local",
    "get_session_manager",
    "router",
]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects/{project_id}/bench")

MAX_BATCH_PACKETS = 500
MAX_BATCH_EVENTS = 100
MAX_EVENTS_KEPT = 512
MAX_SUMMARY_SECONDS = 3600.0

#: A telemetry batch is many small packets; cap the body before it is read so a
#: 500-packet batch's worth of headroom is allowed and a 10 GB POST is refused up
#: front (mirrors routers/artifacts.py, §7). ~4 KiB/packet × 500 + events slack.
MAX_INGEST_BODY_BYTES = 4 * 1024 * 1024
#: Distinct signals one batch may create. The in-memory buffer is O(n) per distinct
#: signal; 500×256 = 128k in one request would wedge the event loop, so cap and
#: count the overflow (a real batch carries a handful of signals per device).
MAX_DISTINCT_SIGNALS_PER_BATCH = 4096
#: An observer-event detail is diagnostic context, not a payload.
MAX_EVENT_DETAIL_BYTES = 4096


def _reject_if_body_exceeds_cap(request: Request) -> None:
    """Refuse an oversized (or absent/malformed) Content-Length before the body is
    read — FastAPI buffers the whole body before dependencies resolve, so this is
    the only place to stop a pre-auth memory-exhaustion POST (§7)."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise APIError(411, "length_required", "Content-Length header is required")
    try:
        declared_bytes = int(declared)
    except ValueError:
        raise APIError(411, "length_required", "Content-Length header is invalid") from None
    if declared_bytes > MAX_INGEST_BODY_BYTES:
        raise APIError(413, "payload_too_large", "Telemetry batch exceeds the size limit")


class ObserverEventIn(BaseModel):
    """Wire shape of an edge-observer event (mirrors livebench's ObserverEvent)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["threshold_breach", "change_point", "stream_gap"]
    device_id: str = Field(min_length=1, max_length=512)
    signal: str = Field(min_length=1, max_length=128)
    at: datetime
    value: float | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("detail")
    @classmethod
    def _bound_detail(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Serialized-size bound: `dict[str, Any]` is otherwise unbounded, and these
        # fields reach SOL context later as untrusted device-authored content.
        if len(json.dumps(value, default=str)) > MAX_EVENT_DETAIL_BYTES:
            raise ValueError(f"event detail exceeds {MAX_EVENT_DETAIL_BYTES} bytes")
        return value


class TelemetryBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packets: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_BATCH_PACKETS)
    events: list[ObserverEventIn] = Field(default_factory=list, max_length=MAX_BATCH_EVENTS)


class BenchEventRing:
    """Bounded per-project observer-event ring. In-memory, like the LNK-06 buffer:
    live ephemeral values only — durable history is out of scope by decision."""

    def __init__(self, capacity: int = MAX_EVENTS_KEPT) -> None:
        self._events: dict[uuid.UUID, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def append(
        self, project_id: uuid.UUID, event: ObserverEventIn, *, finding_id: uuid.UUID | None = None
    ) -> None:
        """`finding_id` (SOLUSDEV-321 P2-T3) is attached here, to the ring's own record, by the
        server that raised the finding: `ObserverEventIn` has no such field, so an ingested event
        can never carry one, and `recent` hands out only the ids attached here."""
        record = event.model_dump(mode="json")
        if finding_id is not None:
            record["finding_id"] = str(finding_id)
        self._events[project_id].append(record)

    def recent(self, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        ring = self._events.get(project_id)
        if not ring:
            return []
        return list(ring)[-limit:]


def get_plumbing(request: Request) -> TelemetryPlumbing:
    plumbing: TelemetryPlumbing = request.app.state.telemetry_plumbing
    return plumbing


def get_event_ring(request: Request) -> BenchEventRing:
    ring: BenchEventRing = request.app.state.bench_events
    return ring


@router.post("/telemetry")
async def ingest_telemetry(
    ctx: ProjectCtx, body: TelemetryBatchIn, request: Request
) -> dict[str, Any]:
    _reject_if_body_exceeds_cap(request)
    require_role(ctx, Role.MEMBER)
    plumbing = get_plumbing(request)
    ring = get_event_ring(request)

    decoded = []
    rejected = 0
    distinct_signals: set[str] = set()
    for wire in body.packets:
        try:
            packet = from_wire(wire)
        except PacketDecodeError:
            rejected += 1  # a hostile packet drops itself, never the batch (§7)
            continue
        # Cap distinct signals per request: the in-memory buffer is O(n) per new
        # signal, so an unbounded request would block the event loop for tenants.
        distinct_signals.update(packet.values)
        if len(distinct_signals) > MAX_DISTINCT_SIGNALS_PER_BATCH:
            rejected += 1
            continue
        decoded.append(packet)

    accepted = unresolved = 0
    for packet in decoded:
        result = await plumbing.ingest(ctx.project.id, packet)
        if result.entity_id is None:
            unresolved += 1
        else:
            accepted += 1
    for event in body.events:
        ring.append(ctx.project.id, event)
    return envelope({"accepted": accepted, "unresolved": unresolved, "rejected": rejected})


@router.get("/telemetry-devices")
async def observed_telemetry_devices(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    return envelope({"device_ids": get_plumbing(request).observed_device_ids(ctx.project.id)})


@router.get("/recent/{entity_id}")
async def recent_values(
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    entity_id: uuid.UUID,
    signals: Annotated[list[str] | None, Query(max_length=64)] = None,
    limit: Annotated[int | None, Query(ge=1, le=512)] = None,
) -> dict[str, Any]:
    entity = await session.get(GraphEntity, entity_id)
    if entity is None or entity.project_id != ctx.project.id or entity.deleted_at is not None:
        raise APIError(404, "not_found", "Entity not found")
    view = await get_plumbing(request).get_recent_values(
        ctx.project.id, entity_id, signals=signals, limit=limit
    )
    return envelope(view.model_dump(mode="json"))


@router.get("/summary")
async def telemetry_summary(
    ctx: ProjectCtx,
    request: Request,
    duration_seconds: Annotated[float, Query(gt=0, le=MAX_SUMMARY_SECONDS)],
    signals: Annotated[list[str] | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    window = TelemetryWindow(duration_seconds=duration_seconds, signals=signals)
    view = await get_plumbing(request).get_telemetry(ctx.project.id, window)
    return envelope(view.model_dump(mode="json"))


@router.get("/events")
async def recent_events(
    ctx: ProjectCtx,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS_KEPT)] = 100,
) -> dict[str, Any]:
    return envelope(get_event_ring(request).recent(ctx.project.id, limit))


# ═══════════════════════════════════════════════════════════════════════════════
# SOLUSDEV-72: local-connections surface — sources, sessions, device-recent.
# The session subset of API.md §2.10, plus the sources/device-recent amendment.
# Providers come from `livebench.local` via the app-state optional runtime import
# (`app.state.bench_local`); absent → every local source is honestly unavailable.
# ═══════════════════════════════════════════════════════════════════════════════


def get_session_manager(request: Request) -> SessionManager:
    manager: SessionManager = request.app.state.bench_sessions
    return manager


def get_bench_local(request: Request) -> Any:
    return request.app.state.bench_local


def _unavailable_sources() -> dict[str, Any]:
    reason = RUNNER_ABSENT
    return {
        "runner": {"available": False, "reason": reason},
        "simulators": [
            {"kind": kind, "available": False, "reason": reason}
            for kind in ("mujoco", "gazebo", "isaac", "mcap-replay")
        ],
        "devices": [],
    }


@router.get("/sources")
async def bench_sources(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    local = get_bench_local(request)
    if local is None:
        return envelope(_unavailable_sources())
    settings = request.app.state.settings
    # Probes and pyserial enumeration hit the OS — off the event loop (§7:
    # a slow udev walk must not stall every other tenant's request).
    probed = await asyncio.to_thread(local.available_simulators)
    devices = await asyncio.to_thread(local.list_devices)
    simulators = [{"kind": s.kind, "available": s.available, "reason": s.reason} for s in probed]
    mcap_ready = bool(settings.bench_data_root)
    simulators.append(
        {
            "kind": "mcap-replay",
            "available": mcap_ready,
            "reason": None if mcap_ready else "bench_data_root is not configured on this server",
        }
    )
    return envelope(
        {
            "runner": {"available": True, "reason": None},
            "simulators": simulators,
            "devices": [device_wire(d) for d in devices],
        }
    )


@router.post("/sessions", status_code=201)
async def start_session(
    ctx: ProjectCtx, session: SessionDep, body: BenchSessionIn, request: Request
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    local = get_bench_local(request)
    if local is None:
        raise APIError(503, "source_unavailable", RUNNER_ABSENT)
    resolved = await resolve_session(
        local, request.app.state.settings, session, ctx.project.id, body, ctx.user.id
    )
    record = await start_resolved_session(
        get_session_manager(request), ctx.project.id, body, resolved, ctx.user.id
    )
    emit_session_event(
        session,
        user=ctx.user,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        started=True,
        record=record,
    )
    await session.commit()
    return envelope(record.model_dump(mode="json"))


@router.get("/sessions")
async def list_sessions(
    ctx: ProjectCtx,
    request: Request,
    status: Annotated[Literal["active", "ended"] | None, Query()] = None,
    mode: Annotated[Literal["sim", "real"] | None, Query()] = None,
) -> dict[str, Any]:
    records = get_session_manager(request).list(ctx.project.id, status=status, mode=mode)
    return envelope([r.model_dump(mode="json") for r in records])


@router.get("/sessions/{session_id}")
async def session_detail(
    ctx: ProjectCtx, request: Request, session_id: uuid.UUID
) -> dict[str, Any]:
    try:
        record = get_session_manager(request).get(ctx.project.id, session_id)
    except SessionNotFoundError as exc:
        raise APIError(404, "not_found", "Session not found") from exc
    return envelope(record.model_dump(mode="json"))


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    ctx: ProjectCtx, session: SessionDep, request: Request, session_id: uuid.UUID
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    manager = get_session_manager(request)
    try:
        record = await manager.stop(ctx.project.id, session_id)
    except SessionNotFoundError as exc:
        raise APIError(404, "not_found", "Session not found") from exc
    except SessionStillStartingError as exc:
        raise APIError(409, "session_starting", "Session is still starting") from exc
    emit_session_event(
        session,
        user=ctx.user,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        started=False,
        record=record,
    )
    await session.commit()
    return envelope(record.model_dump(mode="json"))


@router.get("/device-recent")
async def device_recent(
    ctx: ProjectCtx,
    request: Request,
    session: SessionDep,
    device_id: Annotated[list[str], Query(min_length=1, max_length=16)],
    limit: Annotated[int | None, Query(ge=1, le=512)] = None,
    focus_entity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Batched by design: the desktop polls every visible device panel in ONE
    request per cycle, so N streaming devices never multiply the request rate
    into the shared per-user budget."""
    from solus_api.livebench.focus_scope import focus_entity_ids

    allowed = (
        await focus_entity_ids(session, ctx.project.id, focus_entity_id)
        if focus_entity_id is not None
        else None
    )
    plumbing = get_plumbing(request)
    for one in device_id:
        if not 1 <= len(one) <= 512:
            raise APIError(422, "validation_error", "device_id length out of range")
    views = [
        await plumbing.get_device_recent(ctx.project.id, one, limit=limit) for one in device_id
    ]
    manager = get_session_manager(request)
    devices = []
    for view in views:
        if allowed is not None and view.resolved_entity_id not in allowed:
            continue
        device = view.model_dump(mode="json")
        roles = manager.channel_roles(ctx.project.id, view.device_id)
        for series in device["signals"]:
            if series["signal"] in roles:
                series["display_role"] = roles[series["signal"]]
        devices.append(device)
    return envelope({"devices": devices})
