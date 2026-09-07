"""The vendor flash tool lives in its plugin: pinned argument lists, a missing binary is an
honest error, and the shared flash seam (`livebench.deploy.flash`) never names it."""

from pathlib import Path

import pytest
from livebench.deploy.flash import FlashError
from livebench.plugins.arduino.arduino_flash import ArduinoCliRunner


def test_upload_argv_is_a_pinned_argument_list() -> None:
    runner = ArduinoCliRunner(binary="/usr/bin/arduino-cli", fqbn="x:y:z", port="/dev/ttyACM0")
    assert runner.upload_argv(Path("/tmp/sketch.hex")) == [
        "/usr/bin/arduino-cli",
        "upload",
        "--fqbn",
        "x:y:z",
        "-p",
        "/dev/ttyACM0",
        "--input-file",
        "/tmp/sketch.hex",
    ]


def test_a_missing_binary_refuses_at_construction() -> None:
    with pytest.raises(FlashError):
        ArduinoCliRunner(binary=None, fqbn="x:y:z", port="/dev/ttyACM0")


def test_the_shared_flash_seam_names_no_vendor() -> None:
    import livebench.deploy.flash as flash

    assert "arduino" not in Path(flash.__file__).read_text().lower()
