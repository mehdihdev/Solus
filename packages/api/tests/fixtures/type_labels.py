"""LABELED TYPE FIXTURE — REVIEW ME (Pratham).

These robotics queries (with optional measurable attachments) and their
expected RouteType ARE the spec for the MO-04 type estimator: the
`type_estimator:` knobs in `solus_api/orchestration/models.yaml` are tuned so
`estimate_type` reproduces every label below. Disagree with a label? Change it
HERE and re-tune the yaml (patterns/thresholds — never code) until
`test_type_estimator.py::test_labeled_type_fixture_matches` is green again.

Labeling rubric (the precedence rule — hard constraints beat soft preferences):
- LONG_CONTEXT — the MEASURED input (query + attachment tokens) is too big for
  small-window models; overrides everything else (it must physically FIT).
- VISUAL_LOG  — an image/log artifact is attached, or the query is plainly
  about logs/telemetry/plots; beats CODE (the model must be able to SEE it).
- CODE        — code/firmware/build-error language; a strength preference.
- GENERAL     — everything else.

Lines marked # DEBATABLE are judgment calls listed in the MO-04 report.
"""

from solus_api.orchestration.enums import RouteType
from solus_api.orchestration.type_estimator import AttachmentHint

_LOG_300K = (AttachmentHint(kind="log", tokens=300_000),)
_IMAGE = (AttachmentHint(kind="image", tokens=0),)

# (query, attachments, expected type)
LABELED_TYPES: list[tuple[str, tuple[AttachmentHint, ...] | None, RouteType]] = [
    # --- GENERAL: factual/selection questions, no code/log/window signal ------
    ("what pin is PWM on an Arduino Nano", None, RouteType.GENERAL),
    ("how many amps does a SG90 servo draw", None, RouteType.GENERAL),
    ("compare these two motor drivers for torque", None, RouteType.GENERAL),
    ("why is my robot veering left after the new chassis", None, RouteType.GENERAL),
    ("what's a good battery for a 4kg rover", None, RouteType.GENERAL),
    ("explain PID tuning for beginners", None, RouteType.GENERAL),
    # --- CODE: code/firmware/build-error language ------------------------------
    ("why does my firmware throw a segmentation fault on boot", None, RouteType.CODE),
    ("fix this traceback from my ROS node", None, RouteType.CODE),
    ("here's my motor_control.py, why does init_pwm() hang", None, RouteType.CODE),
    ("undefined reference to imu_read when linking", None, RouteType.CODE),
    ("write a function to debounce the limit switch", None, RouteType.CODE),
    ("my launch file fails: compile error in servo_driver.cpp", None, RouteType.CODE),
    ("```\nvoid setup() { init_pwm(); }\n``` why does this run twice", None, RouteType.CODE),
    ("colcon build fails after adding the lidar package", None, RouteType.CODE),
    # --- VISUAL_LOG: log/telemetry language or an attached visual artifact ----
    ("what do these telemetry spikes mean", None, RouteType.VISUAL_LOG),
    ("summarize the errors in these boot logs", None, RouteType.VISUAL_LOG),
    ("here's a screenshot of the oscilloscope trace", None, RouteType.VISUAL_LOG),
    # attachment modality wins even when the words are about wiring:
    ("what's wrong in this picture of my wiring", _IMAGE, RouteType.VISUAL_LOG),
    ("check the serial monitor output from the crash", None, RouteType.VISUAL_LOG),
    (
        "analyze the attached flight log file",
        (AttachmentHint(kind="log", tokens=2_000),),  # small: stays VISUAL_LOG
        RouteType.VISUAL_LOG,
    ),
    # --- LONG_CONTEXT: MEASURED size wins over everything ----------------------
    (
        "summarize this build output",
        (AttachmentHint(kind="file", tokens=250_000),),
        RouteType.LONG_CONTEXT,
    ),
    # THE precedence case: clearly a code question, but 300K tokens attached —
    # the window is a physical constraint, code strength is only a preference.
    ("why does init_pwm() fail intermittently", _LOG_300K, RouteType.LONG_CONTEXT),
    # ...and over VISUAL_LOG language too:
    (
        "find the anomaly in these telemetry logs",
        (AttachmentHint(kind="log", tokens=500_000),),
        RouteType.LONG_CONTEXT,
    ),
    # the query TEXT alone is huge (measured, not inferred from wording):
    ("review this register dump: " + "a5 " * 150_000, None, RouteType.LONG_CONTEXT),
    (
        "cross-reference the whole codebase dump against the schematic",
        (AttachmentHint(kind="file", tokens=800_000),),
        RouteType.LONG_CONTEXT,
    ),
    (
        "what changed between these two firmware images",
        (
            AttachmentHint(kind="file", tokens=150_000),
            AttachmentHint(kind="file", tokens=140_000),
        ),
        RouteType.LONG_CONTEXT,
    ),
]
