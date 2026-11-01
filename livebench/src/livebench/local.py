"""Local source catalog for the bench-session routes (SOLUSDEV-72).

What is on THIS machine, honestly: simulators probed without importing them, and
serial devices keyed by USB serial number rather than tty path. The API loads
this module through an optional runtime import (no declared dependency — the
package arrow points livebench → solus-api), so a server without livebench
reports every local source unavailable instead of lying or crashing.

Identity rule (the safety property): a `real` session binds to a device by its
USB serial, resolved here to the `/dev/serial/by-id` symlink that EMBEDS that
serial — so a reconnect after re-enumeration reopens the same physical arm, never
whatever inherited its old tty number. Identical or absent serials refuse with
candidates rather than guess (RBT-03 posture); an explicit, still-enumerated
user-confirmed path is the only way past that refusal.

Factories lazy-import their heavy modules: listing availability must never pay
for (or crash on) `import mujoco`.
"""

import asyncio
import dataclasses
import importlib.util
import logging
import re
import shutil
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from solus_api.hardware.config import (
    FieldProvenance,
    HardwareConfig,
    ProtocolBinding,
    ProvenanceRecord,
    TransportBinding,
    TransportKind,
)
from solus_api.livebench.sessions import AmbiguousDeviceError, DeviceNotFoundError
from solus_api.livebench.teleop import NotActuatedError, TeleopNotReadyError

from livebench.recognition.passive import (
    PORT_BINDING_PREFIX,
    PortIdentity,
    binding_key,
    enumerate_usb_serial,
)
from livebench.telemetry.stream_live import PacketStreamLiveConnection

if TYPE_CHECKING:
    from livebench.hardware.actuation import Actuator
    from livebench.hardware.connection import RobotConnection
    from livebench.hardware.replay import Recording
    from livebench.setpoint import SetpointMove, SetpointPreview
    from livebench.teleop import TeleopLoop, TeleopPreview

__all__ = [
    "AmbiguousDeviceError",
    "DeviceNotFoundError",
    "available_simulators",
    "list_devices",
    "resolve_serial_device",
    "open_mujoco",
    "open_gazebo",
    "open_mcap",
    "open_replay",
    "open_robot",
    "open_serial",
    "detect_devices",
    "propose_device",
    "teleop_preview",
    "teleop_start",
    "robot_release",
    "setpoint_preview",
    "setpoint_apply",
    "setpoint_status",
    "setpoint_stop",
]

logger = logging.getLogger(__name__)

#: Where an Isaac Sim build normally lives on a dev box; overridable per call.
DEFAULT_ISAAC_ROOT = Path.home() / "isaacsim"

#: LB-01's hinged rod: real physics (gravity swings it from rest, `qvel` climbs),
#: small enough to compile instantly. The one-click demo scene.
DEMO_SCENE_NAME = "demo"
DEMO_SCENE_XML = """
<mujoco model="demo">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <body name="arm" pos="0 0 1">
      <joint name="rod" type="hinge" axis="0 1 0"/>
      <geom name="rod_geom" type="capsule" fromto="0 0 0 0.5 0 0" size="0.02" mass="1"/>
    </body>
  </worldbody>
</mujoco>
"""

_DEFAULT_BAUD = 115200


@dataclass(frozen=True)
class SimulatorAvailability:
    """One simulator's honest presence claim on this machine."""

    kind: str
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class LocalDevice:
    """One enumerated serial device plus its stable-identity facts."""

    identity: PortIdentity
    by_id_path: str | None
    ambiguous: bool


