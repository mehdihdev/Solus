"""`arduino-cli upload` as a `FlashRunner` (LB-03): argument lists only, binary path pinned
at construction, never shell=True (CLAUDE.md §7). Moved out of the shared flash module so the
seam names no vendor (SOLUSDEV-248)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from livebench.deploy.flash import FlashError, FlashPhase


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
