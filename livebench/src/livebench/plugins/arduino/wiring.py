"""Provider-owned, immutable input pin declarations for reviewed AVR topology."""

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

_CHANNEL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ANALOG_MAX = MappingProxyType({"uno_avr": 5, "nano_avr": 7})


def validate_wiring(
    profile_id: str, channel: str, kind: str, wiring: Sequence[Mapping[str, str]] = ()
) -> tuple[Mapping[str, str], ...]:
    """Freeze validated data before any asynchronous compiler/provider boundary."""
    if profile_id not in _ANALOG_MAX or kind not in {"heartbeat", "probe", "topology"}:
        raise ValueError("unsupported presence profile or kind")
    if not isinstance(channel, str) or not _CHANNEL.fullmatch(channel):
        raise ValueError("invalid heartbeat channel")
    if not isinstance(wiring, (list, tuple)) or len(wiring) > 16:
        raise ValueError("review at most 16 input pins")
    if wiring and kind != "topology":
        raise ValueError("input wiring requires the topology sketch")
    pins: set[str] = set()
    channels = {channel}
    frozen: list[Mapping[str, str]] = []
    for row in wiring:
        if not isinstance(row, Mapping) or set(row) != {"channel", "pin", "kind"}:
            raise ValueError("input wiring requires exactly channel, pin and kind")
        if any(not isinstance(value, str) for value in row.values()):
            raise ValueError("input wiring fields must be strings")
        signal, pin, input_kind = row["channel"], row["pin"], row["kind"]
        if not _CHANNEL.fullmatch(signal) or signal in channels:
            raise ValueError("input channels must be unique and cannot replace heartbeat")
        permitted = (
            {f"A{index}" for index in range(_ANALOG_MAX[profile_id] + 1)}
            if input_kind == "analog_input"
            else {f"D{index}" for index in range(2, 14)}
            if input_kind == "digital_input"
            else set()
        )
        if pin not in permitted or pin in pins:
            raise ValueError("choose a unique supported input pin; serial pins are reserved")
        pins.add(pin)
        channels.add(signal)
        frozen.append(MappingProxyType(dict(row)))
    return tuple(frozen)


def source_for_wiring(wiring: Sequence[Mapping[str, str]]) -> tuple[str, str]:
    """Render only declarations already frozen by validate_wiring."""
    setup: list[str] = []
    # The telemetry library retains name pointers until send(); reuse only afterwards.
    readings: list[str] = ["  char inputChannel[65];\n"] if wiring else []
    for row in wiring:
        analog = row["kind"] == "analog_input"
        pin = row["pin"] if analog else row["pin"][1:]
        if analog and pin in {"A6", "A7"}:
            setup.append(f"  // {pin} is ADC-only; no digital pin configuration.\n")
        else:
            setup.append(f"  pinMode({pin}, INPUT);\n")
        reader = "analogRead" if analog else "digitalRead"
        readings.append(
            f'  strcpy_P(inputChannel, PSTR("{row["channel"]}"));\n'
            f'  telemetry.add(inputChannel, {reader}({pin}), "count");\n  telemetry.send();\n'
        )
    return "".join(setup), "".join(readings)