def available_simulators(
    *,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
    which: Callable[[str], str | None] = shutil.which,
    isaac_root: Path = DEFAULT_ISAAC_ROOT,
) -> list[SimulatorAvailability]:
    """Probe-only: no simulator module is imported to answer "is it here?"."""
    mujoco_present = find_spec("mujoco") is not None
    gz = which("gz")
    isaac_present = isaac_root.is_dir()
    return [
        SimulatorAvailability(
            kind="mujoco",
            available=mujoco_present,
            reason=None if mujoco_present else "mujoco is not installed on this machine",
        ),
        SimulatorAvailability(
            kind="gazebo",
            available=gz is not None,
            reason=None if gz else "Gazebo is not installed (no `gz` CLI on PATH)",
        ),
        SimulatorAvailability(
            kind="isaac",
            available=False,  # never a startable session provider (ADR-014: read its data)
            reason=(
                "Isaac Sim detected — stream live via the Isaac direct script, "
                "or replay an MCAP recording"
                if isaac_present
                else "Isaac Sim is not installed on this machine"
            ),
        ),
    ]


def _by_id_map(by_id_dir: Path) -> dict[str, str]:
    """`realpath(device) → by-id symlink` for every stable serial alias present."""
    if not by_id_dir.is_dir():
        return {}
    mapping: dict[str, str] = {}
    for link in sorted(by_id_dir.iterdir()):
        try:
            mapping[str(link.resolve())] = str(link)
        except OSError:  # a vanished symlink mid-scan is not an error
            continue
    return mapping


def list_devices(
    *,
    identities: list[PortIdentity] | None = None,
    by_id_dir: Path = Path("/dev/serial/by-id"),
) -> list[LocalDevice]:
    """Enumerated USB-serial devices with by-id paths and ambiguity flags.

    A device is ambiguous when it has no binding key or shares it with another
    device — exactly the cases where binding cannot discriminate and the UI must
    make the user pick explicitly.
    """
    found = enumerate_usb_serial() if identities is None else identities
    by_id = _by_id_map(by_id_dir)
    counts = Counter(key for identity in found if (key := binding_key(identity)) is not None)
    return [
        LocalDevice(
            identity=identity,
            by_id_path=by_id.get(identity.device),
            ambiguous=(key := binding_key(identity)) is None or counts[key] > 1,
        )
        for identity in found
    ]


def resolve_serial_device(
    serial_number: str | None,
    *,
    identities: list[PortIdentity] | None = None,
    by_id_dir: Path = Path("/dev/serial/by-id"),
    confirmed_device_path: str | None = None,
    vid: int | None = None,
    pid: int | None = None,
) -> str:
    """The path to OPEN for one physical device, bound by USB serial (or, for a
    serial-less device, its `port-<location>` position — see `binding_key`).

    Prefers the `/dev/serial/by-id` alias (stable across re-enumeration, and it
    embeds the serial — reopening it re-verifies identity by construction).
    Refuses rather than guesses: unknown binding, duplicated binding, or a
    binding-less device without an explicit confirmed pick all raise. A port
    binding names the PORT, so when the caller knows the bound device's vid/pid
    whatever sits there now must still carry them — else reconnect it to verify.
    """
    devices = list_devices(identities=identities, by_id_dir=by_id_dir)
    if serial_number is None:
        if confirmed_device_path is None:
            raise DeviceNotFoundError("no serial number and no user-confirmed device path")
        live = {d.identity.device for d in devices} | {
            d.by_id_path for d in devices if d.by_id_path
        }
        if confirmed_device_path not in live:
            raise DeviceNotFoundError(
                f"confirmed path {confirmed_device_path!r} is not an enumerated device"
            )
        return confirmed_device_path
    matches = [d for d in devices if binding_key(d.identity) == serial_number]
    if not matches:
        raise DeviceNotFoundError(f"no device with binding {serial_number!r}")
    if vid is not None and pid is not None and serial_number.startswith(PORT_BINDING_PREFIX):
        matches = [d for d in matches if (d.identity.vid, d.identity.pid) == (vid, pid)]
        if not matches:
            raise DeviceNotFoundError(
                f"{serial_number!r} now fronts a different device — reconnect it to verify"
            )
    if len(matches) > 1:
        if confirmed_device_path is not None and any(
            confirmed_device_path in (d.identity.device, d.by_id_path) for d in matches
        ):
            return confirmed_device_path
        raise AmbiguousDeviceError(matches)
    chosen = matches[0]
    return chosen.by_id_path or chosen.identity.device


