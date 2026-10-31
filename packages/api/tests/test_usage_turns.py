"""SOLUSDEV-321 P8 — `GET /projects/{id}/usage/turns`: the caller's own ledger rows in one project.

Every model call's row carries `project_id`, `turn_id`, `purpose` and `tier`, and a call that costs
nothing still writes one (amount 0, the balance untouched), so usage counts every call. The route
reads the caller's rows first (`user_id`, the indexed column), then the project's, newest first,
no further back than 90 days; it never returns a balance, and another team's project is a 404.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import BOB, add_member
from fastapi import FastAPI
from fixtures.fake_arm import CODE_PATH, seed_fake_arm
from fixtures.fake_systems import FakeSolSystems
from fixtures.screenshot import screenshot_block
from httpx import AsyncClient
from solus_api.agent import screen
from solus_api.agent.documents.extract import extract_pages
from solus_api.agent.documents.pdf import PageImage
from solus_api.agent.firmware_recipe import FirmwareRecipe
from solus_api.agent.modes import ActionMode
from solus_api.agent.runtime import LlmRunner
from solus_api.agent.tools.machine_writes import build_machine_write_tool
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_context import PerceptionTurn, bind_perception, bind_turn_id
from solus_api.agent.turn_limits import turn_limits
from solus_api.agent.vision.vision_extract import vision_extract
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import CreditBalance, CreditLedger, CreditTxnType, User, utcnow
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.gateway import Completion, complete
from solus_api.orchestration.providers import ImageBlock, ToolConversation, ToolUse, Usage
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_extension_credit_attribution import _adapters
from test_gateway_purpose import _config
from test_machine_writes import Telling
from test_sol import _create_conversation, _project
from test_vision_extract import _render_png

TIERS = {tier.value for tier in Complexity}


class _FreeModel:
    """A scripted adapter whose call costs nothing: no tokens either way."""

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        yield "ok"
        yield Usage(tokens_in=0, tokens_out=0)


async def _user(db: AsyncSession, email: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def _turns_url(project_id: object) -> str:
    return f"/api/v1/projects/{project_id}/usage/turns"


async def test_ledger_rows_carry_project_turn_purpose_tier(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """A real SOL turn through the real gateway: its rows name the project, the turn, why the call
    ran and the tier it was routed at — and the route lists exactly them."""
    app.state.agent_runner = LlmRunner(adapters=_adapters())
    app.state.sol_systems = FakeSolSystems()
    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    reply = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
        headers=alice_headers,
        json={"content": "hello"},
    )
    assert reply.status_code == 200, reply.text
    assert "event: done" in reply.text
    alice = await _user(db, "alice@example.com")
    rows = list(
        await db.scalars(
            select(CreditLedger)
            .where(CreditLedger.user_id == alice.id, CreditLedger.type == CreditTxnType.USAGE)
            .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        )
    )
    assert rows, "the turn's model call wrote no ledger row"
    assert {row.attrs["purpose"] for row in rows} == {"answer"}
    assert {row.attrs["project_id"] for row in rows} == {project["id"]}
    assert {row.attrs["tier"] for row in rows} <= TIERS
    (turn_id,) = {row.attrs["turn_id"] for row in rows}  # one turn
    uuid.UUID(turn_id)

    listed = await client.get(_turns_url(project["id"]), headers=alice_headers)
    assert listed.status_code == 200, listed.text
    assert [
        (item["id"], item["purpose"], item["tier"], item["turn_id"], item["credits"])
        for item in listed.json()["data"]
    ] == [(str(row.id), "answer", row.attrs["tier"], turn_id, -row.amount) for row in rows]
    assert all(item["credits"] > 0 for item in listed.json()["data"])


async def test_zero_credit_call_still_recorded(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project = await _project(client, alice_headers)
    alice = await _user(db, "alice@example.com")
    before = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == alice.id))
    turn_id = uuid.uuid4()

    result = await complete(
        "hi",
        secret_store=InMemorySecretStore(),
        config=_config(),
        adapters={"anthropic": _FreeModel()},
        user_id=alice.id,
        session=db,
        purpose="answer",
        turn_id=turn_id,
        project_id=uuid.UUID(project["id"]),
    )

    row = await db.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == result.call_id)
    )
    assert row is not None, "a zero-credit call wrote no row"
    assert row.amount == 0
    assert row.attrs["project_id"] == project["id"]
    assert row.attrs["turn_id"] == str(turn_id)
    assert row.attrs["purpose"] == "answer"
    assert row.attrs["tier"] == result.model.complexity.value
    after = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == alice.id))
    assert after == before  # nothing was debited
    listed = await client.get(_turns_url(project["id"]), headers=alice_headers)
    assert [
        (item["credits"], item["purpose"], item["turn_id"]) for item in listed.json()["data"]
    ] == [(0, "answer", str(turn_id))]


class _FencedModel:
    """A scripted adapter for every route: a fenced file (the firmware recipe reads its new file
    out of one), then usage — a real gateway call, with its real ledger row."""

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        yield "```cpp\nvoid setup() {}\nvoid loop() {}\n```\n"
        yield Usage(tokens_in=120, tokens_out=80)


async def test_every_in_turn_call_site_lists_its_row(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R148: a tool's own model call inside a SOL turn — a render read, a document page read, the
    firmware recipe — and the runner's screenshot read each write a usage row naming the turn and
    its project (the real gateway on a scripted adapter), so the project's usage lists all four."""
    team, project = await _project(client, alice_headers)
    project_id, team_id = uuid.UUID(project["id"]), uuid.UUID(team["id"])
    alice = await _user(db, "alice@example.com")
    arm = await seed_fake_arm(db, project_id, user_id=None)
    await db.commit()
    (tmp_path / CODE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / CODE_PATH).write_text("void setup() {}\n")
    model = _FencedModel()
    scripted = {"anthropic": model, "openai": model, "google": model}
    real = gateway.complete

    async def on_the_scripted_model(query: str, **kwargs: Any) -> Completion:
        # The recipe names no adapters (it runs on the shipped providers): here every site runs on
        # the scripted one, through the real gateway, its gates and its ledger write.
        return await real(query, **{**kwargs, "adapters": scripted})

    monkeypatch.setattr(gateway, "complete", on_the_scripted_model)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    secrets, turn, png = InMemorySecretStore(), uuid.uuid4(), _render_png()
    budget = TurnBudget(replace(turn_limits(ActionMode.DO), max_model_calls=12))
    recipe = FirmwareRecipe(
        sessions=maker,
        project_id=project_id,
        user_id=alice.id,
        team_id=team_id,
        writer=build_machine_write_tool(Telling(tmp_path)),
        secret_store=secrets,
        redis=None,
        enqueue=None,
    )
    with bind_turn_id(turn, project_id), bind_perception(PerceptionTurn(budget)):
        async with maker() as session:
            render = await vision_extract(
                png, secret_store=secrets, user_id=alice.id, session=session
            )
        async with maker() as session:
            await extract_pages(
                [PageImage(index=1, png=png, width=64, height=48)],
                question=None,
                secret_store=secrets,
                user_id=alice.id,
                session=session,
            )
        await recipe.prepare({"board_id": str(arm.brain), "path": CODE_PATH})
    # The runner reads a screenshot before any dispatch binds the turn: it hands the turn over.
    async with maker() as session:
        await screen.read_screen(
            screenshot_block(),
            secret_store=secrets,
            user_id=alice.id,
            session=session,
            turn_id=turn,
            project_id=project_id,
        )

    assert render.read is True
    listed = await client.get(_turns_url(project_id), headers=alice_headers)
    assert listed.status_code == 200, listed.text
    assert sorted((item["purpose"], item["turn_id"]) for item in listed.json()["data"]) == sorted(
        [
            ("vision", str(turn)),
            ("extract", str(turn)),
            ("answer", str(turn)),
            ("vision", str(turn)),
        ]
    )


