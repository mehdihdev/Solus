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
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.interfaces import TelemetryWindow
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.codec import PacketDecodeError, from_wire
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.hardware.config import TransportKind
from solus_api.hardware.local_runtime import open_local_hardware, prepare_local_hardware
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import hardware_entity, robot_root
from solus_api.livebench.sessions import (
    AmbiguousDeviceError,
    DeviceNotFoundError,
    SessionManager,
    SessionNotFoundError,
    SessionStillStartingError,
    TooManySessionsError,
)
from solus_api.models import GraphEntity, Role
from solus_api.services.events import emit_event

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


# ═══════════════════════════════════════════════════════════════════════════════
# SOLUSDEV-72: local-connections surface — sources, sessions, device-recent.
# The session subset of API.md §2.10, plus the sources/device-recent amendment.
# Providers come from `livebench.local` via the app-state optional runtime import
# (`app.state.bench_local`); absent → every local source is honestly unavailable.
# ═══════════════════════════════════════════════════════════════════════════════

MAX_MJCF_BYTES = 2_000_000
MAX_TOPICS = 32
MAX_TOPIC_LEN = 256
MAX_SESSION_SECONDS = 3600.0
MAX_WINDOW_SECONDS = 60.0
_RUNNER_ABSENT = "livebench is not installed on this server"
_SIM_PROVIDERS = {"mujoco", "gazebo", "mcap-replay"}


def _clean_topics(topics: list[str]) -> list[str]:
    for topic in topics:
        if not 1 <= len(topic) <= MAX_TOPIC_LEN:
            raise ValueError("topic length out of range")
        if topic.startswith("-"):
            raise ValueError(f"topic may not look like a CLI flag: {topic[:32]!r}")
        if not topic.isprintable():
            raise ValueError("topic contains non-printable characters")
    return topics


class MujocoSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mujoco"]
    scene_name: str = Field(default="demo", min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    mjcf_xml: str | None = Field(default=None, min_length=1, max_length=MAX_MJCF_BYTES)
    sample_hz: float = Field(default=50.0, gt=0, le=200)
    duration_seconds: float = Field(default=300.0, gt=0, le=MAX_SESSION_SECONDS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class GazeboSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gazebo"]
    topics: list[str] = Field(min_length=1, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str]) -> list[str]:
        return _clean_topics(topics)


class McapSimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mcap-replay"]
    mcap_path: str = Field(min_length=1, max_length=4096)
    topics: list[str] | None = Field(default=None, max_length=MAX_TOPICS)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str] | None) -> list[str] | None:
        return None if topics is None else _clean_topics(topics)


class SerialRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["serial"]
    serial_number: str | None = Field(default=None, min_length=1, max_length=128)
    confirmed_device_path: str | None = Field(default=None, min_length=1, max_length=256)
    baud: int = Field(default=115200, ge=300, le=3_000_000)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)
    # SOLUSDEV-248: a protocol driver by id with generic parameters — never a closed list of
    # driver names in this schema; the registry decides what exists.
    driver_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    driver_params: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=32
    )