# ── factories (lazy imports: listing never pays for these) ──────────────────────


#: MJCF constructs that reach the filesystem. User-supplied XML must never read
#: the host: `<include file=…>` / asset `file=` are an arbitrary-read + existence
#: oracle, and the *dir attributes re-root relative reads. Token scan, fail
#: closed — ponytail: a denylist over the raw text beats trusting an XML walk to
#: enumerate every file-bearing element across mujoco versions.
_MJCF_FILE_PATTERN = re.compile(
    r"(<include|file\s*=|meshdir|texturedir|assetdir|modelfiledir)", re.IGNORECASE
)


def _reject_file_referencing_mjcf(xml: str) -> None:
    match = _MJCF_FILE_PATTERN.search(xml)
    if match is not None:
        raise ValueError(
            f"mjcf_xml may not reference files on disk (found {match.group(1).lower()!r})"
        )


async def open_mujoco(
    *,
    project_id: UUID,
    duration_seconds: float,
    scene_name: str = DEMO_SCENE_NAME,
    xml: str | None = None,
    sample_hz: float = 50.0,
) -> PacketStreamLiveConnection:
    """A realtime MuJoCo connection. `realtime` is forced on and the duration is
    required: a non-realtime run busy-loops the hosting event loop forever."""
    from livebench.sim.connections import MuJoCoSimConnection

    if xml is not None:
        _reject_file_referencing_mjcf(xml)

    def build() -> MuJoCoSimConnection:  # model compile is sync — off-loop
        try:
            return MuJoCoSimConnection(
                xml if xml is not None else DEMO_SCENE_XML,
                scene_name=scene_name,
                start_time=datetime.now(UTC),
                sample_hz=sample_hz,
                duration_seconds=duration_seconds,
                realtime=True,
                project_id=project_id,
            )
        except ValueError as exc:
            # The compiler's own text can leak host details for probing inputs —
            # log it, return a fixed message (routes echo ValueError bodies).
            logger.warning("MuJoCo compile failed: %s", str(exc)[:500])
            raise ValueError("invalid MuJoCo model XML (compile failed)") from None

    return await asyncio.to_thread(build)


async def open_gazebo(topics: list[str], *, project_id: UUID) -> PacketStreamLiveConnection:
    """A Gazebo topic connection; raises `GazeboNotAvailableError` when gz is absent."""
    from livebench.sim.connections import GazeboSimConnection

    return GazeboSimConnection(topics, project_id=project_id)


async def open_mcap(
    path: Path, *, project_id: UUID, topics: list[str] | None = None
) -> PacketStreamLiveConnection:
    """An MCAP replay connection (the Isaac read-path, and any recorded run)."""
    from livebench.sim.connections import McapReplaySimConnection

    return McapReplaySimConnection(path, topics=topics, project_id=project_id)


async def open_serial(
    serial_number: str | None,
    *,
    project_id: UUID,
    baud: int = _DEFAULT_BAUD,
    confirmed_device_path: str | None = None,
    driver_id: str | None = None,
    driver_params: Mapping[str, Any] | None = None,
) -> PacketStreamLiveConnection:
    """A serial robot connection bound by USB serial (see `resolve_serial_device`).
    The blocking pyserial open runs off-loop. With a `driver_id` the link opens through the
    protocol-driver registry (SOLUSDEV-248) instead of the passive LB-06 line reader."""
    from livebench.telemetry.robot import SerialRobotConnection

    if driver_id is not None:
        if serial_number is None:
            raise ValueError("a driver session binds by USB serial number")
        document = HardwareConfig(
            robot_entity_id=UUID(int=0),
            identity=TransportBinding(kind=TransportKind.USB_SERIAL, binding=serial_number),
            protocol=ProtocolBinding(
                driver_id=driver_id, params={"baud": baud, **dict(driver_params or {})}
            ),
            provenance={
                "identity": ProvenanceRecord(by=FieldProvenance.DETECTED),
                "protocol": ProvenanceRecord(by=FieldProvenance.USER),
            },
        )
        return await open_robot(document.model_dump(mode="json"), project_id=project_id)

    def _open() -> PacketStreamLiveConnection:
        # Enumeration + the pyserial open both block — resolve AND open off-loop.
        device = resolve_serial_device(serial_number, confirmed_device_path=confirmed_device_path)
        return SerialRobotConnection.open(device, baud, project_id=project_id)

    return await asyncio.to_thread(_open)


