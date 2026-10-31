"""SOLUSDEV-321 P2-T4 — the dev-only `replay` bench provider, API half (docs/api/bench-runs.md).

A replay session plays a recorded capture as one of the project's robots, so the Live Bench pane
and the window evaluator can be driven with no hardware. This module holds the authority — which
file may be read, which robot it plays as, what the runner is handed — and
`livebench.local.open_replay`, reached through the optional runner like every provider, holds the
transport. Nothing here opens a device, reads the file's text or runs a model.
"""

from __future__ import annotations

import stat
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    FieldProvenance,
    HardwareConfig,
    ProtocolBinding,
    ProvenanceRecord,
)
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import robot_root

if TYPE_CHECKING:
    from solus_api.livebench.bench_router import ReplayRealConfig

#: A recording is hex frames of JSON lines; a minute of a six-servo arm is about 4 MiB.
MAX_RECORDING_BYTES: Final = 32 * 1024 * 1024
_MIB: Final = 1024 * 1024


def _regular_size(path: Path) -> int | None:
    """The size of a regular file; None for anything else: a missing path, a directory, a pipe
    (which would block a read), a name too long to stat."""
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


def confined_file(
    root: str | Path,
    raw: str,
    *,
    field: str,
    root_name: str,
    suffix: str,
    max_bytes: int | None = None,
) -> Path:
    """`raw` (relative to `root`, or absolute) as the regular `suffix` file it names inside `root`.

    Resolved with symlinks followed, then required to lie inside the resolved root, so neither
    `..` nor a link can leave it. Anything else is a 422 naming `field`, never the path: an
    escape, another suffix, no such regular file, a file over `max_bytes`, a path that cannot be
    resolved at all (an embedded NUL, a symlink loop). One confinement for the MCAP and the
    replay providers."""
    try:
        root_path = Path(root).resolve()
        candidate = Path(raw)
        resolved = (candidate if candidate.is_absolute() else root_path / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        raise APIError(422, "validation_error", f"{field} is not a usable path") from None
    if not resolved.is_relative_to(root_path):
        raise APIError(422, "validation_error", f"{field} escapes the {root_name}")
    if resolved.suffix != suffix:
        raise APIError(422, "validation_error", f"{field} must name a {suffix} file")
    size = _regular_size(resolved)
    if size is None:
        raise APIError(422, "validation_error", f"{field} does not exist")
    if max_bytes is not None and size > max_bytes:
        raise APIError(422, "validation_error", f"{field} is larger than {max_bytes // _MIB} MiB")
    return resolved


def _decoded_with(config: HardwareConfig, driver_id: str) -> dict[str, Any]:
    """The robot's config with `driver_id` (its default parameters) in place of its own protocol."""
    document = config.model_dump(mode="json")
    document["protocol"] = ProtocolBinding(driver_id=driver_id).model_dump(mode="json")
    user = ProvenanceRecord(by=FieldProvenance.USER).model_dump(mode="json")
    document["provenance"] = {**document["provenance"], "protocol": user}
    return HardwareConfig.model_validate(document).model_dump(mode="json")


async def replay_session(
    local: Any,
    session: AsyncSession,
    project_id: uuid.UUID,
    cfg: ReplayRealConfig,
    settings: Any,
) -> tuple[Callable[[], Awaitable[Any]], str, dict[str, Any], uuid.UUID]:
    """(open_conn, label, device, robot id) for a replay session.

    Refused in this order, so the answer to a body never depends on what a later check would
    have said: no replay root configured (503, for every body), a robot that is not a live
    Physical Robot of THIS project (404, another team's included), a recording that is not a
    file confined under the root (422), a robot whose config names no transport identity yet
    (422). The runner then checks the capture was recorded from that identity. The label and
    the device name the file, never its place on the server, and the device has no
    `serial_number`, `device_path` or `baud` field (`device_ref` is `usb:<serial>`, but the
    desktop matches a session to a physical device by those): a replay is not taken for the
    device it was recorded from."""
    root = settings.bench_replay_root
    if root is None:
        raise APIError(
            503,
            "source_unavailable",
            "Replay is not configured on this server (bench_replay_root unset)",
        )
    robot = await robot_root(session, project_id, cfg.robot_entity_id)
    path = confined_file(
        root,
        cfg.recording,
        field="recording",
        root_name="bench replay root",
        suffix=".json",
        max_bytes=MAX_RECORDING_BYTES,
    )
    config = await resolve_runtime_config(session, project_id, robot.id)
    if config.identity is None:
        raise APIError(
            422,
            "validation_error",
            "the robot's config has no transport identity yet — detect it or configure it "
            "before replaying a capture as it",
        )
    payload = {
        "document": _decoded_with(config, cfg.driver_id),
        "recording": str(path),
        "max_bytes": MAX_RECORDING_BYTES,
        "realtime": cfg.realtime,
    }

    async def open_replay() -> Any:
        return await local.open_replay(payload, project_id=project_id)

    device = {"device_ref": config.identity.device_ref, "driver_id": cfg.driver_id, "replay": True}
    return open_replay, f"Replay {path.name} as {robot.name}", device, robot.id
