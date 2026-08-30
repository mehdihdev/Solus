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
import importlib.util
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from solus_api.livebench.sessions import AmbiguousDeviceError, DeviceNotFoundError

from livebench.recognition.passive import PortIdentity, enumerate_usb_serial
from livebench.telemetry.stream_live import PacketStreamLiveConnection

__all__ = [
    "AmbiguousDeviceError",
    "DeviceNotFoundError",
    "available_simulators",
    "list_devices",
    "resolve_serial_device",
    "open_mujoco",
    "open_gazebo",
    "open_mcap",
    "open_serial",
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

    A device is ambiguous when its serial is absent or shared with another
    device — exactly the cases where binding by serial cannot discriminate and
    the UI must make the user pick explicitly.
    """
    found = enumerate_usb_serial() if identities is None else identities
    by_id = _by_id_map(by_id_dir)
    serial_counts: dict[str, int] = {}
    for identity in found:
        if identity.serial is not None:
            serial_counts[identity.serial] = serial_counts.get(identity.serial, 0) + 1
    return [
        LocalDevice(
            identity=identity,
            by_id_path=by_id.get(identity.device),
            ambiguous=identity.serial is None or serial_counts[identity.serial] > 1,
        )
        for identity in found
    ]


def resolve_serial_device(
    serial_number: str | None,
    *,
    identities: list[PortIdentity] | None = None,
    by_id_dir: Path = Path("/dev/serial/by-id"),
    confirmed_device_path: str | None = None,
) -> str:
    """The path to OPEN for one physical device, bound by USB serial.

    Prefers the `/dev/serial/by-id` alias (stable across re-enumeration, and it
    embeds the serial — reopening it re-verifies identity by construction).
    Refuses rather than guesses: unknown serial, duplicated serial, or a
    serial-less device without an explicit confirmed pick all raise.
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
    matches = [d for d in devices if d.identity.serial == serial_number]
    if not matches:
        raise DeviceNotFoundError(f"no device with serial {serial_number!r}")
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
) -> PacketStreamLiveConnection:
    """A serial robot connection bound by USB serial (see `resolve_serial_device`).
    The blocking pyserial open runs off-loop."""
    from livebench.telemetry.robot import SerialRobotConnection

    def _open() -> PacketStreamLiveConnection:
        # Enumeration + the pyserial open both block — resolve AND open off-loop.
        device = resolve_serial_device(serial_number, confirmed_device_path=confirmed_device_path)
        return SerialRobotConnection.open(device, baud, project_id=project_id)

    return await asyncio.to_thread(_open)