def _read_unmoved(path: Path, max_bytes: int | None) -> "Recording | None":
    """The capture at `path`, read off-loop and at most `max_bytes` long; None when `path` is no
    longer its own `resolve()`. The API hands it over resolved, so a symlink there now is a swap,
    and so is a symlink loop, whose error would name the server's path: only its type is logged."""
    from livebench.hardware.replay import load_recording

    try:
        moved = path.resolve() != path
    except (OSError, RuntimeError) as exc:
        logger.warning("replay recording could not be re-checked: %s", type(exc).__name__)
        moved = True
    return None if moved else load_recording(path, max_bytes=max_bytes)


async def open_replay(config: Mapping[str, Any], *, project_id: UUID) -> "RobotConnection":
    """DEV ONLY (SOLUSDEV-321 P2-T4): a recorded capture opened as a configured robot, so the
    pane and the window evaluator can be driven with no hardware. `config` carries the robot's
    HardwareConfig as `document` (its protocol the driver the capture is decoded with), the
    capture's `recording` path (the API has confined it and hands over the resolved one), the
    `max_bytes` it checked the file against (the read is bounded by it too) and `realtime`
    (pace the frames by their recorded times; the default).

    The capture opens through the SAME transport → driver → part-routing path as a live robot;
    only the transport differs. It is registered, for this one connection, on a scratch registry
    (never the process-wide one) and the link does not reconnect: a replay is not restarted.
    A capture of another device than the robot's is refused — the robot's parts would be fed by
    a stranger's frames, or by none — and what the file says, and where it is, is never echoed
    or logged: a refusal logs the exception's type only."""
    from livebench.hardware import registries as hardware_registries
    from livebench.hardware.channel import TransportRegistry
    from livebench.hardware.connection import open_robot_connection
    from livebench.hardware.replay import replay_opener

    document = HardwareConfig.model_validate(config["document"])
    path = Path(config["recording"])
    try:
        recording = await asyncio.to_thread(_read_unmoved, path, config.get("max_bytes"))
    except (OSError, LookupError, TypeError, ValueError, RecursionError) as exc:  # M75: deep nest
        logger.warning("replay recording unreadable: %s", type(exc).__name__)
        raise ValueError("the recording could not be read") from None
    if recording is None:
        raise ValueError("the recording moved after it was checked")
    identity = recording.identity
    if document.identity is None or (identity.kind, identity.binding) != (
        document.identity.kind,
        document.identity.binding,
    ):
        raise ValueError("the recording was captured from another device than this robot's")
    transports = TransportRegistry()
    transports.register(
        identity.kind, replay_opener(recording, realtime=bool(config.get("realtime", True)))
    )
    return await asyncio.to_thread(
        open_robot_connection,
        document,
        project_id=project_id,
        transports=transports,
        drivers=hardware_registries.default_registries().drivers,
        reconnect=False,
    )


def _detected_wire(device: Any) -> dict[str, Any]:
    """DetectedDevice → plain dict (crosses the optional-import boundary duck-typed)."""
    return {
        "transport": device.transport.value,
        "device_ref": device.device_ref,
        "identity": device.identity.model_dump(mode="json") if device.identity else None,
        "level": device.level,
        "board": device.board,
        "board_class": device.board_class,
        "mcu_known": device.mcu_known,
        "confidence": device.confidence,
        "evidence": [m.model_dump(mode="json") for m in device.evidence],
        "ambiguous": device.ambiguous,
        "last_seen_path": device.last_seen_path,
        "vid": device.vid,
        "pid": device.pid,
        "headline": device.headline,
        "identity_basis": device.identity_basis,
    }