class RobotRealConfig(BaseModel):
    """A session from a Physical Robot's HardwareConfig (docs/api/hardware.md §6)."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["robot"]
    robot_entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class HardwareRealConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["hardware"]
    entity_id: uuid.UUID
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)


class BenchSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sim", "real"]
    config: Annotated[
        MujocoSimConfig
        | GazeboSimConfig
        | McapSimConfig
        | SerialRealConfig
        | RobotRealConfig
        | HardwareRealConfig,
        Field(discriminator="provider"),
    ]

    @model_validator(mode="after")
    def _mode_matches_provider(self) -> "BenchSessionIn":
        is_sim = self.config.provider in _SIM_PROVIDERS
        if is_sim != (self.mode == "sim"):
            raise ValueError(f"provider {self.config.provider!r} does not run in {self.mode} mode")
        return self


def get_session_manager(request: Request) -> SessionManager:
    manager: SessionManager = request.app.state.bench_sessions
    return manager


def get_bench_local(request: Request) -> Any:
    return request.app.state.bench_local


def _device_wire(device: Any) -> dict[str, Any]:
    """LocalDevice → wire dict (duck-typed: livebench types cross an optional
    import boundary, so this never imports them)."""
    identity = device.identity
    board = identity.board
    return {
        "device_path": identity.device,
        "by_id_path": device.by_id_path,
        "serial_number": identity.serial,
        "vid": f"{identity.vid:04x}",
        "pid": f"{identity.pid:04x}",
        "board": board.name if board is not None else None,
        "board_class": board.kind.value if board is not None else None,
        "mcu_known": identity.mcu_known,
        "confidence": identity.evidence.confidence,
        "ambiguous": device.ambiguous,
        "note": str(identity.evidence.evidence.get("note", "")),
    }


def _unavailable_sources() -> dict[str, Any]:
    reason = _RUNNER_ABSENT
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
            "devices": [_device_wire(d) for d in devices],
        }
    )


def _validated_mcap_path(settings: Any, raw: str) -> Path:
    root = settings.bench_data_root
    if not root:
        raise APIError(
            503,
            "source_unavailable",
            "MCAP replay is not configured on this server (bench_data_root unset)",
        )
    root_path = Path(root).resolve()
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root_path / candidate).resolve()
    if not resolved.is_relative_to(root_path):
        raise APIError(422, "validation_error", "mcap_path escapes the bench data root")
    if resolved.suffix != ".mcap":
        raise APIError(422, "validation_error", "mcap_path must name a .mcap file")
    if not resolved.is_file():
        raise APIError(422, "validation_error", "mcap_path does not exist")
    return resolved


def _session_opener(
    local: Any, settings: Any, project_id: uuid.UUID, body: BenchSessionIn
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any] | None]:
    """(open_conn, label, device) for the validated session config."""
    cfg = body.config
    if isinstance(cfg, MujocoSimConfig):

        async def open_mujoco() -> Any:
            return await local.open_mujoco(
                project_id=project_id,
                xml=cfg.mjcf_xml,
                scene_name=cfg.scene_name,
                sample_hz=cfg.sample_hz,
                duration_seconds=cfg.duration_seconds,
            )

        return open_mujoco, f"MuJoCo {cfg.scene_name}", None
    if isinstance(cfg, GazeboSimConfig):

        async def open_gazebo() -> Any:
            return await local.open_gazebo(list(cfg.topics), project_id=project_id)

        return open_gazebo, f"Gazebo ({len(cfg.topics)} topic(s))", None
    if isinstance(cfg, McapSimConfig):
        mcap_path = _validated_mcap_path(settings, cfg.mcap_path)

        async def open_mcap() -> Any:
            return await local.open_mcap(mcap_path, project_id=project_id, topics=cfg.topics)

        return open_mcap, f"MCAP replay {mcap_path.name}", None
    assert isinstance(cfg, SerialRealConfig)  # the robot provider is opened in start_session
    serial_cfg = cfg

    async def open_serial() -> Any:
        return await local.open_serial(
            serial_cfg.serial_number,
            project_id=project_id,
            baud=serial_cfg.baud,
            confirmed_device_path=serial_cfg.confirmed_device_path,
            driver_id=serial_cfg.driver_id,
            driver_params=serial_cfg.driver_params,
        )

    # Wire contract with the desktop's session-to-device matching: an explicit
    # pick rides `device_path`; serial-bound sessions leave it None.
    device = {
        "serial_number": serial_cfg.serial_number,
        "device_path": serial_cfg.confirmed_device_path,
        "baud": serial_cfg.baud,
        "driver_id": serial_cfg.driver_id,
    }
    return (
        open_serial,
        f"Serial {serial_cfg.serial_number or serial_cfg.confirmed_device_path}",
        device,
    )


async def _robot_opener(
    local: Any,
    session: AsyncSession,
    project_id: uuid.UUID,
    cfg: RobotRealConfig | HardwareRealConfig,
    account_id: uuid.UUID,
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any]]:
    """(open_conn, label, device) for a robot session: the config document is the truth."""
    robot = (
        await robot_root(session, project_id, cfg.robot_entity_id)
        if isinstance(cfg, RobotRealConfig)
        else await hardware_entity(session, project_id, cfg.entity_id)
    )
    config = await resolve_runtime_config(session, project_id, robot.id)
    if config.identity is None or config.protocol is None:
        raise APIError(
            422,
            "validation_error",
            "the robot's config has no transport identity or protocol yet — detect it or "
            "configure it before starting a session",
        )
    from solus_api.hardware.store import read_entity_config

    entry, owner_config = await read_entity_config(session, project_id, robot.id)
    if entry is None:
        raise APIError(422, "validation_error", "Configure this hardware before connecting.")
    document = await asyncio.to_thread(
        prepare_local_hardware,
        local,
        config,
        project_id,
        account_id,
        entry.id,
        owner_config=owner_config,
    )
    identity, protocol = config.identity, config.protocol

    async def open_robot() -> Any:
        return await open_local_hardware(local, document, project_id)

    device = {
        "device_ref": identity.device_ref,
        "driver_id": protocol.driver_id,
        "serial_number": identity.binding if identity.kind is TransportKind.USB_SERIAL else None,
        "device_path": getattr(identity, "last_seen_path", None),
        "baud": protocol.params.get("baud"),
    }
    return open_robot, f"Robot {robot.name} ({identity.device_ref})", device


@router.post("/sessions", status_code=201)
async def start_session(
    ctx: ProjectCtx, session: SessionDep, body: BenchSessionIn, request: Request
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    local = get_bench_local(request)
    if local is None:
        raise APIError(503, "source_unavailable", _RUNNER_ABSENT)
    settings = request.app.state.settings
    device: dict[str, Any] | None
    if isinstance(body.config, (RobotRealConfig, HardwareRealConfig)):
        open_conn, label, device = await _robot_opener(
            local, session, ctx.project.id, body.config, ctx.user.id
        )
    else:
        open_conn, label, device = _session_opener(local, settings, ctx.project.id, body)
    manager = get_session_manager(request)
    try:
        record = await manager.start(
            ctx.project.id,
            mode=body.mode,
            provider=body.config.provider,
            label=label,
            open_conn=open_conn,
            window_seconds=body.config.window_seconds,
            device=device,
        )
    except TooManySessionsError as exc:
        raise APIError(409, "too_many_sessions", str(exc)) from exc
    except AmbiguousDeviceError as exc:
        raise APIError(
            409,
            "device_ambiguous",
            "More than one device matches — pick one explicitly",
            details=[_device_wire(c) for c in exc.candidates],
        ) from exc
    except DeviceNotFoundError as exc:
        raise APIError(404, "device_not_found", str(exc)) from exc
    except APIError:
        raise
    except ValueError as exc:
        raise APIError(422, "validation_error", str(exc)) from exc
    except Exception as exc:
        # Honest degradation (§7): a source that cannot start is unavailable —
        # log the cause, never crash the route on device/simulator input.
        logger.exception("bench session start failed: provider=%s", body.config.provider)
        raise APIError(
            503, "source_unavailable", f"{body.config.provider} could not be started"
        ) from exc
    emit_event(
        session,
        user=ctx.user,
        event_type="bench.session_started",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"provider": body.config.provider, "mode": body.mode, "session_id": str(record.id)},
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
    emit_event(
        session,
        user=ctx.user,
        event_type="bench.session_stopped",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"provider": record.provider, "mode": record.mode, "session_id": str(record.id)},
    )
    await session.commit()
    return envelope(record.model_dump(mode="json"))


@router.get("/device-recent")
async def device_recent(
    ctx: ProjectCtx,
    request: Request,
    device_id: Annotated[list[str], Query(min_length=1, max_length=16)],
    limit: Annotated[int | None, Query(ge=1, le=512)] = None,
) -> dict[str, Any]:
    """Batched by design: the desktop polls every visible device panel in ONE
    request per cycle, so N streaming devices never multiply the request rate
    into the shared per-user budget."""
    plumbing = get_plumbing(request)
    for one in device_id:
        if not 1 <= len(one) <= 512:
            raise APIError(422, "validation_error", "device_id length out of range")
    views = [
        await plumbing.get_device_recent(ctx.project.id, one, limit=limit) for one in device_id
    ]
    return envelope({"devices": [v.model_dump(mode="json") for v in views]})
