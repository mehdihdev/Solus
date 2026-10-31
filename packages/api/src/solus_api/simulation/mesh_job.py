"""SOLUSDEV-321 P4-T4 (R110) — the mesh check as its own bounded ARQ job (docs/api/simulation.md
§7, §8).

The rung-3 mesh check (`providers/mesh_interference.py`) is numpy in process, and its worst case is
about two million edge-face tests, so it never runs in a SOL request. `simulate` enqueues
`run_mesh_sim`, and the worker runs it through `run_and_record`, the one shape of the rung-3 jobs:
off the event loop, and recorded through `record_sim_result`. The queue keeps nothing
(`keep_result=0`) and never retries (`max_tries=1`, `connectors/worker.py`): a second try would be a
second recorded run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import JsonValue, ValidationError

from solus_api.simulation.providers.mesh_interference import MeshInterference
from solus_api.simulation.sim_capability import (
    SimInput,
    SimResult,
    SimulationFailedError,
    SimulationRefusedError,
)
from solus_api.simulation.sim_facts import run_and_record

#: The most of a closed form's own refusal that a job's status repeats.
MAX_REASON: Final = 200


class QueuedMeshCheck(MeshInterference):
    """The mesh check as a job's provider. It is numpy alone, so it is available wherever the job
    runs, and a subject it has nothing to check in is refused, never a crashed job."""

    @property
    def available(self) -> bool:
        return True

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        try:
            return super().run(inputs)
        except ValidationError:  # a result past its bound: a failed run, its values never logged
            raise SimulationFailedError(f"{self.name}'s result does not validate") from None
        except ValueError as exc:  # the closed form's own "nothing to compute", naming inputs
            raise SimulationRefusedError(str(exc)[:MAX_REASON]) from None


async def run_mesh_sim(ctx: dict[str, Any], request: dict[str, Any]) -> dict[str, JsonValue]:
    """The ARQ job (module docstring)."""
    return await run_and_record(ctx, QueuedMeshCheck(), request)
