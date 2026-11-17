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
from solus_api.graph.read_scope import current_scope
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.hardware.local_runtime import plan_session, prepare_session
from solus_api.hardware.store import hardware_entity, robot_root
from solus_api.livebench.replay_provider import confined_file, replay_session
from solus_api.livebench.sessions import (
    AmbiguousDeviceError,
    BenchSessionOut,
    DeviceBusyError,
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
        self._events: dict[uuid.UUID, deque[tuple[uuid.UUID | None, dict[str, Any]]]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def append(
        self,
        project_id: uuid.UUID,
        event: ObserverEventIn,
        *,
        finding_id: uuid.UUID | None = None,
        owner: uuid.UUID | None = None,
    ) -> None:
        """`finding_id` (SOLUSDEV-321 P2-T3) is attached here, to the ring's own record, by the
        server that raised the finding: `ObserverEventIn` has no such field, so an ingested event
        can never carry one, and `recent` hands out only the ids attached here."""
        record = event.model_dump(mode="json")
        if finding_id is not None:
            record["finding_id"] = str(finding_id)
        # SOLUSDEV-326: `owner` is the entity its writer resolved the event's device to, kept
        # from when it was recorded (a session's sim alias included); never in the payload.
        self._events[project_id].append((owner, record))

    def record(self, project_id: uuid.UUID, event: dict[str, Any], owner: uuid.UUID | None) -> None:
        """A bench session's event sink: the event as its session resolved its device."""
        self.append(project_id, ObserverEventIn.model_validate(event), owner=owner)

    def owned(
        self, project_id: uuid.UUID, limit: int
    ) -> list[tuple[uuid.UUID | None, dict[str, Any]]]:
        """The newest `limit` records, each with the entity it was attributed to."""
        return list(self._events.get(project_id, ()))[-limit:]

    def recent(self, project_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        return [record for _, record in self.owned(project_id, limit)]


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
    owners = {  # attributed as this route's packets resolve: by device alone
        device: await plumbing.resolve(ctx.project.id, device)
        for device in {event.device_id for event in body.events}
    }
    for event in body.events:
        ring.append(ctx.project.id, event, owner=owners[event.device_id])
    return envelope({"accepted": accepted, "unresolved": unresolved, "rejected": rejected})


@router.get("/telemetry-devices")
async def observed_telemetry_devices(
    ctx: ProjectCtx, session: SessionDep, request: Request
) -> dict[str, Any]:
    # SOLUSDEV-326: a device on hardware another member keeps out of the graph is left out.
    hidden = await current_scope(ctx.project.id).hidden_ids(session)
    devices = get_plumbing(request).observed_device_ids(ctx.project.id, exclude=hidden)
    return envelope({"device_ids": devices})


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
    if (
        entity is None
        or entity.project_id != ctx.project.id
        or entity.deleted_at is not None
        or current_scope(ctx.project.id).hides(entity.attrs)  # SOLUSDEV-326: not theirs to see
    ):
        raise APIError(404, "not_found", "Entity not found")
    view = await get_plumbing(request).get_recent_values(
        ctx.project.id, entity_id, signals=signals, limit=limit
    )
    return envelope(view.model_dump(mode="json"))


@router.get("/summary")
async def telemetry_summary(
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    duration_seconds: Annotated[float, Query(gt=0, le=MAX_SUMMARY_SECONDS)],
    signals: Annotated[list[str] | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    window = TelemetryWindow(duration_seconds=duration_seconds, signals=signals)
    hidden = await current_scope(ctx.project.id).hidden_ids(session)  # SOLUSDEV-326
    view = await get_plumbing(request).get_telemetry(ctx.project.id, window, exclude=hidden)
    return envelope(view.model_dump(mode="json"))


@router.get("/events")
async def recent_events(
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS_KEPT)] = 100,
) -> dict[str, Any]:
    events = get_event_ring(request).owned(ctx.project.id, limit)
    hidden = await current_scope(ctx.project.id).hidden_ids(session)
    if hidden:  # SOLUSDEV-326: an event on hardware another member keeps out of the graph,
        # attributed when it was recorded (a sim alias included) or by its device now.
        plumbing = get_plumbing(request)
        now = {
            device: await plumbing.resolve(ctx.project.id, device)
            for device in {event["device_id"] for _, event in events}
        }
        events = [
            (owner, event)
            for owner, event in events
            if owner not in hidden and now[event["device_id"]] not in hidden
        ]
    return envelope([event for _, event in events])


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
_GAZEBO_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"  # never option-shaped, never text-format syntax


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
    """Manual `topics`, or (SOLUSDEV-322 P3-T5) a `world` + `model` whose joint_state stream the
    livebench source derives for the installed (or named) Gazebo `family`."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gazebo"]
    topics: list[str] = Field(default_factory=list, max_length=MAX_TOPICS)
    family: Literal["classic", "ignition", "gz"] | None = None
    world: str | None = Field(default=None, pattern=_GAZEBO_NAME, max_length=64)
    model: str | None = Field(default=None, pattern=_GAZEBO_NAME, max_length=64)
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("topics")
    @classmethod
    def _bound_topics(cls, topics: list[str]) -> list[str]:
        return _clean_topics(topics)

    @model_validator(mode="after")
    def _topics_or_model(self) -> "GazeboSimConfig":
        if (self.world is None) != (self.model is None):
            raise ValueError("world and model go together")
        if not self.topics and self.world is None:
            raise ValueError("give topics, or a world and model")
        return self


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


class ReplayRealConfig(BaseModel):
    """DEV ONLY (docs/api/bench-runs.md): a recorded capture replayed as one of the project's
    robots. `recording` is a file under `Settings.bench_replay_root`; `driver_id` decodes it."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["replay"]
    recording: str = Field(min_length=1, max_length=4096)
    driver_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    robot_entity_id: uuid.UUID
    realtime: bool = True
    window_seconds: float = Field(default=1.0, gt=0, le=MAX_WINDOW_SECONDS)

    @field_validator("recording")
    @classmethod
    def _printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("recording may not contain control characters")
        return value


class BenchSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sim", "real"]
    config: Annotated[
        MujocoSimConfig
        | GazeboSimConfig
        | McapSimConfig
        | SerialRealConfig
        | RobotRealConfig
        | HardwareRealConfig
        | ReplayRealConfig,
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
        "headline": getattr(board, "headline", None),
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
    return confined_file(root, raw, field="mcap_path", root_name="bench data root", suffix=".mcap")


def _session_opener(
    local: Any, settings: Any, project_id: uuid.UUID, body: BenchSessionIn, user_id: uuid.UUID
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any] | None]:
    """(open_conn, label, device) for the validated session config; a serial device is claimed
    for `user_id`, the requesting member (SOLUSDEV-326)."""
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
        gazebo_cfg = cfg

        async def open_gazebo() -> Any:
            return await local.open_gazebo(
                list(gazebo_cfg.topics),
                project_id=project_id,
                family=gazebo_cfg.family,
                world=gazebo_cfg.world,
                model=gazebo_cfg.model,
            )

        label = (
            f"Gazebo {gazebo_cfg.world}/{gazebo_cfg.model}"
            if gazebo_cfg.world
            else f"Gazebo ({len(gazebo_cfg.topics)} topic(s))"
        )
        return open_gazebo, label, None
    if isinstance(cfg, McapSimConfig):
        mcap_path = _validated_mcap_path(settings, cfg.mcap_path)

        async def open_mcap() -> Any:
            return await local.open_mcap(mcap_path, project_id=project_id, topics=cfg.topics)

        return open_mcap, f"MCAP replay {mcap_path.name}", None
    assert isinstance(cfg, SerialRealConfig)  # the robot provider is opened in start_session
    serial_cfg = cfg

    async def open_serial() -> Any:
        try:
            return await local.open_serial(
                serial_cfg.serial_number,
                project_id=project_id,
                user_id=user_id,
                baud=serial_cfg.baud,
                confirmed_device_path=serial_cfg.confirmed_device_path,
                driver_id=serial_cfg.driver_id,
                driver_params=serial_cfg.driver_params,
            )
        except DeviceBusyError as exc:  # SOLUSDEV-326: busy is never "could not be started"
            raise APIError(409, "device_busy", str(exc), details=exc.details()) from exc

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
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any], uuid.UUID, bool]:
    """(open_conn, label, device, subject id, evaluate) for a robot or hardware session: the
    config document is the truth, opened through the one shared opener (SOLUSDEV-326) — the
    host check, each brain this host reaches, the others reported on the session's device."""
    subject = (
        await robot_root(session, project_id, cfg.robot_entity_id)
        if isinstance(cfg, RobotRealConfig)
        else await hardware_entity(session, project_id, cfg.entity_id)
    )
    plan = await plan_session(local, session, project_id, subject)
    opener = await prepare_session(local, plan, account_id)
    return opener.open, opener.label, opener.device, subject.id, opener.evaluate


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
    robot_entity_id: uuid.UUID | None = None
    evaluate = True
    if isinstance(body.config, ReplayRealConfig):
        open_conn, label, device, robot_entity_id = await replay_session(
            local, session, ctx.project.id, body.config, settings
        )
    elif isinstance(body.config, (RobotRealConfig, HardwareRealConfig)):
        open_conn, label, device, robot_entity_id, evaluate = await _robot_opener(
            local, session, ctx.project.id, body.config, ctx.user.id
        )
    else:
        open_conn, label, device = _session_opener(
            local, settings, ctx.project.id, body, ctx.user.id
        )
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
            robot_entity_id=robot_entity_id,
            owner_user_id=ctx.user.id,
            evaluate=evaluate,
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
    session: SessionDep,
    request: Request,
    status: Annotated[Literal["active", "ended"] | None, Query()] = None,
    mode: Annotated[Literal["sim", "real"] | None, Query()] = None,
) -> dict[str, Any]:
    records = get_session_manager(request).list(ctx.project.id, status=status, mode=mode)
    # SOLUSDEV-326: a session of hardware another member keeps out of the graph is left out.
    hidden = await current_scope(ctx.project.id).hidden_ids(session)
    return envelope([r.model_dump(mode="json") for r in records if r.robot_entity_id not in hidden])


