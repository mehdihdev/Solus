"""SOLUSDEV-322 P1-T2 — simulator facts derived from a machine's `tool_versions`.

The companion reports one redacted line per installed binary (`machine.tool_versions`); this
module turns the simulator-related lines into `attrs.simulators`, stored beside the raw map by
`services/machines.py:upsert_machine`. Nothing is guessed: a family is named only from the binary
that printed its version, and an absent binary yields None / False.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

GazeboFamily = Literal["classic", "ignition", "gz"]

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+|\d+")
#: Classic Gazebo (≤ 11) prints "Gazebo multi-robot simulator, version 11.x" from every binary,
#: including the `gz` that the modern `gz sim --versions` probe falls back to.
_CLASSIC_MARK = "multi-robot simulator"


def _simulator_version(line: str) -> str:
    """The first dotted number in the redacted line, or the whole line when it carries none."""
    match = _VERSION_RE.search(line)
    return match.group(0) if match else line.strip()


def _gazebo(tool_versions: Mapping[str, str]) -> dict[str, Any] | None:
    """Newest family first: a modern `gz`, then `ign`, then any classic binary."""
    gz = tool_versions.get("gz")
    if gz and _CLASSIC_MARK not in gz:
        return {"family": "gz", "version": _simulator_version(gz)}
    ign = tool_versions.get("ign")
    if ign:
        return {"family": "ignition", "version": _simulator_version(ign)}
    classic = next(
        (tool_versions[k] for k in ("gzserver", "gazebo", "gz") if tool_versions.get(k)), None
    )
    return {"family": "classic", "version": _simulator_version(classic)} if classic else None


def derive_simulators(tool_versions: Mapping[str, str]) -> dict[str, Any]:
    ngspice = tool_versions.get("ngspice")
    return {
        "gazebo": _gazebo(tool_versions),
        "nvidia_smi": bool(tool_versions.get("nvidia-smi")),
        "ngspice": _simulator_version(ngspice) if ngspice else None,
    }
