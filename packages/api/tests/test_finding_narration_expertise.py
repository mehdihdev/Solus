"""SOLUSDEV-321 P6 fix 1 (m8) — the finding narration speaks in its owner's register: after the
mode's note, its system text carries the Solus-authored line the SOL prompt carries for the same
stored levels (`expertise.register_line`), and nothing more for an owner with no levels."""

from __future__ import annotations

from solus_api.agent.expertise import Expertise, register_line
from solus_api.graph.findings import raise_finding
from solus_api.services.machines import ensure_member
from sqlalchemy.ext.asyncio import AsyncEngine
from test_finding_narration import (
    _attrs,
    _eventually,
    _explained,
    _NarrationGateway,
    _narrator,
    _observer_spec,
)
from test_gateway_purpose import _funded_user
from test_window_evaluator import _arm, _maker

LEVELS = Expertise(control="novice", electronics="expert")


async def _narrated_system(engine: AsyncEngine, levels: Expertise | None) -> str:
    """The system text of the one call that narrates a stall on a fresh arm, for an owner whose
    member node holds `levels` (no member node at all for None)."""
    maker = _maker(engine)
    project, arm = await _arm(maker)
    async with maker() as db:
        owner = await _funded_user(db)
        if levels is not None:
            member = await ensure_member(db, project, owner)
            member.attrs = {**member.attrs, "expertise": levels.model_dump()}
        stall = await raise_finding(db, project, _observer_spec(arm, 3))
        await db.commit()
    gateway = _NarrationGateway(_explained)
    narrator = _narrator(maker, gateway)

    async def written() -> bool:
        return bool((await _attrs(maker, stall.id))["explanation"])

    try:
        narrator.hear(project, owner, arm.robot, [stall.id])
        await _eventually(written)
    finally:
        await narrator.aclose()
    (conversation,) = gateway.provider.conversations
    return conversation.system


async def test_the_owners_register_follows_the_mode_note(engine: AsyncEngine) -> None:
    register = register_line(LEVELS)
    assert register is not None
    neutral = await _narrated_system(engine, None)
    assert "By domain" not in neutral and neutral.endswith("saying what its signals mean.")
    assert await _narrated_system(engine, LEVELS) == f"{neutral} {register}"
