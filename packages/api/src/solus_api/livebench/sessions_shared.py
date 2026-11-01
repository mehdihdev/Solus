"""Bench session configs and the session opener, shared by `POST /sessions` and the SOL
`bench.session_start` tool (docs/architecture/bench-view.md §5): both validate with the same
`BenchSessionIn` and open through the same path, so the two can never drift.

Moved verbatim from `bench_router.py` (SOLUSDEV-319 B6); the route's behaviour is unchanged.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.config import TransportKind
from solus_api.hardware.local_runtime import open_local_hardware, prepare_local_hardware
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import hardware_entity, robot_root
from solus_api.livebench.replay_provider import confined_file, replay_session
from solus_api.livebench.sessions import (
    AmbiguousDeviceError,
    BenchSessionOut,
    DeviceNotFoundError,
    SessionManager,
    TooManySessionsError,
)
from solus_api.models import User
from solus_api.services.events import emit_event

logger = logging.getLogger("solus_api.livebench.bench_router")

MAX_MJCF_BYTES = 2_000_000
MAX_TOPICS = 32
MAX_TOPIC_LEN = 256
MAX_SESSION_SECONDS = 3600.0
MAX_WINDOW_SECONDS = 60.0
RUNNER_ABSENT = "livebench is not installed on this server"
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


def device_wire(device: Any) -> dict[str, Any]:
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
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any], uuid.UUID]:
    """(open_conn, label, device, robot id) for a robot session: the config document is the
    truth, and the session's window evaluator judges the robot resolved here (P2-T3)."""
    robot = (
        await robot_root(session, project_id, cfg.robot_entity_id)
        if isinstance(cfg, RobotRealConfig)
        else await hardware_entity(session, project_id, cfg.entity_id)
    )
    # SOLUSDEV-320 P5-T4: a robot whose host was confirmed opens only on that host.
    bound = robot.attrs.get("host_machine_id")
    if bound is not None:
        from solus_api.hardware.host_topology import LocalHostProvider

        host = await LocalHostProvider(local).identity()
        if host is not None and host != bound:
            raise APIError(
                409,
                "host_mismatch",
                "This robot is bound to another host machine; start the session there",
                details=[{"host_machine_id": bound, "local_host_id": host}],
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
        # The UI's per-robot panel key; a part-level (hardware) session names no robot.
        **({"robot_entity_id": str(robot.id)} if isinstance(cfg, RobotRealConfig) else {}),
    }
    return open_robot, f"Robot {robot.name} ({identity.device_ref})", device, robot.id


@dataclass(frozen=True)
class ResolvedSession:
    """What a validated body opens: nothing is opened until `open_conn` is awaited."""

    open_conn: Callable[[], Awaitable[Any]]
    label: str
    device: dict[str, Any] | None
    robot_entity_id: uuid.UUID | None


async def resolve_session(
    local: Any,
    settings: Any,
    session: AsyncSession,
    project_id: uuid.UUID,
    body: BenchSessionIn,
    account_id: uuid.UUID,
) -> ResolvedSession:
    """The opener, label and device for `body`. Raises the route's APIErrors (404, 409, 422,
    503). Opens nothing, so a SOL card can show the label before anything starts."""
    if isinstance(body.config, ReplayRealConfig):
        return ResolvedSession(
            *await replay_session(local, session, project_id, body.config, settings)
        )
    if isinstance(body.config, (RobotRealConfig, HardwareRealConfig)):
        return ResolvedSession(
            *await _robot_opener(local, session, project_id, body.config, account_id)
        )
    open_conn, label, device = _session_opener(local, settings, project_id, body)
    return ResolvedSession(open_conn, label, device, None)


async def start_resolved_session(
    manager: SessionManager,
    project_id: uuid.UUID,
    body: BenchSessionIn,
    resolved: ResolvedSession,
    owner_user_id: uuid.UUID,
) -> BenchSessionOut:
    """Start the session, mapping the manager's failures onto the route's APIErrors."""
    try:
        return await manager.start(
            project_id,
            mode=body.mode,
            provider=body.config.provider,
            label=resolved.label,
            open_conn=resolved.open_conn,
            window_seconds=body.config.window_seconds,
            device=resolved.device,
            robot_entity_id=resolved.robot_entity_id,
            owner_user_id=owner_user_id,
        )
    except TooManySessionsError as exc:
        raise APIError(409, "too_many_sessions", str(exc)) from exc
    except AmbiguousDeviceError as exc:
        raise APIError(
            409,
            "device_ambiguous",
            "More than one device matches — pick one explicitly",
            details=[device_wire(c) for c in exc.candidates],
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


def emit_session_event(
    session: AsyncSession,
    *,
    user: User,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    started: bool,
    record: BenchSessionOut,
    actor: Literal["sol"] | None = None,
) -> None:
    """`bench.session_started` / `_stopped`; a SOL tool adds `actor: "sol"` (additive)."""
    payload: dict[str, Any] = {
        "provider": record.provider,
        "mode": record.mode,
        "session_id": str(record.id),
    }
    if actor is not None:
        payload["actor"] = actor
    emit_event(
        session,
        user=user,
        event_type="bench.session_started" if started else "bench.session_stopped",
        team_id=team_id,
        project_id=project_id,
        payload=payload,
    )
