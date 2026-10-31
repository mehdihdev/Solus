"""SOLUSDEV-321 P6 fix 1 (m8) — the runs narration speaks in the asker's register: after the
mode's note, its system text carries the Solus-authored line the SOL prompt carries for the same
levels (`expertise.register_line`). A caller that hands no levels gets the text unchanged."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from solus_api.agent.expertise import Expertise, register_line
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.livebench.runs import narration
from solus_api.models import SolMode
from sqlalchemy.ext.asyncio import AsyncSession

LEVELS = Expertise(control="novice", electronics="expert")


async def _system(monkeypatch: pytest.MonkeyPatch, **expertise: Any) -> str:
    """The system text of the one call `narrate` makes for one finding, in Expert mode."""
    seen: list[Any] = []

    async def complete(query: str, **kwargs: Any) -> Any:
        seen.append(kwargs["conversation"])
        return SimpleNamespace(text='["Possible stall; the cause remains uncertain."]')

    monkeypatch.setattr(narration, "complete", complete)
    finding = {
        "entity_id": str(uuid.uuid4()),
        "headline": "Possible stall",
        "explanation": "Current reached the rating.",
        "detail": "Cause is unknown.",
        "evidence": {"stall_current_a": 1.5},
    }
    answer = await narration.narrate(
        {"findings": [finding], "insufficient": []},
        secret_store=InMemorySecretStore(),
        user_id=uuid.uuid4(),
        session=cast(AsyncSession, object()),
        redis=None,
        enqueue=None,
        mode=SolMode.EXPERT,
        **expertise,
    )
    assert answer["mode"] == "model"
    (conversation,) = seen
    return str(conversation.system)


async def test_the_askers_register_follows_the_mode_note(monkeypatch: pytest.MonkeyPatch) -> None:
    register = register_line(LEVELS)
    assert register is not None
    neutral = await _system(monkeypatch)
    assert "By domain" not in neutral and neutral.endswith("terse technical explanation.")
    assert await _system(monkeypatch, expertise=LEVELS) == f"{neutral} {register}"
