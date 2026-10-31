"""SOLUSDEV-321 R115 (P4-T4 fix 2) — the Build policy's answer for a routine `simulate` routed.

`simulate` notes the routine tool it routes rungs 2 and 4 to for the turn (`note_routed`). In that
turn the Build policy treats the tool's call as forced confirmation: it is never owned, so the call
goes to its card, since the person asked to simulate, not to run a routine. The next turn the tool
is owned again.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Final

from solus_api.agent import firmware_recipe
from solus_api.agent.execution_policy import BuildExecutionPolicy, register_owned_routine
from solus_api.agent.modes import ActionMode
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.apply_sim_change import note_routed
from solus_api.agent.tools.machine_writes import build_machine_write_tool
from solus_api.agent.turn_context import bind_turn_id
from test_machine_writes import Telling
from test_simulate import _owned_routine

ROUTINE: Final = "isaac.run_routine"


async def test_a_routine_simulate_routed_is_never_owned_that_turn_and_owned_the_next() -> None:
    ran: list[dict[str, Any]] = []
    registry = ToolRegistry()
    registry.register(_owned_routine(ROUTINE, ran))

    with bind_turn_id(uuid.uuid4()):
        note_routed(ROUTINE)
        routed = await BuildExecutionPolicy(registry, ActionMode.DO).prepare(
            ToolCall(tool=ROUTINE, args={})
        )
    with bind_turn_id(uuid.uuid4()):
        owned = await BuildExecutionPolicy(registry, ActionMode.DO).prepare(
            ToolCall(tool=ROUTINE, args={})
        )

    assert (routed, owned) == (False, True)
    assert ran == []  # the policy decides; it runs nothing


async def test_a_write_in_a_turn_that_asked_for_firmware_keeps_its_card(tmp_path: Path) -> None:
    """SOLUSDEV-321 P6 (R134): `firmware_recipe` routes its turn to `machine.write_file`, and the
    same predicate forces that write's card: the person asked for firmware, not for a write. The
    next turn the owned write is Build's to run again."""
    writer = build_machine_write_tool(Telling(tmp_path))
    register_owned_routine(writer, family="machine")
    registry = ToolRegistry()
    registry.register(writer)
    write = ToolCall(tool="machine.write_file", args={"path": "fw.ino", "content": "loop\n"})

    turn = uuid.uuid4()
    with bind_turn_id(turn):
        firmware_recipe._note_routed(turn)
        routed = await BuildExecutionPolicy(registry, ActionMode.DO).prepare(write)
    with bind_turn_id(uuid.uuid4()):
        owned = await BuildExecutionPolicy(registry, ActionMode.DO).prepare(write)

    assert (routed, owned) == (False, True)
    assert not (tmp_path / "fw.ino").exists()  # the policy decides; it writes nothing
