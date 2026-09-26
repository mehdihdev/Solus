"""Reviewed input wiring compiles to readings only; never to control commands."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from livebench.plugins.arduino import presence


@pytest.mark.parametrize("profile,last", [("uno_avr", "A5"), ("nano_avr", "A7")])
def test_topology_source_reads_only_reviewed_inputs(profile: str, last: str) -> None:
    source = presence.generate_source(
        profile_id=profile,
        device_id="usb:test",
        channel="board.alive",
        kind="topology",
        wiring=[
            {"channel": "sensor.raw", "pin": last, "kind": "analog_input"},
            {"channel": "switch.state", "pin": "D2", "kind": "digital_input"},
        ],
    )
    assert f"analogRead({last})" in source
    assert "digitalRead(2)" in source and "pinMode(2, INPUT)" in source
    assert '"sensor.raw"' in source and '"switch.state"' in source
    assert '"board.alive"' in source and '"count"' in source
    assert "Serial.read() == '?'" in source and "n < 16" in source
    assert "digitalWrite" not in source and "analogWrite" not in source
    assert "OUTPUT" not in source and "INPUT_PULLUP" not in source
    assert "Wire." not in source
    if last == "A7":
        assert "pinMode(A7" not in source


def test_empty_reviewed_topology_is_heartbeat_only() -> None:
    source = presence.generate_source(
        profile_id="uno_avr", device_id="usb:test", channel="board.alive", kind="topology"
    )
    assert '"board.alive"' in source and "analogRead" not in source and "digitalRead" not in source


@pytest.mark.parametrize(
    "wiring",
    [
        [{"channel": "board.alive", "pin": "A0", "kind": "analog_input"}],
        [{"channel": 'x";evil()', "pin": "A0", "kind": "analog_input"}],
        [{"channel": "x", "pin": "A0);evil()", "kind": "analog_input"}],
        [{"channel": "x", "pin": "A6", "kind": "analog_input"}],
        [{"channel": "x", "pin": "D0", "kind": "digital_input"}],
        [{"channel": "x", "pin": "D1", "kind": "digital_input"}],
        [{"channel": "x", "pin": "D14", "kind": "digital_input"}],
        [{"channel": "x", "pin": "A0", "kind": "digital_input"}],
        [{"channel": "x", "pin": "D2", "kind": "output"}],
        [{"channel": "x", "pin": "A0", "kind": "analog_input", "extra": "no"}],
        [
            {"channel": "x", "pin": "A0", "kind": "analog_input"},
            {"channel": "y", "pin": "A0", "kind": "analog_input"},
        ],
        [
            {"channel": "x", "pin": "A0", "kind": "analog_input"},
            {"channel": "x", "pin": "A1", "kind": "analog_input"},
        ],
        [{"channel": "x", "pin": "D2", "kind": "digital_input"}] * 17,
    ],
)
def test_rejects_unreviewable_pin_or_channel(wiring: list[dict[str, str]]) -> None:
    with pytest.raises(ValueError):
        presence.generate_source(
            profile_id="uno_avr",
            device_id="usb:test",
            channel="board.alive",
            kind="topology",
            wiring=wiring,
        )


@pytest.mark.parametrize("kind", ["heartbeat", "probe"])
def test_other_sketch_kinds_do_not_silently_ignore_wiring(kind: str) -> None:
    with pytest.raises(ValueError):
        presence.generate_source(
            profile_id="uno_avr",
            device_id="usb:test",
            channel="board.alive",
            kind=kind,
            wiring=[{"channel": "x", "pin": "A0", "kind": "analog_input"}],
        )


async def test_topology_compile_keeps_exact_source_and_rejects_before_compiler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = AsyncMock()

    async def compile_fixture(argv: list[str], **kwargs: object) -> bytes:
        output = Path(argv[argv.index("--output-dir") + 1])
        source = (Path(argv[-1]) / "presence.ino").read_text()
        assert "digitalRead(13)" in source
        (output / "presence.ino.hex").write_bytes(b":firmware-fixture")
        return b"ok"

    runner.side_effect = compile_fixture
    monkeypatch.setattr(presence, "run_cli", runner)
    compiler = presence.PresenceCompiler(binary="/usr/bin/arduino-cli", library=tmp_path)
    result = await compiler.prepare(
        profile_id="nano_avr",
        device_id="usb:test",
        channel="board.alive",
        kind="topology",
        wiring=[{"channel": "button", "pin": "D13", "kind": "digital_input"}],
    )
    assert b"digitalRead(13)" in result.source and result.binary == b":firmware-fixture"
    with pytest.raises(ValueError):
        await compiler.prepare(
            profile_id="nano_avr",
            device_id="usb:test",
            channel="board.alive",
            kind="topology",
            wiring=[{"channel": "button", "pin": "D1", "kind": "digital_input"}],
        )
    assert runner.await_count == 1


def test_wiring_snapshot_is_immutable_and_supports_sixteen_reviewed_inputs() -> None:
    from livebench.plugins.arduino.wiring import validate_wiring

    rows = [
        {"channel": f"analog.{index}", "pin": f"A{index}", "kind": "analog_input"}
        for index in range(6)
    ]
    rows += [
        {"channel": f"digital.{index}", "pin": f"D{index}", "kind": "digital_input"}
        for index in range(2, 12)
    ]
    result = validate_wiring("uno_avr", "board.alive", "topology", rows)
    rows[0]["pin"] = "D0"
    assert result[0]["pin"] == "A0" and len(result) == 16
    with pytest.raises(TypeError):
        result[0]["pin"] = "D1"  # type: ignore[index]


@pytest.mark.parametrize(
    "row", [{"channel": "x", "pin": 2, "kind": "digital_input"}, {"channel": "x"}, "not a mapping"]
)
def test_wiring_boundary_rejects_nonstring_or_incomplete_values(row: object) -> None:
    from livebench.plugins.arduino.wiring import validate_wiring

    with pytest.raises(ValueError):
        validate_wiring("uno_avr", "board.alive", "topology", [row])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "profile,channel", [("unknown", "board.alive"), ("uno_avr", "bad\nchannel")]
)
def test_provider_wiring_validator_checks_profile_and_heartbeat(profile: str, channel: str) -> None:
    from livebench.plugins.arduino.wiring import validate_wiring

    with pytest.raises(ValueError):
        validate_wiring(profile, channel, "topology")


def test_topology_names_use_flash_and_one_bounded_reused_buffer() -> None:
    names = [f"s{i:02d}" + "x" * 61 for i in range(16)]
    pins = [(f"A{i}", "analog_input") for i in range(6)] + [
        (f"D{i}", "digital_input") for i in range(2, 12)
    ]
    source = presence.generate_source(
        profile_id="uno_avr",
        device_id="d" * 128,
        channel="h" * 64,
        kind="topology",
        wiring=[
            {"channel": name, "pin": pin, "kind": kind}
            for name, (pin, kind) in zip(names, pins, strict=True)
        ],
    )
    assert "#include <avr/pgmspace.h>" in source
    assert source.count("char inputChannel[65];") == 1
    for name in names:
        assert f'strcpy_P(inputChannel, PSTR("{name}"));' in source
        assert f'telemetry.add("{name}"' not in source
    assert source.count("telemetry.add(inputChannel,") == 16
    assert source.count("telemetry.send();") == 17
