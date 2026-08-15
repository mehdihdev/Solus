"""Flashing (LB-03): `flash(target, artifact)` with progress and an HONEST result.

The dangerous state is the half-flashed device. The result therefore carries a
tri-state `device_state`:

* `unchanged` — the failure happened before anything touched flash memory;
* `flashed` — write + verify completed;
* `unknown` — the failure happened during writing or verification. The device may
  be half-programmed and must be treated as unbootable until re-flashed. This is
  reported loudly, never folded into a generic error.

The tool seam is a `FlashRunner`: `ArduinoCliRunner` builds pinned argument lists
for `arduino-cli upload` (CLAUDE.md §7: argument lists only, binary path pinned at
construction, never shell=True); tests drive the orchestration with scripted
runners, and a real flash happens only against hardware a human has sanctioned.
"""

import asyncio
import enum
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from solus_api.contracts.action_gate import DiffRow, ToolConfirmationEvent

logger = logging.getLogger(__name__)

#: The gate seam (mirrors RBT-04's active id): answers the confirmation, returns
#: approved?. On this branch the real surface is unmerged (SOLUSDEV-60) — callers
#: plug it in here, tests plug fakes. A denied gate NEVER reaches the device.
Approval = Callable[[ToolConfirmationEvent], Awaitable[bool]]

#: MCU firmware is KBs to a few MBs; anything larger is the wrong artifact.
MAX_ARTIFACT_BYTES: Final = 32 * 1024 * 1024


class FlashError(RuntimeError):
    """A flashing step failed. The orchestrator maps WHERE it failed to the state."""


class FlashPhase(enum.StrEnum):
    PREPARING = "preparing"
    ERASING = "erasing"
    WRITING = "writing"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"


#: Called with (phase, fraction 0..1) as the flash advances.
ProgressCallback = Callable[[FlashPhase, float], None]

#: Phases the runner executes on the device, in order, with their completion fraction.
_DEVICE_PHASES: Final = (
    (FlashPhase.ERASING, 0.3),
    (FlashPhase.WRITING, 0.8),
    (FlashPhase.VERIFYING, 0.95),
)


class FlashRunner(Protocol):
    """The tool adapter: performs one device phase for one target."""

    async def run(self, phase: FlashPhase, target: str, artifact: Path) -> None: ...


@dataclass(frozen=True)
class FlashResult:
    ok: bool
    device_state: Literal["unchanged", "flashed", "unknown"]
    artifact_sha256: str | None
    error: str | None


def propose_flash(
    target: str, artifact: Path, *, artifact_sha256: str, size: int
) -> ToolConfirmationEvent:
    """The gate payload: the concrete destructive action, shown before any write (§7)."""
    return ToolConfirmationEvent(
        confirmation_id=uuid.uuid4().hex,
        tool="flash_device",
        args={"target": target, "artifact": str(artifact), "sha256": artifact_sha256, "size": size},
        summary=f"Flash {size}-byte firmware onto {target}",
        preview=[
            DiffRow(label="target device", before=None, after=target),
            DiffRow(label="artifact", before=None, after=artifact.name),
            DiffRow(label="sha256", before=None, after=artifact_sha256[:16]),
        ],
    )


async def flash(
    target: str,
    artifact: Path,
    *,
    runner: FlashRunner,
    on_progress: ProgressCallback | None = None,
    approval: Approval | None = None,
) -> FlashResult:
    """Flash `artifact` onto `target` with progress; never raises on flash failure.

    Flashing is destructive real-world action, so when `approval` is supplied the
    gate is consulted AFTER the artifact is read/hashed (so the confirmation shows
    the real sha256/size) and BEFORE the first device phase — a refusal returns
    `refused` with the device untouched. `approval=None` is the un-gated test/dev
    path; a route MUST pass a real approval seam."""

    def report(phase: FlashPhase, fraction: float) -> None:
        if on_progress is not None:
            on_progress(phase, fraction)

    report(FlashPhase.PREPARING, 0.0)
    try:
        data = artifact.read_bytes()
    except OSError as exc:
        report(FlashPhase.FAILED, 0.0)
        return FlashResult(False, "unchanged", None, f"artifact unreadable: {exc}")
    if len(data) > MAX_ARTIFACT_BYTES:
        report(FlashPhase.FAILED, 0.0)
        return FlashResult(False, "unchanged", None, "artifact exceeds the size cap")
    digest = hashlib.sha256(data).hexdigest()

    if approval is not None:
        event = propose_flash(target, artifact, artifact_sha256=digest, size=len(data))
        if not await approval(event):
            report(FlashPhase.FAILED, 0.0)
            return FlashResult(False, "unchanged", digest, "flash refused at the confirmation gate")

    for phase, fraction in _DEVICE_PHASES:
        report(phase, fraction)
        try:
            await runner.run(phase, target, artifact)
        except FlashError as exc:
            # Erase failure precedes any write → device unchanged; a failure in
            # writing or verification leaves flash memory in an UNKNOWN state.
            state: Literal["unchanged", "unknown"] = (
                "unchanged" if phase is FlashPhase.ERASING else "unknown"
            )
            logger.error("flash of %s failed during %s; device state %s", target, phase, state)
            report(FlashPhase.FAILED, fraction)
            return FlashResult(False, state, digest, f"failed during {phase}: {exc}")
    report(FlashPhase.DONE, 1.0)
    return FlashResult(True, "flashed", digest, None)


class ArduinoCliRunner:
    """`arduino-cli upload` as the flash tool, argument lists only, binary pinned."""

    def __init__(self, *, binary: str | None, fqbn: str, port: str) -> None:
        if not binary:
            raise FlashError("arduino-cli not found — install it (user-space) to flash")
        self._binary = binary
        self._fqbn = fqbn
        self._port = port

    def upload_argv(self, artifact: Path) -> list[str]:
        return [
            self._binary,
            "upload",
            "--fqbn",
            self._fqbn,
            "-p",
            self._port,
            "--input-file",
            str(artifact),
        ]

    async def run(self, phase: FlashPhase, target: str, artifact: Path) -> None:
        # arduino-cli performs erase+write+verify in one invocation; run it once
        # at the WRITING phase and treat the other phases as no-ops.
        if phase is not FlashPhase.WRITING:
            return
        process = await asyncio.create_subprocess_exec(
            *self.upload_argv(artifact),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        if process.returncode != 0:
            raise FlashError(
                f"arduino-cli exited {process.returncode}: {output[-500:].decode(errors='replace')}"
            )
