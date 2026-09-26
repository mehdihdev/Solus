# solus-telemetry

One-include telemetry emitters for Arduino (C++), MicroPython and Python that write Solus
**LB-06** packets as JSON lines. Optional — Solus also reads raw serial and generic JSON — but a
board that speaks LB-06 arrives in Live Bench with named, unit-tagged signals and a sequence
counter, nothing to configure. MIT licensed.

## The line

One packet per line, keys always in this order; `seq` is omitted when unsequenced and `units`
when empty:

```
{"schema_version":1,"device_id":"usb:5B42134331","ts_us":1757145600000000,"values":{"base.velocity":0.1234,"imu.accel_z":9.8067},"seq":7,"units":{"base.velocity":"m/s","imu.accel_z":"m/s^2"}}
```

| key              | meaning                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------- |
| `schema_version` | always `1`                                                                                  |
| `device_id`      | who is talking — see _How Solus recognises the stream_                                      |
| `ts_us`          | integer microseconds: epoch on a host with a clock, since boot on a bare board (see below)   |
| `values`         | signal name → finite number, 1–256 signals, names 1–128 chars                               |
| `seq`            | monotonic per-device counter from 0 — Solus detects drops and reordering from it            |
| `units`          | unit symbol per signal (≤ 32 chars); keys must be a subset of `values`                      |

Full contract: `docs/contracts/telemetry-packet.md` in the Solus repo.

## How Solus recognises the stream

- **`device_id`** should be the device ref Solus shows for the board (Live Bench → connections),
  e.g. `usb:<USB serial>` → `usb:5B42134331`. Solus pins the first identity it sees on a link and
  drops packets that change it mid-stream.
- **Signal names** are `<part>.<quantity>`: `base.velocity`, `imu.accel_z`, `shoulder_pan.position`.
  `<part>` is the part name as confirmed in the robot's hardware config, `<quantity>` a lowercase
  snake_case physical quantity. The unit goes in `units`, never in the name (`joint_3.pos_deg` is
  the shape this retires).
- **`units`** is a map from signal name to unit symbol: `m/s`, `rad/s`, `m/s^2`, `A`, `V`, `degC`.
- **`ts_us`** on a board without a wall clock is microseconds since boot (Arduino `micros()` is a
  `uint32` and wraps every ~71.6 minutes). Solus orders samples by `seq`, so this is accepted — it
  is simply not wall-clock time. Send epoch microseconds when the device has an RTC or NTP.

Lines longer than 64 KiB are refused by Solus before parsing; every emitter here validates and
bounds a packet before writing it, so a line that leaves the library always decodes.

## Python

```
pip install solus-telemetry          # or, inside the Solus workspace: uv sync --all-packages
```

```python
import serial
from solus_telemetry import Emitter, format_line

port = serial.Serial("/dev/ttyUSB0", 115200)
tx = Emitter("usb:5B42134331", port.write)          # clock_us defaults to epoch microseconds
tx.send({"base.velocity": 0.1234, "imu.accel_z": 9.8067}, {"base.velocity": "m/s"})  # -> seq 0

line = format_line("usb:5B42134331", {"base.velocity": 0.1234}, ts_us=1_757_145_600_000_000)
```

`format_line(device_id, values, *, ts_us, seq=None, units=None) -> str` returns the line with its
trailing newline and raises `ValueError` for anything Solus would refuse. `Emitter(device_id,
write, *, clock_us=...)` stamps the clock, assigns `seq` (monotonic from 0) and calls
`write(bytes)`; `send()` returns the `seq` used. No dependencies; Python ≥ 3.10.

## MicroPython

Copy `micropython/solus_telemetry.py` to the board (`mpremote cp micropython/solus_telemetry.py :`).

```python
from machine import UART
from solus_telemetry import Emitter

uart = UART(1, 115200)
tx = Emitter("usb:5B42134331", uart.write)   # time.time_ns() when the port has it, else ticks_us()
tx.send({"base.velocity": 0.1234}, {"base.velocity": "m/s"})
```

Same `format_line` / `Emitter` API and the same bytes as the Python package. `python3
micropython/solus_telemetry.py` runs its self-check on a host.

## Arduino

Install `arduino/` as a library (Sketch → Include Library → Add .ZIP Library, or copy it into
`~/Arduino/libraries/SolusTelemetry`). `examples/NanoSixChannels` streams six unit-tagged channels.

