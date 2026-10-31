"""SOLUSDEV-321 P2-T4 — writes `serial_fake_arm_stall.json`: a fake arm's stall as a recording.

One synthetic six-servo arm, no vendor and no product: every name and number is made up. It
streams one LB-06 JSON line per tick at 20 Hz for 60 s, five channels a servo
(`servoN.position|commanded_position|current|temperature|voltage`, the channels
`packages/api/tests/fixtures/fake_arm.py` configures), `device_id` the transport's own
`usb:FAKE-ARM-0001`, `ts_us` the event time from the fixed epoch 2026-10-25T00:00:00Z. There is no
randomness and no libm: the same run writes the same bytes (a test regenerates and compares).

    python make_fake_arm_stall.py [out_dir]        # default: beside this file

The minute (event time; limits are the fake arm's: rating 2.0 A, nominal 1.0 A, 70 degC, 7.4 V):

    5.0 s  servo 3 stalls: its command steps 45 deg away, its position holds, its current rises
           to 1.7 A and, a second on, peaks at 2.8 A (over the rating) before it settles at 2.4 A
    6.0 s  that peak sags the shared rail: every servo's voltage dips with it
   10.0 s  the firmware's stall timeout: servo 3's command comes back, its current drops
   10-35 s servo 3's temperature runs away toward the 70 degC limit, accelerating, never past it
   30.0 s  servo 5's position sensor freezes while its command, a slow sweep, goes on moving
   40.0 s  servo 2 stalls the way servo 3 did
"""

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

BINDING: Final = "FAKE-ARM-0001"
DEVICE_ID: Final = f"usb:{BINDING}"
FILE_NAME: Final = "serial_fake_arm_stall.json"
EPOCH_US: Final = int(datetime(2026, 10, 25, tzinfo=UTC).timestamp()) * 1_000_000
HZ: Final = 20
SECONDS: Final = 60
TICK_US: Final = 1_000_000 // HZ
SERVOS: Final = (1, 2, 3, 4, 5, 6)
CHANNELS: Final = (
    ("position", "deg"),
    ("commanded_position", "deg"),
    ("current", "A"),
    ("temperature", "degC"),
    ("voltage", "V"),
)

#: Parked positions, in degrees: servo n rests at 10 n.
REST_DEG: Final = {servo: 10.0 * servo for servo in SERVOS}
IDLE_A: Final = 0.5
IDLE_C: Final = 36.0
RAIL_V: Final = 7.4

#: A stall: the command steps this far from where the servo is parked and the position holds.
STALL_STEP_DEG: Final = 45.0
#: Its current: pushing at PUSH_A for PUSH_SECONDS, then a PEAK_A spike that settles to HOLD_A over
#: DECAY_SECONDS. The push is over the warn bound (1.6 A) and under the rating (2.0 A), so a stall
#: is judged a whole second before the current is over the rating.
PUSH_A: Final = 1.7
PUSH_SECONDS: Final = 1.0
PEAK_A: Final = 2.8
HOLD_A: Final = 2.4
DECAY_SECONDS: Final = 0.5
#: The shared rail holds up to RAIL_CAP_A of total load; past it each amp costs SAG_OHMS volts.
RAIL_CAP_A: Final = 4.5
SAG_OHMS: Final = 0.4

HOT_SERVO: Final = 3
HEAT_START: Final = 10.0
HEAT_END: Final = 35.0
HEAT_RISE_C: Final = 32.0  # 36 degC to 68 degC: toward the 70 degC limit, never past it

SWEEP_SERVO: Final = 5
SWEEP_SPAN_DEG: Final = 10.0
SWEEP_PERIOD_SECONDS: Final = 24.0
SWEEP_LAG_SECONDS: Final = 0.1
FREEZE_AT: Final = 30.0

#: Dither, per channel: what a real reading wobbles by. A stalled shaft rocks a few hundredths of
#: a degree, which is also what keeps a held position from being a frozen one.
POSITION_NOISE_DEG: Final = 0.04
CURRENT_NOISE_A: Final = 0.02
TEMPERATURE_NOISE_C: Final = 0.03
VOLTAGE_NOISE_V: Final = 0.01


@dataclass(frozen=True)
class Stall:
    servo: int
    start: float
    end: float

    def covers(self, servo: int, seconds: float) -> bool:
        return self.servo == servo and self.start <= seconds < self.end


STALLS: Final = (Stall(3, 5.0, 10.0), Stall(2, 40.0, 45.0))


