"""LABELED COMPLEXITY FIXTURE — REVIEW ME (Pratham).

These robotics queries and their expected tiers ARE the spec for the
query-based estimator (MO-02): the `estimator:` knobs in
`solus_api/orchestration/models.yaml` are tuned so `estimate_complexity`
reproduces every label below. If you disagree with a label, change it HERE and
re-tune the config (thresholds / weights / keyword lists — never code) until
`test_complexity.py::test_labeled_fixture_matches` is green again.

Labeling rubric used:
- TRIVIAL  — short, single-domain factual lookup (a datasheet-style answer).
- STANDARD — implementation how-to, comparison, calculation, or setup work
             within one or two domains.
- HARD     — diagnosis/debugging, anomaly hunting, or reasoning that spans
             multiple domains (code AND electrical AND mechanical).

Lines marked # DEBATABLE are judgment calls listed in the MO-02 report.
"""

from solus_api.orchestration.enums import Complexity

LABELED_QUERIES: list[tuple[str, Complexity]] = [
    # --- TRIVIAL: short single-domain factual lookups -------------------------
    ("what pin is PWM on an Arduino Nano", Complexity.TRIVIAL),
    ("what's the default baud rate for an ESP32", Complexity.TRIVIAL),
    ("how many amps does a SG90 servo draw", Complexity.TRIVIAL),
    ("what voltage does a Raspberry Pi 5 need", Complexity.TRIVIAL),
    ("what does PWM stand for", Complexity.TRIVIAL),
    ("default I2C address of the MPU6050", Complexity.TRIVIAL),
    ("max current of an L298N motor driver", Complexity.TRIVIAL),
    ("what gauge wire for a 5V servo", Complexity.TRIVIAL),
    # DEBATABLE: the ticket's example list put this in STANDARD (it implies an
    # Ohm's-law calculation), but to a text heuristic it is indistinguishable
    # from the "what gauge wire" lookup above — labeling both TRIVIAL for
    # consistency. Adjudicate the pair together.
    ("what resistor for this LED at 3.3V", Complexity.TRIVIAL),
    # --- STANDARD: implementation how-tos, comparisons, calculations ----------
    ("how do I read an IMU over I2C in my firmware", Complexity.STANDARD),
    ("compare these two motor drivers for a 12V DC motor", Complexity.STANDARD),
    ("how do I set up PlatformIO for an ESP32 project", Complexity.STANDARD),
    ("how to calibrate the magnetometer on my flight controller", Complexity.STANDARD),
    ("how do I tune a PID loop for a small drone", Complexity.STANDARD),
    ("calculate the power budget for two ESCs and a Jetson", Complexity.STANDARD),
    ("how do I publish IMU data to a ROS topic", Complexity.STANDARD),
    ("recommend a battery for a 4kg differential drive robot", Complexity.STANDARD),
    ("how to wire a limit switch to a GPIO pin", Complexity.STANDARD),
    ("convert this URDF to MJCF for simulation", Complexity.STANDARD),
    ("how do I mount this lidar on an aluminum frame", Complexity.STANDARD),
    ("choose between an absolute and incremental encoder for this joint", Complexity.STANDARD),
    # Long requirements ramble with no diagnostic signal: length alone should
    # not reach HARD — it lands STANDARD.
    (
        "we are building a small autonomous boat that needs to run for six "
        "hours on one charge and carry a camera payload while staying under "
        "two kilograms total weight so what should we think about when "
        "picking parts for this competition",
        Complexity.STANDARD,
    ),
    # --- HARD: diagnosis and cross-domain reasoning ----------------------------
    ("why is my SLAM drifting when the robot turns", Complexity.HARD),
    (
        "my servo torque doesn't match the arm load and the code assumes a "
        "range the joint can't reach — what's wrong",
        Complexity.HARD,
    ),
    (
        "trace why the robot veers left across the control code and the motor wiring",
        Complexity.HARD,
    ),
    ("debug why the ROS node stops publishing when the servos move", Complexity.HARD),
    (
        "the IMU readings jitter whenever the motors spin up — is this "
        "electrical noise or a firmware timing issue",
        Complexity.HARD,
    ),
    (
        "why does my robot arm overshoot the target position and oscillate before settling",
        Complexity.HARD,
    ),
    (
        "the battery brownout resets the Jetson every time the arm lifts a load — where do I start",
        Complexity.HARD,
    ),
    ("intermittent CAN bus errors only when the chassis vibrates", Complexity.HARD),
    (
        "the gripper firmware conflicts with the wrist joint limits in CAD — "
        "the fingers crash into the mount",
        Complexity.HARD,
    ),
    ("why is odometry wrong only when driving on carpet", Complexity.HARD),
]