def _repo_match_wire(match: Any) -> dict[str, Any]:
    return {
        "config_id": match.config_id,
        "parser_id": match.parser_id,
        "label": match.label,
        "source": match.source,
        "protocol_hint": match.protocol_hint,
        "parts": [
            {
                "name": part.name,
                "address": part.address,
                "model": part.model,
                "calibration_mode": (
                    part.calibration_mode.value if part.calibration_mode is not None else None
                ),
                "calibration": part.calibration,
                "calibration_source": part.calibration_source,
            }
            for part in match.parts
        ],
        "port_hint": match.port_hint,
        "calibration_source": match.calibration_source,
        "params": dict(match.params),
    }


def _proposal_wire(proposal: Any) -> dict[str, Any]:
    return {
        "device_ref": proposal.device_ref,
        "identity": proposal.identity.model_dump(mode="json") if proposal.identity else None,
        "level": proposal.level,
        "summary": proposal.summary,
        "driver_id": proposal.driver_id,
        "params": dict(proposal.params),
        "rows": [
            {
                "id": row.id,
                "subject": row.subject,
                "address": row.address,
                "model": row.model,
                "proposed_function": row.proposed_function,
                "confidence": row.confidence,
                "evidence": [m.model_dump(mode="json") for m in row.evidence],
                "provenance": row.provenance,
            }
            for row in proposal.rows
        ],
        "repo_matches": [_repo_match_wire(m) for m in proposal.repo_matches],
        "disambiguation": (
            {
                "question": proposal.disambiguation.question,
                "options": proposal.disambiguation.options,
                "favoured": proposal.disambiguation.favoured,
            }
            if proposal.disambiguation is not None
            else None
        ),
        "confidence": proposal.confidence,
        "evidence": [m.model_dump(mode="json") for m in proposal.evidence],
        "calibration_source": proposal.calibration_source,
        "headline": proposal.headline,
        "tone": proposal.tone,
        "stream": dataclasses.asdict(proposal.stream) if proposal.stream is not None else None,
        "identity_basis": proposal.identity_basis,
    }


def detect_devices() -> list[dict[str, Any]]:
    """Every USB-serial device on this machine at its honest level (opens no port)."""
    from livebench.hardware.detection import enumerate_devices

    return [_detected_wire(d) for d in enumerate_devices(list_devices=list_devices)]


