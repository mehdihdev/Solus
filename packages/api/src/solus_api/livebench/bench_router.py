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

import json
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
from solus_api.models import GraphEntity, Role

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

    def append(self, project_id: uuid.UUID, event: ObserverEventIn) -> None:
        self._events[project_id].append(event.model_dump(mode="json"))

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
