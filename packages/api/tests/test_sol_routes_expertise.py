"""SOLUSDEV-321 P6 — the SOL message route hands the runner the turn's expertise: the member's
stored levels, each domain the person stated in `preferences.expertise` winning, and None when
there is neither, so the register stays as it is. A stated level is never a prompt section, and a
level that is not one refuses the turn."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import me
from httpx import AsyncClient
from solus_api.agent.expertise import Expertise
from solus_api.services.machines import ensure_member
from sqlalchemy.ext.asyncio import AsyncSession
from test_sol import _create_conversation, _project, _RecordingRunner


def _handed(runner: _RecordingRunner) -> Expertise | None:
    """What the route handed the runner for the last turn."""
    handed: Expertise | None = runner.ctx.expertise
    return handed


async def test_the_turns_expertise_reaches_the_runner(
    app: Any, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project = await _project(client, alice_headers)
    convo = await _create_conversation(client, alice_headers, project["id"])
    runner = _RecordingRunner()
    app.state.agent_runner = runner
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{convo['id']}/messages"

    plain = await client.post(url, json={"content": "hi"}, headers=alice_headers)
    assert plain.status_code == 200 and _handed(runner) is None

    stated = {"content": "hi", "preferences": {"expertise": {"control": "novice"}}}
    assert (await client.post(url, json=stated, headers=alice_headers)).status_code == 200
    assert _handed(runner) == Expertise(control="novice")
    assert runner.ctx.engineering_preferences is None  # a stated level is no prompt section

    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    member = await ensure_member(db, uuid.UUID(project["id"]), user_id)
    member.attrs = {**member.attrs, "expertise": Expertise(software="expert").model_dump()}
    await db.commit()
    assert (await client.post(url, json=stated, headers=alice_headers)).status_code == 200
    assert _handed(runner) == Expertise(software="expert", control="novice")

    for bad in ({"control": "guru"}, {"firmware": "expert"}):
        refused = await client.post(
            url, json={"content": "hi", "preferences": {"expertise": bad}}, headers=alice_headers
        )
        assert refused.status_code == 422, bad