def dither(tick: int, servo: int, channel: int) -> float:
    """Repeatable noise in [-1, 1]: an integer hash of (tick, servo, channel), never a draw."""
    x = (tick * 0x9E3779B1 + servo * 0x85EBCA6B + channel * 0xC2B2AE35) & 0xFFFFFFFF
    x = ((x ^ (x >> 15)) * 0x2C1B3C6D) & 0xFFFFFFFF
    x = ((x ^ (x >> 12)) * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return x / 0xFFFFFFFF * 2.0 - 1.0


def triangle(cycles: float) -> float:
    """A triangle wave in [-1, 1] with period 1, rising from -1 at zero."""
    phase = cycles % 1.0
    return 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase


def stalled_since(servo: int, seconds: float) -> float | None:
    """How long the servo has been in a stall at `seconds`; None when it is not in one."""
    return next((seconds - stall.start for stall in STALLS if stall.covers(servo, seconds)), None)


def stall_current(since: float) -> float:
    """The current of a stall `since` seconds after it began."""
    if since < PUSH_SECONDS:
        return PUSH_A
    fade = max(0.0, 1.0 - (since - PUSH_SECONDS) / DECAY_SECONDS)
    return HOLD_A + (PEAK_A - HOLD_A) * fade


def drawn_current(servo: int, seconds: float) -> float:
    since = stalled_since(servo, seconds)
    return IDLE_A if since is None else stall_current(since)


def rail_volts(seconds: float) -> float:
    """The shared rail: RAIL_V while the arm's total load fits, sagging past RAIL_CAP_A."""
    load = sum(drawn_current(servo, seconds) for servo in SERVOS)
    return RAIL_V - SAG_OHMS * max(0.0, load - RAIL_CAP_A)


def commanded_deg(servo: int, seconds: float) -> float:
    if stalled_since(servo, seconds) is not None:
        return REST_DEG[servo] + STALL_STEP_DEG
    if servo == SWEEP_SERVO:
        return REST_DEG[servo] + SWEEP_SPAN_DEG * triangle(seconds / SWEEP_PERIOD_SECONDS)
    return REST_DEG[servo]


def held_position(servo: int, seconds: float, noise: float) -> float:
    """Where the servo reads: parked (or held against its stall) and rocking a little; the
    sweeping servo follows its command a beat late until its sensor freezes, then repeats the
    one value, bit for bit."""
    if servo == SWEEP_SERVO:
        return commanded_deg(servo, min(seconds, FREEZE_AT) - SWEEP_LAG_SECONDS)
    return REST_DEG[servo] + POSITION_NOISE_DEG * noise


def temperature_c(servo: int, seconds: float) -> float:
    """Idle, except the hot servo's runaway: accelerating, so the short fit sees it first."""
    if servo != HOT_SERVO or seconds < HEAT_START:
        return IDLE_C
    progress = min(1.0, (seconds - HEAT_START) / (HEAT_END - HEAT_START))
    return IDLE_C + HEAT_RISE_C * progress * progress


def reading(servo: int, quantity: str, tick: int) -> float:
    seconds = tick / HZ
    noise = dither(tick, servo, [name for name, _ in CHANNELS].index(quantity))
    match quantity:
        case "position":
            value = held_position(servo, seconds, noise)
        case "commanded_position":
            value = commanded_deg(servo, seconds)
        case "current":
            value = drawn_current(servo, seconds) + CURRENT_NOISE_A * noise
        case "temperature":
            value = temperature_c(servo, seconds) + TEMPERATURE_NOISE_C * noise
        case _:
            value = rail_volts(seconds) + VOLTAGE_NOISE_V * noise
    return round(value, 3)


def tick_line(tick: int) -> bytes:
    """One LB-06 JSON line: every servo's five channels at this tick, newline-terminated."""
    names = [(f"servo{servo}.{quantity}", unit) for servo in SERVOS for quantity, unit in CHANNELS]
    values = {
        f"servo{servo}.{quantity}": reading(servo, quantity, tick)
        for servo in SERVOS
        for quantity, _ in CHANNELS
    }
    packet = {
        "device_id": DEVICE_ID,
        "schema_version": 1,
        "seq": tick,
        "ts_us": EPOCH_US + tick * TICK_US,
        "units": dict(names),
        "values": values,
    }
    return (json.dumps(packet, separators=(",", ":"), sort_keys=True) + "\n").encode()


def recording_text() -> str:
    """The recording as `livebench.hardware.replay.load_recording` reads it."""
    frames = [
        {"t": round(tick / HZ, 3), "hex": tick_line(tick).hex()} for tick in range(HZ * SECONDS)
    ]
    document = {"transport": "usb_serial", "binding": BINDING, "frames": frames}
    return json.dumps(document, indent=1) + "\n"


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    (out_dir / FILE_NAME).write_text(recording_text())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
