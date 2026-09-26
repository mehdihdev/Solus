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
            "--verify",
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
        await run_cli(self.upload_argv(artifact))


async def run_cli(argv: list[str], *, timeout: float = 120, output_limit: int = 65536) -> bytes:
    """Supervise a pinned tool with bounded output and cleanup on every exit path."""
    if not argv or not Path(argv[0]).is_absolute():
        raise FlashError("compiler binary must be an absolute pinned path")
    if timeout <= 0 or output_limit <= 0:
        raise ValueError("positive supervision limits required")
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    try:
        async with asyncio.timeout(timeout):
            assert process.stdout is not None
            while chunk := await process.stdout.read(4096):
                if len(output) + len(chunk) > output_limit:
                    raise FlashError("arduino-cli exceeded output limit")
                output.extend(chunk)
            await process.wait()
        if process.returncode != 0:
            # Tool output can contain local paths or project source: never echo it into errors.
            raise FlashError(f"arduino-cli exited {process.returncode}")
        return bytes(output)
    except TimeoutError as exc:
        raise FlashError("arduino-cli timed out; device state may be unknown") from exc
    finally:
        # The compiler launches children; terminate the private process group as well.
        import os
        import signal

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