async def test_user_scoped_and_never_balance_after(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team, project = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    _, other = await _project(client, alice_headers)
    alice = await _user(db, "alice@example.com")
    bob = await _user(db, BOB["email"])
    now = utcnow()

    def ledger(
        user: User,
        project_id: str,
        *,
        minutes_ago: int,
        attrs: dict[str, Any] | None = None,
        kind: CreditTxnType = CreditTxnType.USAGE,
    ) -> CreditLedger:
        row = CreditLedger(
            user_id=user.id,
            amount=-3,
            type=kind,
            balance_after=97,
            idempotency_key=f"key-{uuid.uuid4()}",
            attrs={
                "project_id": project_id,
                "purpose": "answer",
                "tier": "standard",
                "turn_id": str(uuid.uuid4()),
                "tokens_in": 120,
                "tokens_out": 80,
                **(attrs or {}),
            },
            created_at=now - timedelta(minutes=minutes_ago),
        )
        db.add(row)
        return row

    answer = ledger(alice, project["id"], minutes_ago=5)
    web = ledger(alice, project["id"], minutes_ago=1, attrs={"purpose": "web", "tier": None})
    ledger(alice, project["id"], minutes_ago=100 * 24 * 60)  # older than any read reaches
    ledger(alice, other["id"], minutes_ago=2)  # this person's, another project's
    ledger(alice, project["id"], minutes_ago=3, kind=CreditTxnType.TRIAL_GRANT)  # not usage
    theirs = ledger(bob, project["id"], minutes_ago=4)  # a teammate's, same project
    await db.commit()

    url = _turns_url(project["id"])
    since = {"since": (now - timedelta(days=200)).isoformat()}
    mine = await client.get(url, headers=alice_headers, params=since)
    assert mine.status_code == 200, mine.text
    assert [item["id"] for item in mine.json()["data"]] == [str(web.id), str(answer.id)]
    assert "balance" not in mine.text
    assert set(mine.json()["data"][0]) == {
        "id",
        "created_at",
        "turn_id",
        "purpose",
        "tier",
        "credits",
        "tokens_in",
        "tokens_out",
    }
    newest = mine.json()["data"][0]
    assert (newest["purpose"], newest["tier"], newest["credits"]) == ("web", None, 3)
    first = await client.get(url, headers=alice_headers, params={"limit": 1})
    assert first.json()["meta"]["has_next"] is True
    rest = await client.get(
        url,
        headers=alice_headers,
        params={"limit": 1, "cursor": first.json()["meta"]["next_cursor"]},
    )
    assert [item["id"] for item in rest.json()["data"]] == [str(answer.id)]
    teammate = await client.get(url, headers=bob_headers)
    assert [item["id"] for item in teammate.json()["data"]] == [str(theirs.id)]


async def test_cross_team_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _, project = await _project(client, alice_headers)
    url = _turns_url(project["id"])
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    unknown = await client.get(_turns_url(uuid.uuid4()), headers=alice_headers)
    assert unknown.status_code == 404


async def test_the_usage_order_is_served_by_an_index(db: AsyncSession) -> None:
    """M9: the route reads one person's usage rows newest first; `(user_id, created_at)` on the
    ledger serves that order instead of a sort per page."""
    found = await db.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_credit_ledger_user_created'")
    )
    assert found is not None and "credit_ledger" in found and "(user_id, created_at)" in found
