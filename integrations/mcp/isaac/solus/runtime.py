"""Non-launching runtime helpers; no inherited configuration or open listener."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OPERATIONS = frozenset(
    {"status", "load_model", "set_joint_limits", "set_sensor_pose", "run_routine", "stop"}
)
MAX_FRAME = 128 * 1024
RUNTIME = Path("/home/beeboss/isaacsim/IsaacSim/_build/linux-aarch64/release")


def child_environment(private: Path) -> dict[str, str]:
    return {
        "HOME": str(private),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TMPDIR": str(private),
    }


def validate_frame(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_FRAME:
        raise ValueError("frame too large")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON frame") from error
    if not isinstance(value, dict) or set(value) != {
        "operation",
        "sequence",
        "generation",
        "arguments",
    }:
        raise ValueError("invalid frame fields")
    if (
        not isinstance(value["operation"], str)
        or value["operation"] not in OPERATIONS
        or type(value["sequence"]) is not int
        or not 1 <= value["sequence"] <= 1_000_000
        or not isinstance(value["generation"], str)
        or not 1 <= len(value["generation"]) <= 64
        or not isinstance(value["arguments"], dict)
    ):
        raise ValueError("invalid frame values")
    return value