def propose_device(
    device_ref: str,
    *,
    repo_root: str | None = None,
    budget_s: float = 0.5,
    repo_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Interrogate one detected device safely and build its proposal; None when the device is
    not here. BLOCKING (ports are opened): callers run it off-loop."""
    from livebench.hardware import registries as hardware_registries
    from livebench.hardware.detection import enumerate_devices, interrogate_device, propose
    from livebench.hardware.repo_config import match_configs, parse_repo_sources, scan_repo

    device = next(
        (d for d in enumerate_devices(list_devices=list_devices) if d.device_ref == device_ref),
        None,
    )
    if device is None or device.identity is None:
        return None
    registries = hardware_registries.default_registries()
    interrogations = interrogate_device(device.identity, registries=registries, budget_s=budget_s)
    matches: list[Any] = []
    if (repo_root or repo_sources) and interrogations:
        best = max(interrogations, key=lambda i: i.confidence)
        configs = (
            parse_repo_sources(repo_sources, registries.repo_parsers)
            if repo_sources
            else scan_repo(Path(repo_root or ""), registries.repo_parsers)
        )
        matches = match_configs(best.bus_map, configs)
    return _proposal_wire(propose(device, interrogations, repo_matches=matches))


async def open_robot(config: Mapping[str, Any], *, project_id: UUID) -> "RobotConnection":
    """A configured robot's connection (SOLUSDEV-248): transport identity, driver id and
    parameters all come from the HardwareConfig document; the plugin registries do the rest.
    An invalid document is a ValueError; an absent device surfaces as the identity error the
    routes already map (404/409), anything else as unavailable."""
    from livebench.hardware import registries as hardware_registries
    from livebench.hardware.channel import TransportUnavailableError
    from livebench.hardware.connection import open_robot_connection

    document = HardwareConfig.model_validate(config)
    registries = hardware_registries.default_registries()
    try:
        return await asyncio.to_thread(
            open_robot_connection,
            document,
            project_id=project_id,
            transports=registries.transports,
            drivers=registries.drivers,
        )
    except TransportUnavailableError as exc:
        cause = exc.__cause__
        if isinstance(cause, DeviceNotFoundError | AmbiguousDeviceError):
            raise cause from None
        raise


def presence_provider() -> Any:
    """Discover an installed presence implementation through the plugin boundary."""
    from livebench.plugins import presence_provider as discover

    return discover()


def session_observers() -> Any:
    """Fresh bounded statistics for one local session; no hardware side effects."""
    from livebench.anomaly.session import SessionObservers

    return SessionObservers()


# ── teleoperation (SOLUSDEV-319, ADR-014 amendment 2026-10-30) ──────────────────


def _actuator(conn: Any) -> "Actuator":
    actuator = getattr(conn, "actuator", None)
    if actuator is None:
        raise NotActuatedError("this robot's driver can be read but not driven")
    return actuator  # type: ignore[no-any-return]


def _preview_wire(result: "TeleopPreview") -> dict[str, Any]:
    from livebench.teleop import TOLERANCE

    return {
        "ready": result.ready,
        "blockers": [
            {"code": b.code, "message": b.message, "address": b.address} for b in result.blockers
        ],
        "pairs": [
            {
                "address": r.pair.address,
                "leader_signal": r.pair.leader_signal,
                "follower_signal": r.pair.follower_signal,
                "unit": r.pair.unit,
                "leader_value": r.leader_value,
                "follower_value": r.follower_value,
                "delta": r.delta,
                "within_tolerance": r.within_tolerance,
            }
            for r in result.pairs
        ],
        "tolerance": dict(TOLERANCE),
    }


def teleop_preview(leader_conn: Any, follower_conn: Any) -> dict[str, Any]:
    """Where both robots are now, joint by joint. BLOCKING (reads both buses)."""
    from livebench.hardware.actuation import ActuatorUnavailableError
    from livebench.teleop import Blocker, TeleopPreview, preview

    leader, follower = _actuator(leader_conn), _actuator(follower_conn)
    try:
        return _preview_wire(preview(leader, follower))
    except (ActuatorUnavailableError, OSError):
        gap = Blocker("link_unavailable", "A robot's link is reconnecting; try again in a moment.")
        return _preview_wire(TeleopPreview((), (gap,)))


class _TeleopHandle:
    """The running loop as the API sees it: wire-shaped pairs, no livebench types."""

    def __init__(self, loop: "TeleopLoop") -> None:
        self._loop = loop
        self.rate_hz = loop.rate_hz
        self.pairs = [
            {
                "address": p.address,
                "leader_signal": p.leader_signal,
                "follower_signal": p.follower_signal,
            }
            for p in loop.pairs
        ]

    @property
    def running(self) -> bool:
        return self._loop.running

    async def stop(self, reason: str = "user") -> None:
        await self._loop.stop(reason)  # type: ignore[arg-type]


async def teleop_start(
    leader_conn: Any, follower_conn: Any, *, on_stopped: Callable[[str], object]
) -> _TeleopHandle:
    """Re-check the gate on fresh readings, hold the follower, start tracking."""
    from livebench.hardware.actuation import ActuatorUnavailableError, ActuatorWriteError
    from livebench.teleop import TeleopNotReadyError as GateFailed
    from livebench.teleop import start_teleop

    leader, follower = _actuator(leader_conn), _actuator(follower_conn)
    try:
        loop = await start_teleop(leader, follower, on_stopped=on_stopped)
    except GateFailed as exc:
        raise TeleopNotReadyError(_preview_wire(exc.preview)) from None
    except (ActuatorUnavailableError, ActuatorWriteError, OSError) as exc:
        # Hold may have torqued some joints before the bus failed: say so, never imply limp.
        raise ActuatorWriteError(
            f"Teleoperation could not start ({exc}); the follower may be holding some joints."
        ) from exc
    return _TeleopHandle(loop)


def robot_release(conn: Any) -> None:
    """Torque off on the robot's calibrated joints. BLOCKING."""
    _actuator(conn).release()


# ── SOL setpoint (SOLUSDEV-319, ADR-014 amendment 2026-10-31) ───────────────────


def _setpoint_read(conn: Any, joint: str, target: float) -> "SetpointPreview":
    """Fresh refusal checks + clamp on the robot's bus, with livebench errors translated into
    the API's (the legal dependency direction, as for teleop). BLOCKING."""
    from solus_api.livebench.setpoint import SetpointNotFoundError, SetpointRefusedError

    from livebench.setpoint import JointNotFoundError, SetpointRefusalError, preview

    actuator = _actuator(conn)
    try:
        return preview(actuator, joint, target)
    except SetpointRefusalError as exc:
        raise SetpointRefusedError(exc.code, unit=exc.unit) from None
    except JointNotFoundError:
        raise SetpointNotFoundError("joint") from None


def setpoint_preview(conn: Any, joint: str, target: float) -> dict[str, Any]:
    """The joint's present value and the clamped target, wire-shaped. BLOCKING."""
    from livebench.setpoint import DEFAULT_MAX_STEP_TICKS

    result = _setpoint_read(conn, joint, target)
    return {
        "address": result.address,
        "joint": result.signal,
        "unit": result.unit,
        "current": result.current_value,
        "target": result.target_value,
        "requested": result.requested,
        "clamped": result.clamped,
        "goal_ticks": result.goal_ticks,
        "max_step_ticks": DEFAULT_MAX_STEP_TICKS,
        "max_step": result.max_step_value,
    }


class _SetpointHandle:
    """One running move as the API sees it: no livebench types cross."""

    def __init__(self, move: "SetpointMove", result: "SetpointPreview") -> None:
        self._move = move
        self.goal_ticks = result.goal_ticks
        self.target = result.target_value
        self.unit = result.unit
        self.clamped = result.clamped

    @property
    def state(self) -> str:
        return self._move.state

    @property
    def reason(self) -> str | None:
        return self._move.reason

    async def stop(self, reason: str = "user") -> None:
        await self._move.stop(reason)


async def setpoint_apply(
    conn: Any,
    joint: str,
    target: float,
    *,
    on_ended: Callable[[str], object],
    guard: Callable[[], str | None] | None = None,
    rate_hz: float | None = None,
) -> _SetpointHandle:
    """Re-check every bus refusal on fresh readings, then start ONE bounded move."""
    from livebench.setpoint import DEFAULT_RATE_HZ, SetpointMove

    result = await asyncio.to_thread(_setpoint_read, conn, joint, target)
    move = SetpointMove(
        _actuator(conn),
        result.address,
        result.goal_ticks,
        result.span,
        rate_hz=rate_hz or DEFAULT_RATE_HZ,
        guard=guard,
        on_ended=on_ended,
    )
    move.start()
    return _SetpointHandle(move, result)


def setpoint_status(handle: _SetpointHandle) -> dict[str, Any]:
    return {"state": handle.state, "reason": handle.reason}


async def setpoint_stop(handle: _SetpointHandle, reason: str = "user") -> None:
    """End the move; the joint holds its last goal with torque on."""
    await handle.stop(reason)