async def _visible_session(
    session: AsyncSession, request: Request, project_id: uuid.UUID, session_id: uuid.UUID
) -> BenchSessionOut:
    """404 for an unknown session, and (SOLUSDEV-326) for one of hardware the caller cannot see."""
    try:
        record = get_session_manager(request).get(project_id, session_id)
    except SessionNotFoundError as exc:
        raise APIError(404, "not_found", "Session not found") from exc
    if record.robot_entity_id in await current_scope(project_id).hidden_ids(session):
        raise APIError(404, "not_found", "Session not found")
    return record


@router.get("/sessions/{session_id}")
async def session_detail(
    ctx: ProjectCtx, session: SessionDep, request: Request, session_id: uuid.UUID
) -> dict[str, Any]:
    record = await _visible_session(session, request, ctx.project.id, session_id)
    return envelope(record.model_dump(mode="json"))


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    ctx: ProjectCtx, session: SessionDep, request: Request, session_id: uuid.UUID
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await _visible_session(session, request, ctx.project.id, session_id)
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
    # SOLUSDEV-326: unfocused, a device on hardware another member keeps out of the graph is left
    # out; a focus already reaches only what the caller sees.
    hidden = (
        await current_scope(ctx.project.id).hidden_ids(session) if allowed is None else frozenset()
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
        if (
            allowed is not None and view.resolved_entity_id not in allowed
        ) or view.resolved_entity_id in hidden:
            continue
        device = view.model_dump(mode="json")
        roles = manager.channel_roles(ctx.project.id, view.device_id)
        display = manager.channel_display(ctx.project.id, view.device_id)
        for series in device["signals"]:
            if series["signal"] in roles:
                series["display_role"] = roles[series["signal"]]
            series.update(display.get(series["signal"], {}))
        devices.append(device)
    return envelope({"devices": devices})
