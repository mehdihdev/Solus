"""RBT-02: firmware idiom extraction — provenance-exact, medium confidence, no hardware."""

import os
from pathlib import Path

import pytest
from livebench.recognition.firmware import FirmwareFinding, extract_firmware_findings
from solus_api.fingerprint.contract import MatchState, Modality

ARDUINO_SKETCH = """\
#include <Servo.h>

#define WRIST_PIN 5
const int basePin = 3;
const float MOTOR_KV = 920.0;

Servo servo_elbow;
Servo gripper;

void setup() {
  servo_elbow.attach(9);
  gripper.attach(WRIST_PIN);  // symbolic arg: the attach is recorded without a pin number
}
"""

MICROPYTHON = """\
from machine import Pin, PWM

ELBOW_PIN = 7
servo_wrist = PWM(Pin(12))
lift_motor = Servo(Pin(4))
"""


def write_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "arm.ino").write_text(ARDUINO_SKETCH)
    (tmp_path / "src" / "boot.py").write_text(MICROPYTHON)
    (tmp_path / "README.md").write_text("# not firmware")
    return tmp_path


class TestExtraction:
    def test_attach_calls_with_numeric_pins_and_provenance(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))

        attach = [f for f in findings if f.kind == "attach_call" and f.pin is not None]
        elbow = next(f for f in attach if f.name == "servo_elbow")
        assert elbow.pin == 9
        assert elbow.file.endswith("src/arm.ino")
        assert elbow.line == 11
        assert elbow.language == "cpp"
        assert elbow.name_hint == "elbow"

    def test_symbolic_attach_recorded_without_a_guessed_pin(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))

        gripper = next(f for f in findings if f.name == "gripper" and f.kind == "attach_call")
        assert gripper.pin is None  # WRIST_PIN is a symbol; resolving it is not guessing

    def test_pin_constants_from_both_languages(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))
        constants = {f.name: f.pin for f in findings if f.kind == "pin_constant"}

        assert constants["WRIST_PIN"] == 5
        assert constants["basePin"] == 3
        assert constants["ELBOW_PIN"] == 7

    def test_micropython_pwm_and_servo_attachments(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))
        attach = {f.name: f.pin for f in findings if f.kind == "attach_call"}

        assert attach["servo_wrist"] == 12
        assert attach["lift_motor"] == 4

    def test_motor_constants_are_captured(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))

        kv = next(f for f in findings if f.name == "MOTOR_KV")
        assert kv.kind == "motor_constant"
        assert kv.value == 920.0

    def test_evidence_is_firmware_symbol_at_medium_confidence(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))

        for finding in findings:
            match = finding.evidence
            assert match.modality is Modality.FIRMWARE_SYMBOL
            assert match.state is MatchState.LOW_CONFIDENCE
            assert match.confidence == 0.55
            assert "line" in match.evidence
            assert "code intent" in match.evidence["note"]

    def test_repo_with_no_firmware_returns_empty_not_error(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# docs only")
        assert extract_firmware_findings(tmp_path) == []

    def test_malformed_cpp_is_skipped_never_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "broken.cpp").write_text("void { {{{ ??? ")
        (tmp_path / "ok.ino").write_text("Servo s;\nvoid setup() { s.attach(2); }\n")

        findings = extract_firmware_findings(tmp_path)

        assert [f.pin for f in findings if f.kind == "attach_call"] == [2]

    def test_oversized_files_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "huge.cpp").write_text("// " + "x" * 3_000_000)
        assert extract_firmware_findings(tmp_path) == []


class TestTenancyBoundary:
    """RBT-02's hard line: the IDIOM is tool knowledge; the INSTANCE is customer content.

    The emission half is deferred until LANE 0 amends CTR-05 (ToolFamily has no firmware
    value today) — these tests prove the boundary is structurally closed meanwhile.
    """

    def test_ctr05_cannot_name_a_firmware_tool_family_today(self) -> None:
        from solus_api.contracts.tool_knowledge import ToolFamily

        with pytest.raises(ValueError):
            ToolFamily("arduino_servo_library")
        assert all("firmware" not in member.value for member in ToolFamily)

    def test_this_module_has_no_path_to_the_knowledge_store(self) -> None:
        # No import, no emission API: an instance-level fact (pin 9 → elbow) cannot
        # leave this module as a pattern, because no code path exists to carry it.
        import livebench.recognition.firmware as firmware_module

        source = Path(firmware_module.__file__).read_text()
        imports = [
            line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
        ]
        assert not any("tool_knowledge" in line for line in imports), (
            "the firmware extractor must never import the knowledge-store boundary"
        )

    def test_findings_are_instance_shaped_not_pattern_shaped(self, tmp_path: Path) -> None:
        findings = extract_firmware_findings(write_repo(tmp_path))

        # Every finding names a concrete file in a concrete repo — customer content
        # by construction, which is exactly what CTR-05's vendor-text rules reject.
        assert all(isinstance(f, FirmwareFinding) and f.file for f in findings)


class TestPathTraversal:
    """Security (both reviews, CRITICAL): a connector-supplied checkout is untrusted;
    a symlink must never read a file outside the scanned root."""

    def test_symlinked_file_pointing_outside_root_is_not_read(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret_outside.cpp"
        secret.write_text("const int AWS_SECRET_PIN = 133742;\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "real.ino").write_text("Servo s;\nvoid setup() { s.attach(2); }\n")
        os.symlink(secret, repo / "looks_like_firmware.cpp")

        findings = extract_firmware_findings(repo)

        assert all("AWS_SECRET_PIN" != f.name for f in findings)
        assert [f.pin for f in findings if f.kind == "attach_call"] == [2]

    def test_symlinked_directory_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.cpp").write_text("const int LEAK_PIN = 999;\n")
        repo = tmp_path / "repo2"
        repo.mkdir()
        os.symlink(outside, repo / "linked")

        findings = extract_firmware_findings(repo)

        assert findings == []