```cpp
#include <SolusTelemetry.h>

SolusTelemetry telemetry(Serial, "usb:5B42134331");

void setup() { Serial.begin(115200); telemetry.begin(); }

void loop() {
  telemetry.add("base.velocity", 0.1234f, "m/s");
  telemetry.add("imu.accel_z", 9.8067f, "m/s^2");
  telemetry.send();   // one line; add() returns false when a channel is rejected
  delay(10);
}
```

Fixed buffers, no heap: up to 16 channels per line, values printed with 4 decimals
(`|value| < 1e9`), `ts_us` from `micros()`, `seq` a `uint32`. `add()` keeps pointers to `name` and
`unit` — pass string literals or keep the strings alive until `send()`. A UART carries `baud / 10`
bytes per second, so size the line and rate to the link (the six-channel example line is ~330
bytes: ~35 Hz at 115200 baud, 100 Hz needs ≥ 500000).

`arduino/extras/host/` compiles the library on a host against a tiny `Stream` stub; the Solus
test suite runs it to pin the golden line the three runtimes must agree on.

## Layout

```
libs/solus-telemetry/
├── LICENSE                 MIT
├── python/                 pip package `solus-telemetry` (uv workspace member in the Solus repo)
├── micropython/            single-file module, copy to the board
└── arduino/                Arduino library (library.properties, src/, examples/, extras/host/)
```

## Existing Python control loops

Use `import solus_telemetry as solus` (the `solus` module name is already used by several tool
integrations). Explicitly configure the completed read/write methods and numeric dictionary keys:

```python
import solus_telemetry as solus

config = solus.MirrorConfig(
    device_id="ethernet:127.0.0.1", port=14550,
    methods=(solus.MethodAdapter("get_observation", {"shoulder.position": "shoulder.pos"}),),
    units={"shoulder.position": "deg"},
)
handle = solus.mirror(robot, config=config)
# Your existing loop continues unchanged. Stop mirroring with handle.close().
```

The default mirror sink sends UDP datagrams, but Solus does not currently wire a UDP
receiver into Live Bench. That default alone is not an end-to-end integration. Use the
authenticated HTTP publisher below for an existing controller loop.
The shim observes completed method calls; it never starts the robot or reads it again. Only
configured numeric dictionary fields are copied. Queue overflow or sink failure drops mirror
samples and increments counters rather than blocking control. No socket opens on import.
Source insertion uses the existing reviewed local-file diff; linking a repository alone grants
no permission to alter a control loop.


## Publish completed observations to Live Bench over HTTP

The controller remains the sole owner of the serial ports. Copy its already-read values:

```python
import os
from solus_telemetry import HttpPublisher

publisher = HttpPublisher(
    os.environ["SOLUS_API_URL"],       # e.g. http://127.0.0.1:8000
    os.environ["SOLUS_PROJECT_ID"],
    os.environ["SOLUS_ACCESS_TOKEN"],  # existing authenticated bearer access token
)
try:
    # Inside your existing loop, AFTER its successful hardware read:
    # observation = robot.get_observation()
    publisher.submit(
        "usb:YOUR_BOARD_SERIAL/1",     # exact accepted graph part external_ref
        {"shoulder_pan.position": observation["shoulder_pan.pos"]},
        {"shoulder_pan.position": "deg"},  # must match the calibration's units
    )
finally:
    publisher.close()
    print(publisher.counters)
```

Configure graph device/part identities in the same project first: HTTP success does not
mean an unknown device resolved. `accepted`, `unresolved`, and `rejected` counters report
the server's actual result. `submitted` counts valid samples offered to the queue;
`dropped` includes overflow, expiry, failed batches, and close; `invalid` counts malformed
samples; `errors` counts failed HTTP batches. A queued sample is not proof of delivery.

The publisher never opens serial or reads a robot. Submission copies bounded values in
memory; a daemon sends at most one batch per second by default (500 packets and 1 MiB
maximum). Queued samples older than two seconds are discarded. Network errors, expired
authentication, and rate limits drop that batch without retry; obtain a fresh access token
and create a new publisher when necessary. Close discards pending samples and waits up
to 0.25 seconds by default, returning false if an HTTP call is still finishing. For a final
counter snapshot, use `close(timeout=3)` with the default two-second transport timeout.
This best-effort stream is not a durable recording or a safety/control channel.

Only HTTPS origins or literal loopback HTTP origins are accepted. Credentials, paths,
queries, and fragments in the origin are rejected. The transport does not follow redirects
or use environment proxies. No network activity occurs at import. Disconnect Solus's direct
serial session before starting the external controller; this publisher does not stop an
existing reader or arbitrate the serial bus.
