"""Ignition (Citadel 3 / Edifice 5 / Fortress 6) telemetry (SOLUSDEV-322 P3-T5).

The ignition CLI echoes exactly like the new family — `ign topic -e -t <topic> --json-output`,
one JSON document per line, `ignition.msgs.Model` on `/world/<w>/model/<m>/joint_state` — so the
source is the gz source under another binary. RECON §2 verified `--json-output` on Fortress
6.16.0 (2026-11-09); a text-format fallback is not built (ponytail: add it the day an install
without the flag is seen — `classic_source.text_blocks` + `packets_from_text_blocks` are ready).
"""

from typing import ClassVar

from livebench.sim.gazebo_family import FamilyName
from livebench.sim.gazebo_source import GazeboTopicSource


class IgnitionTopicSource(GazeboTopicSource):
    """`ign topic -e -t <topic> --json-output` per topic; the binary is `find_exe("ignition")`."""

    family: ClassVar[FamilyName] = "ignition"
