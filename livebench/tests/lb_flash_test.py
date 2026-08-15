"""LB-03: flash orchestration — progress, result, and the mid-flash danger state."""

from pathlib import Path

import pytest
from livebench.deploy.flash import (
    ArduinoCliRunner,
    FlashError,
    FlashPhase,
    flash,
)


class ScriptedRunner:
    """A runner that succeeds or fails at a scripted phase."""

    def __init__(self, fail_at: FlashPhase | None = None) -> None:
        self.fail_at = fail_at
        self.ran: list[FlashPhase] = []

    async def run(self, phase: FlashPhase, target: str, artifact: Path) -> None:
        self.ran.append(phase)
        if phase == self.fail_at:
            raise FlashError(f"scripted failure in {phase}")


def make_artifact(tmp_path: Path) -> Path:
    artifact = tmp_path / "firmware.bin"
    artifact.write_bytes(b"\x00" * 1024)
    return artifact


async def test_successful_flash_reports_phases_and_result(tmp_path: Path) -> None:
    runner = ScriptedRunner()
    seen: list[tuple[FlashPhase, float]] = []

    result = await flash(
        "serial:/dev/ttyACM0",
        make_artifact(tmp_path),
        runner=runner,
        on_progress=lambda phase, fraction: seen.append((phase, fraction)),
    )

    assert result.ok is True
    assert result.device_state == "flashed"
    assert result.error is None
    assert [p for p, _ in seen][0] == FlashPhase.PREPARING
    assert seen[-1] == (FlashPhase.DONE, 1.0)
    assert runner.ran == [FlashPhase.ERASING, FlashPhase.WRITING, FlashPhase.VERIFYING]


async def test_failure_before_writing_leaves_device_unchanged(tmp_path: Path) -> None:
    runner = ScriptedRunner(fail_at=FlashPhase.ERASING)

    result = await flash("t", make_artifact(tmp_path), runner=runner)

    assert result.ok is False
    assert result.device_state == "unchanged"
    assert result.error is not None and "erasing" in result.error


async def test_mid_write_failure_is_the_loud_unknown_state(tmp_path: Path) -> None:
    # A half-flashed device is the dangerous state: it must be UNKNOWN, never
    # "unchanged", and the result must say so plainly.
    runner = ScriptedRunner(fail_at=FlashPhase.WRITING)

    result = await flash("t", make_artifact(tmp_path), runner=runner)

    assert result.ok is False
    assert result.device_state == "unknown"
    assert result.error is not None and "writing" in result.error


async def test_verify_failure_is_also_unknown(tmp_path: Path) -> None:
    runner = ScriptedRunner(fail_at=FlashPhase.VERIFYING)
    result = await flash("t", make_artifact(tmp_path), runner=runner)
    assert result.device_state == "unknown"


async def test_missing_artifact_fails_before_touching_the_device(tmp_path: Path) -> None:
    runner = ScriptedRunner()

    result = await flash("t", tmp_path / "nope.bin", runner=runner)

    assert result.ok is False
    assert result.device_state == "unchanged"
    assert runner.ran == []


async def test_oversized_artifact_is_rejected(tmp_path: Path) -> None:
    from livebench.deploy.flash import MAX_ARTIFACT_BYTES

    artifact = tmp_path / "huge.bin"
    artifact.write_bytes(b"\x00" * (MAX_ARTIFACT_BYTES + 1))
    runner = ScriptedRunner()

    result = await flash("t", artifact, runner=runner)

    assert result.ok is False
    assert runner.ran == []


def test_arduino_cli_runner_builds_pinned_arg_lists(tmp_path: Path) -> None:
    artifact = make_artifact(tmp_path)
    runner = ArduinoCliRunner(
        binary="/usr/local/bin/arduino-cli", fqbn="esp32:esp32:esp32s3", port="/dev/ttyACM0"
    )

    argv = runner.upload_argv(artifact)

    assert argv[0] == "/usr/local/bin/arduino-cli"
    assert "--fqbn" in argv and "esp32:esp32:esp32s3" in argv
    assert "-p" in argv and "/dev/ttyACM0" in argv
    assert str(artifact) in " ".join(argv)


def test_arduino_cli_runner_requires_the_binary() -> None:
    with pytest.raises(FlashError, match="not found"):
        ArduinoCliRunner(binary=None, fqbn="x:y:z", port="/dev/ttyACM0")


class TestFlashGate:
    """Security (§7): flashing is destructive; a refused gate never touches the device."""

    async def test_refusal_returns_before_the_runner_runs(self, tmp_path: Path) -> None:
        from livebench.recognition.active import MotionPlan  # noqa: F401 - shape parity check

        runner = ScriptedRunner()

        async def refuse(event: object) -> bool:
            return False

        result = await flash("t", make_artifact(tmp_path), runner=runner, approval=refuse)

        assert runner.ran == []  # device untouched
        assert result.ok is False
        assert result.device_state == "unchanged"
        assert result.error is not None and "refused" in result.error

    async def test_approval_shows_the_concrete_action_then_flashes(self, tmp_path: Path) -> None:
        from solus_api.contracts.action_gate import ToolConfirmationEvent

        runner = ScriptedRunner()
        seen: list[ToolConfirmationEvent] = []

        async def approve(event: ToolConfirmationEvent) -> bool:
            seen.append(event)
            return True

        result = await flash("robot-a", make_artifact(tmp_path), runner=runner, approval=approve)

        assert len(seen) == 1
        assert "robot-a" in seen[0].summary
        # sha256 is real (computed from the artifact), shown before the write.
        assert any(row.label == "sha256" for row in seen[0].preview)
        assert result.ok is True
        assert runner.ran == [FlashPhase.ERASING, FlashPhase.WRITING, FlashPhase.VERIFYING]
