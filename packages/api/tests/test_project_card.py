"""SOLUSDEV-321 P0-T5 — the project card: layer 2 of SOL's stable prompt prefix.

Project-wide facts — robots, sources and what each can do, `.solus` counts — are cached per
project and dropped by the graph-changed fan-out. Open-finding counts, the budgets line, active
bench sessions and the caller's own machine are read per request and never cached. The machine
is the one the caller's LIVE bridge session runs on, and only when they own its row: a
teammate's machine (and its commands) never renders, whatever id a companion claims. Every
rendered string is redacted and capped; a failure anywhere means no card, never a failed turn.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent import prompt
from solus_api.agent.context import Context
from solus_api.agent.layers import ContextSection
from solus_api.agent.project_card import (
    CARD_MAX_TOKENS,
    CardInputs,
    CardRobot,
    CardSource,
    MachineBlock,
    ProjectCard,
    ProjectCardCache,
    build_project_card,
    card_inputs,
    machine_block,
    owned_commands,
    owns_machine,
    project_card_section,
    render_card,
    tool_versions,
)
from solus_api.agent.stream import AgentEventType
from solus_api.bridge.registry import BridgeSession
from solus_api.checkers.interface import Severity
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.registry import ConnectorRegistry, build_registry
from solus_api.core.config import Settings
from solus_api.graph import kinds
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.graph.graph_changed_fanout import GraphChangedFanout, graph_changed_callbacks
from solus_api.graph.live import LiveHub, graph_changed_frame
from solus_api.livebench.sessions import SessionManager
from solus_api.models import (
    Domain,
    GraphEntity,
    Project,
    SolusSection,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
    utcnow,
)
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.type_estimator import estimate_tokens
from solus_api.services.budgets import store_budgets
from solus_api.services.machines import MachineIn, find_machine, upsert_machine
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import add_text_entry, put_config_entry
from solus_api.services.solus_payloads import BudgetLine, Budgets, ConstraintMeta
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from test_sessions import FakeConn, _manager, _packet, _start
from test_sol_reasoner import _ctx, _run, _ScriptedModel

_ESTIMATOR = default_orchestration_config().type_estimator
_LOGGER = "solus.agent.project_card"
COMPANION = "0123456789abcdef0123456789abcdef"
_CONVERSATION = uuid.UUID("0190f1a2-0000-7000-8000-000000000325")
_CARD_BLOCK = re.compile(r"kind=context_project_card>>>\n(.*?)\n<<<END-SOLUS-DATA", re.S)


async def _project(db: AsyncSession, name: str = "Rover") -> tuple[uuid.UUID, uuid.UUID]:
    team = Team(name="T")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=name)
    db.add(project)
    await db.commit()
    return project.id, team.id


async def _user(db: AsyncSession) -> uuid.UUID:
    handle = uuid.uuid4().hex
    user = User(supabase_user_id=handle, email=f"{handle}@example.dev")
    db.add(user)
    await db.commit()
    return user.id


async def _robot(
    db: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    *,
    external_ref: str | None = None,
    deleted: bool = False,
    **attrs: str,
) -> GraphEntity:
    robot = GraphEntity(
        project_id=project_id,
        kind=kinds.PHYSICAL_ROBOT,
        domain=Domain.PROJECT,
        origin="manual",
        name=name,
        external_ref=external_ref,
        attrs=attrs,
        deleted_at=utcnow() if deleted else None,
    )
    db.add(robot)
    await db.commit()
    return robot


async def _source(
    db: AsyncSession,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    kind: SourceType,
    name: str,
    status: SourceStatus,
) -> None:
    db.add(Source(project_id=project_id, team_id=team_id, type=kind, name=name, status=status))
    await db.commit()  # one transaction each: creation order is the card's order


async def _finding(
    db: AsyncSession, project_id: uuid.UUID, subject: uuid.UUID, severity: Severity, rule_id: str
) -> GraphEntity:
    spec = FindingSpec(
        rule_id=rule_id,
        severity=severity,
        source="checker",
        headline=f"{rule_id} on the arm",
        subjects=[subject],
        domain=Domain.ELECTRICAL,
    )
    finding = await raise_finding(db, project_id, spec)
    await db.commit()
    return finding


def _companion_session(
    user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID, companion: str = COMPANION
) -> BridgeSession:
    """A live bridge session: the scope is server-derived, `companion` is what the
    client claims to be."""

    async def _send(frame: str) -> None:
        return None

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        companion_instance_id=companion,
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(),
        send=_send,
        close=_close,
        max_inflight=1,
    )


async def _inputs(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    cache: ProjectCardCache,
    connectors: ConnectorRegistry,
    sessions: SessionManager | None = None,
    live: BridgeSession | None = None,
) -> CardInputs:
    inputs = await card_inputs(
        db,
        project_id=project_id,
        user_id=user_id,
        live=live,
        cache=cache,
        sessions=sessions,
        connectors=connectors,
    )
    assert inputs is not None
    return inputs


def _card_text(prefix: str) -> str:
    """The project card's own text, out of a prefix turn's fenced block."""
    match = _CARD_BLOCK.search(prefix)
    assert match is not None, "no project card in the prefix"
    text: str = json.loads(match.group(1))["text"]
    return text


async def test_card_lists_robots_sources_solus_counts_budgets(
    db: AsyncSession, settings: Settings
) -> None:
    project_id, team_id = await _project(db)
    elsewhere, _ = await _project(db, name="Elsewhere")
    arm = await _robot(db, project_id, "Arm A", external_ref="dev-1", host_machine_id="host-a")
    spare = await _robot(db, project_id, "Arm B")
    await _robot(db, project_id, "Scrapped arm", deleted=True)
    await _robot(db, elsewhere, "Not ours")
    await _source(
        db, project_id, team_id, SourceType.GITHUB, "Rover firmware", SourceStatus.CONNECTED
    )
    await _source(db, project_id, team_id, SourceType.KICAD, "Main board", SourceStatus.ERROR)
    for section, subsection, words in (
        (SolusSection.GOALS, "reach", "reach the top shelf"),
        (SolusSection.GOALS, None, "stay quiet at night"),
        (SolusSection.CONSTRAINTS, "rules", "no exposed 24 V"),
    ):
        await add_text_entry(
            db, project_id, section, words, author="user", created_by=None, subsection=subsection
        )
    budgets = Budgets(
        computed_at=datetime.now(UTC),
        budgets=[
            BudgetLine(name="cost", current=12, limit=100, unit="USD", source="bom", status="ok"),
            BudgetLine(
                name="mass", current=2.5, limit=2, unit="kg", source="cad", status="exceeded"
            ),
            BudgetLine(name="power:+5V", unit="A", source="netlist", status="unknown"),
        ],
    )
    await put_config_entry(
        db,
        project_id,
        SolusSection.CONSTRAINTS,
        "budgets",
        budgets,
        text="Budgets",
        configured_entity_id=None,
        created_by=None,
        author="system",
    )
    await db.commit()
    registry = build_registry(settings)
    capabilities = {row["type"]: tuple(row["capabilities"]) for row in registry.catalog()}

    card = await build_project_card(db, project_id, catalog=registry.catalog())
    inputs = await _inputs(
        db,
        project_id,
        uuid.uuid4(),
        cache=ProjectCardCache(InMemoryCacheStore()),
        connectors=registry,
    )

    assert card.name == "Rover"
    assert card.robots == (
        CardRobot(entity_id=arm.id, name="Arm A", external_ref="dev-1", host_machine_id="host-a"),
        CardRobot(entity_id=spare.id, name="Arm B", external_ref=None, host_machine_id=None),
    )
    assert card.sources == (
        CardSource(type="github", name="Rover firmware", capabilities=capabilities["github"]),
        CardSource(type="kicad", name="Main board", capabilities=capabilities["kicad"]),
    )
    assert card.solus == {"goals": 2, "constraints": 2}
    assert card.subsections == {
        "goals": {"general": 1, "reach": 1},
        "constraints": {"budgets": 1, "rules": 1},
    }
    assert ProjectCard.model_validate_json(card.model_dump_json()) == card  # what the cache holds
    # The budgets line is read per request, worst status first.
    assert inputs.budgets == (
        "mass 2.5/2 kg (exceeded); power:+5V ?/? A (unknown); cost 12/100 USD (ok)"
    )

    text = render_card(
        card,
        findings=inputs.findings,
        machine=inputs.machine,
        active_device_ids=frozenset({"dev-1"}),
        budgets=inputs.budgets,
    )
    assert text.splitlines()[0] == "project: Rover"
    for fact in (
        f"Arm A [bench session active] (id {arm.id}, ref dev-1, host host-a)",
        f"Arm B (id {spare.id})",
        'github "Rover firmware" [' + ", ".join(capabilities["github"]) + "]",
        'kicad "Main board" [' + ", ".join(capabilities["kicad"]) + "]",
        ".solus: goals 2 (general 1, reach 1); constraints 2 (budgets 1, rules 1)",
        f"budgets: {inputs.budgets}",
        "open findings: none",
    ):
        assert fact in text, fact
    assert "Not ours" not in text and "Scrapped" not in text
    assert "connected" not in text  # a source's status is the sources tools', not the card's

    # One section, in layer 2, fenced as DATA: nothing of it sits outside the fence.
    card_section = ContextSection(
        kind="project_card", text=text, tokens=estimate_tokens(text, config=_ESTIMATOR), score=1.0
    )
    bare = Context(query="q", project_id=project_id, sections=())
    context = bare.with_card(card_section)
    assert bare.with_card(None) == bare
    assert context.sections == (card_section,)
    assert context.layers.project_card.sections == (card_section,)
    assert context.layers.project_card.empty_reason is None
    nonce = prompt.new_nonce()
    prefix = context.fenced_prefix(nonce)
    fenced = prompt.data_block(nonce, "context_project_card", {"text": text, "citation": None})
    assert "## Layer 2/11 — project_card" in prefix and fenced in prefix
    assert "Rover firmware" not in prefix.replace(fenced, "")


def _wide_card(
    *, robots: int = 1, sources: int = 1, capabilities: int = 3, goals: int = 0
) -> ProjectCard:
    return ProjectCard(
        name="Rover " + "x" * 200,
        robots=tuple(
            CardRobot(
                entity_id=uuid.UUID(int=i + 1),
                name=f"robot {i:02d} " + "r" * 60,
                external_ref=f"dev-{i}",
                host_machine_id=None,
            )
            for i in range(robots)
        ),
        sources=tuple(
            CardSource(
                type="code",
                name=f"source {i:02d}",
                capabilities=tuple(f"cap_{c:02d}" for c in range(capabilities)),
            )
            for i in range(sources)
        ),
        solus={"goals": goals} if goals else {},
        subsections={"goals": {f"goal-{i:03d}": 1 for i in range(goals)}} if goals else {},
    )


def test_card_under_token_cap() -> None:
    def render(
        card: ProjectCard,
        machine: MachineBlock | None = None,
        active: frozenset[str] = frozenset(),
    ) -> str:
        text = render_card(
            card,
            findings={"warning": 2},
            machine=machine,
            active_device_ids=active,
            budgets="no budgets",
        )
        assert estimate_tokens(text, config=_ESTIMATOR) <= CARD_MAX_TOKENS
        return text

    roomy = render(_wide_card(goals=3))
    assert "goal-000 1" in roomy and "cap_00" in roomy  # a card that fits keeps every detail
    assert "x" * 80 not in roomy  # and every name is still capped at 80

    # 1. `.solus` subsection detail goes first,
    many_goals = render(_wide_card(goals=120))
    assert "goal-000" not in many_goals and "goals 120" in many_goals
    assert "cap_00" in many_goals

    # 2. then source capabilities,
    many_sources = render(_wide_card(sources=12, capabilities=12, goals=120))
    assert "cap_00" not in many_sources and "goal-000" not in many_sources
    assert "source 11" in many_sources and "robot 00" in many_sources

    # 3. then every robot and every source but the first — an active robot sorts first.
    many_robots = render(
        _wide_card(robots=20, sources=12, capabilities=12), active=frozenset({"dev-7"})
    )
    assert "robots (20): robot 07" in many_robots and "+19 more" in many_robots
    assert "robot 00" not in many_robots
    assert 'sources (12): code "source 00"; +11 more' in many_robots

    # A list read at its row limit is a lower bound, not a count.
    assert "robots (50+): " in render(_wide_card(robots=50))

    # Every rendered string is redacted and capped: kinds, capabilities, section names,
    # severities and the budgets line too, not only the names.
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2
    hostile = ProjectCard(
        name="Rover",
        robots=(),
        sources=(CardSource(type="t" * 300, name=token, capabilities=("k" * 300,)),),
        solus={"s" * 300: 1},
        subsections={"s" * 300: {"u" * 300: 1}},
    )
    loud = render_card(
        hostile,
        findings={"v" * 300: 1},
        machine=None,
        active_device_ids=frozenset(),
        budgets="b" * 300,
    )
    for run, cap in (("t", 80), ("k", 80), ("s", 80), ("u", 80), ("v", 80), ("b", 120)):
        assert run * cap not in loud, run
    assert token not in loud and "[REDACTED]" in loud

    # Past all three the card is clipped; the newest command comes first, so the oldest goes.
    noisy = MachineBlock(
        hostname="bench-01",
        os="linux",
        arch="arm64",
        tool_versions=(("git", "2.45.0"),),
        recent_commands=tuple(
            {
                "command_redacted": f"command-{i} " + "c" * 180,
                "cwd": "/work/" + "d" * 190,
                "output_tail": "t" * 199,
            }
            for i in (4, 3, 2, 1, 0)
        ),
    )
    clipped = render(_wide_card(), noisy)
    assert clipped.endswith("…") and "bench-01 (linux/arm64)" in clipped
    assert "command-4" in clipped and "command-0" not in clipped


async def test_finding_counts_and_machine_block_are_per_request(
    engine: AsyncEngine, db: AsyncSession, settings: Settings
) -> None:
    """Two turns of one conversation, through the real runner, read ONE cached card: a rename
    between them is not seen. Between them, and with no `graph.changed`, findings are raised,
    the budgets writer rewrites the budgets line, the bench session ends and the caller's
    machine comes online — and each turn's prefix carries its own."""
    ctx = await _ctx(engine, "why does the arm stall?")
    assert ctx.user_id is not None
    project_id, team_id = await _project(db)
    arm = await _robot(db, project_id, "Arm A", external_ref="dev-1")
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            name="frame",
            attrs={"mass_kg": 1.0},
        )
    )
    await db.commit()
    await store_budgets(db, project_id)  # the budgets writer: 1 kg, no limit yet
    await db.commit()
    elsewhere, _ = await _project(db, name="Elsewhere")
    stranger = await _robot(db, elsewhere, "Not ours")
    await _finding(db, elsewhere, stranger.id, Severity.CRITICAL, "foreign_rule")
    store = InMemoryCacheStore()
    cache = ProjectCardCache(store)
    connectors = build_registry(settings)
    bench, _ = _manager(project_id)
    conn = FakeConn()
    bench_session = await _start(bench, project_id, conn)
    await conn.drive(_packet("dev-1", 0.0, v=1.0))

    first = await _inputs(
        db, project_id, ctx.user_id, cache=cache, connectors=connectors, sessions=bench
    )
    assert first.findings == {} and first.machine is None
    assert first.active_device_ids == frozenset({"dev-1"})
    assert "mass 1/? kg (unknown)" in first.budgets
    turn = dataclasses.replace(
        ctx, project_id=project_id, conversation_id=_CONVERSATION, project_card=first
    )
    model = _ScriptedModel()
    events = await _run(model, turn)

    await _finding(db, project_id, arm.id, Severity.CRITICAL, "stall")
    for rule in ("brownout", "overheat"):
        await _finding(db, project_id, arm.id, Severity.WARNING, rule)
    dismissed = await _finding(db, project_id, arm.id, Severity.INFO, "noise")
    dismissed.attrs = {**dismissed.attrs, "status": "dismissed"}
    limit = ConstraintMeta(quantity="mass", limit=5, unit="kg", comparator="<=")
    await add_text_entry(
        db,
        project_id,
        SolusSection.CONSTRAINTS,
        "Total mass at most 5 kg",
        author="user",
        created_by=None,
        subsection="rules",
        payload=limit.model_dump(mode="json"),
    )
    await store_budgets(db, project_id)  # the writer rewrites the line; no `graph.changed`
    await bench.stop(project_id, bench_session.id)
    await upsert_machine(
        db,
        project_id,
        ctx.user_id,
        COMPANION,
        MachineIn(hostname="bench-01", os="linux", arch="arm64"),
        tool_versions={"git": "git version 2.45.0"},
    )
    await db.execute(update(Project).where(Project.id == project_id).values(name="Rover II"))
    await db.commit()

    second = await _inputs(
        db,
        project_id,
        ctx.user_id,
        cache=cache,
        connectors=connectors,
        sessions=bench,
        live=_companion_session(ctx.user_id, team_id, project_id),
    )
    assert second.findings == {"critical": 1, "warning": 2}
    assert second.machine is not None and second.machine.hostname == "bench-01"
    assert second.active_device_ids == frozenset()  # the session ended
    await _run(model, dataclasses.replace(turn, prompt="and now?", project_card=second))

    one, two = (_card_text(seen.messages[0].text or "") for seen in model.seen)
    assert "open findings: none" in one and "Arm A [bench session active]" in one
    assert "mass 1/? kg (unknown)" in one and "bench-01" not in one
    assert "open findings: critical 1, warning 2" in two
    assert "mass 1/5 kg (ok)" in two and "mass 1/? kg" not in two
    assert "bench-01 (linux/arm64)" in two and "git git version 2.45.0" in two
    assert "bench session active" not in two
    assert "project: Rover\n" in two and "Rover II" not in two  # the card came from the cache

    frame = next(e for e in events if e.type is AgentEventType.CONTEXT_USED)
    assert frame.data["sections"][0]["kind"] == "project_card"
    (layer,) = [row for row in frame.data["layers"] if row["layer"] == "project_card"]
    assert layer["sections"] == 1 and layer["empty_reason"] is None

    raw = await store.get(f"solus:project_card:{project_id}")
    assert raw is not None
    cached = json.loads(raw)
    assert set(cached) == set(ProjectCard.model_fields) and "budgets" not in cached
    for per_request in ("critical", "bench-01", "mass 1"):
        assert per_request not in raw, per_request


async def test_card_text_is_byte_identical_across_turns_with_unchanged_state(
    engine: AsyncEngine, db: AsyncSession, settings: Settings
) -> None:
    """The card is layer 2 of the stable prefix: two turns with nothing changed between them —
    every per-request input read afresh — carry the same card, byte for byte."""
    ctx = await _ctx(engine, "what is on the bench?")
    assert ctx.user_id is not None
    project_id, team_id = await _project(db)
    arm = await _robot(db, project_id, "Arm A", external_ref="dev-1", host_machine_id="host-a")
    await _finding(db, project_id, arm.id, Severity.WARNING, "brownout")
    machine = await upsert_machine(
        db,
        project_id,
        ctx.user_id,
        COMPANION,
        MachineIn(hostname="bench-01", os="linux", arch="arm64"),
        tool_versions={"git": "git version 2.45.0"},
    )
    machine.attrs = {
        **machine.attrs,
        "recent_commands": [{"command_redacted": "make flash", "cwd": "/home/a", "exit_code": 0}],
    }
    await db.commit()
    bench, _ = _manager(project_id)
    conn = FakeConn()
    await _start(bench, project_id, conn)
    await conn.drive(_packet("dev-1", 0.0, v=1.0))
    cache = ProjectCardCache(InMemoryCacheStore())
    connectors = build_registry(settings)
    live = _companion_session(ctx.user_id, team_id, project_id)
    model = _ScriptedModel()

    for message in ("what is on the bench?", "and the arm?"):
        inputs = await _inputs(
            db,
            project_id,
            ctx.user_id,
            cache=cache,
            connectors=connectors,
            sessions=bench,
            live=live,
        )
        turn = dataclasses.replace(
            ctx,
            prompt=message,
            project_id=project_id,
            conversation_id=_CONVERSATION,
            project_card=inputs,
        )
        await _run(model, turn)

    one, two = (_card_text(seen.messages[0].text or "") for seen in model.seen)
    assert one == two
    for part in ("warning 1", "[bench session active]", "bench-01", "make flash"):
        assert part in one, part  # every per-request part is in the compared bytes


class _Recorder:
    """A runner that keeps the context the route built and yields nothing."""

    def __init__(self) -> None:
        self.ctx: Any = None

    async def run(self, ctx: Any) -> Any:
        self.ctx = ctx
        for _ in ():
            yield


async def test_card_never_serves_another_members_commands(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Two members of one team. Bob's machine carries his recent commands; Alice's
    companion connects claiming Bob's companion id (client-supplied: routing, never
    authority). Her turn's card has no machine at all; Bob's own turn has his."""
    alice = await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    resp = await client.put(
        f"/api/v1/projects/{project['id']}/members/me/machines/{COMPANION}",
        json={"hostname": "bob-laptop", "os": "linux", "arch": "x86_64"},
        headers=bob_headers,
    )
    assert resp.status_code == 200, resp.text
    machine = await find_machine(db, uuid.UUID(project["id"]), COMPANION)
    assert machine is not None
    machine.attrs = {
        **machine.attrs,
        "recent_commands": [
            {
                "command_redacted": "bob-flash --port /dev/ttyUSB0",
                "cwd": "/home/bob/firmware",
                "output_tail": "bob-private-tail",
            }
        ],
    }
    await db.commit()

    async def turn_card(headers: dict[str, str], user: dict[str, Any]) -> tuple[CardInputs, str]:
        app.state.bridge_sessions.bind(
            _companion_session(
                uuid.UUID(user["id"]), uuid.UUID(team["id"]), uuid.UUID(project["id"])
            )
        )
        recorder = _Recorder()
        app.state.agent_runner = recorder
        conversation = await client.post(
            f"/api/v1/projects/{project['id']}/sol/conversations",
            json={"title": "bench"},
            headers=headers,
        )
        reply = await client.post(
            f"/api/v1/projects/{project['id']}/sol/conversations/"
            f"{conversation.json()['data']['id']}/messages",
            json={"content": "what is on my bench?"},
            headers=headers,
        )
        assert reply.status_code == 200, reply.text
        inputs: CardInputs | None = recorder.ctx.project_card
        assert inputs is not None
        section = await project_card_section(
            recorder.ctx.sessionmaker, recorder.ctx.project_id, inputs
        )
        assert section is not None
        return inputs, section.text

    theirs, text = await turn_card(alice_headers, alice)
    assert theirs.machine is None
    for private in ("bob-laptop", "bob-flash", "/home/bob", "bob-private-tail"):
        assert private not in text, private

    mine, own = await turn_card(bob_headers, bob)
    assert mine.machine is not None
    assert "bob-laptop (linux/x86_64)" in own
    assert "bob-flash --port /dev/ttyUSB0" in own and "bob-private-tail" in own


async def test_recent_commands_redacted_and_capped(db: AsyncSession) -> None:
    project_id, team_id = await _project(db)
    owner = await _user(db)
    machine = await upsert_machine(
        db,
        project_id,
        owner,
        COMPANION,
        MachineIn(hostname="bench-01", os="linux", arch="arm64"),
        tool_versions={f"tool{i}": f"{i}.0" for i in range(10)},
    )
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2
    commands: list[Any] = [
        {"command_redacted": f"make flash-{i}", "cwd": "/home/a/fw", "exit_code": 0}
        for i in range(6)
    ]
    commands += [
        "not a command",
        {
            "command_redacted": f"curl -H 'Authorization: Bearer {token}' https://example.dev",
            "cwd": "/" + "deep/" * 80,
            "output_tail": "password=hunter2 " + "y" * 500,
            "exit_code": 1,
            "env": {"API_KEY": "leak-me"},
        },
    ]
    machine.attrs = {**machine.attrs, "recent_commands": commands}
    await db.commit()
    live = _companion_session(owner, team_id, project_id)

    block = await machine_block(db, project_id=project_id, user_id=owner, live=live)

    assert block is not None
    assert block.tool_versions == tuple((f"tool{i}", f"{i}.0") for i in range(8))
    # The last five commands, newest first; the junk entry is skipped, unknown keys ignored.
    newest, *older = block.recent_commands
    assert [c["command_redacted"] for c in older] == [f"make flash-{i}" for i in (5, 4, 3, 2)]
    assert set(newest) == {"command_redacted", "cwd", "output_tail", "exit_code"}
    assert newest["exit_code"] == "1"
    dumped = block.model_dump_json()
    for secret in (token, "hunter2", "leak-me", "Bearer"):
        assert secret not in dumped, secret
    assert "[REDACTED]" in newest["command_redacted"]
    assert newest["output_tail"].startswith("password=[REDACTED]")
    assert all(len(value) <= 200 for command in block.recent_commands for value in command.values())
    assert newest["cwd"].endswith("…") and newest["output_tail"].endswith("…")
    # A live session in another project is not this project's machine, whatever it claims.
    assert await machine_block(db, project_id=uuid.uuid4(), user_id=owner, live=live) is None

    text = render_card(
        ProjectCard(name="Rover", robots=(), sources=(), solus={}, subsections={}),
        findings={},
        machine=block,
        active_device_ids=frozenset(),
        budgets="no budgets",
    )
    assert "make flash-5" in text and token not in text and "hunter2" not in text
    assert estimate_tokens(text, config=_ESTIMATOR) <= CARD_MAX_TOKENS


def test_owns_machine_is_the_one_owner_comparison() -> None:
    owner = uuid.uuid4()
    attrs = {"owner_user_id": str(owner)}
    assert owns_machine(attrs, owner) is True
    assert owns_machine(attrs, uuid.uuid4()) is False
    assert owns_machine(attrs, None) is False
    assert owns_machine({}, owner) is False  # a machine with no recorded owner is nobody's
    assert owns_machine({"owner_user_id": "None"}, None) is False  # str(None) is not an owner


def test_owned_commands_are_the_owners_alone_newest_first_and_capped() -> None:
    owner, teammate = uuid.uuid4(), uuid.uuid4()
    commands: list[Any] = [
        {"command_redacted": f"make {n}", "cwd": "/w", "exit_code": n} for n in range(7)
    ]
    attrs = {"owner_user_id": str(owner), "recent_commands": [*commands, "junk"]}
    assert owned_commands(attrs, owner, limit=3) == (
        {"command_redacted": "make 6", "cwd": "/w", "exit_code": "6"},
        {"command_redacted": "make 5", "cwd": "/w", "exit_code": "5"},
        {"command_redacted": "make 4", "cwd": "/w", "exit_code": "4"},
    )
    assert owned_commands(attrs, teammate, limit=3) == ()
    assert owned_commands(attrs, None, limit=3) == ()
    assert owned_commands({"recent_commands": commands}, owner, limit=3) == ()  # nobody's machine
    assert owned_commands({**attrs, "recent_commands": "nope"}, owner, limit=3) == ()


def test_tool_versions_are_sorted_capped_and_stringified() -> None:
    attrs = {"tool_versions": {"python3": "Python 3.12.3", "git": "git 2.45", "node": 22}}
    assert tool_versions(attrs, limit=2) == (("git", "git 2.45"), ("node", "22"))
    assert tool_versions({"tool_versions": ["not", "a", "dict"]}, limit=2) == ()
    assert tool_versions({}, limit=2) == ()


async def test_cache_invalidated_through_fanout(
    engine: AsyncEngine, db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fan-out both processes install drops the project's cached card on a published
    `graph.changed` — that project's only — and still queues the budgets recompute."""
    monkeypatch.setattr("solus_api.services.budgets.DEBOUNCE_SECONDS", 0.0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryCacheStore()
    enqueued: list[tuple[str, str]] = []

    async def enqueue(job: str, project: str) -> None:
        enqueued.append((job, project))

    fanout = GraphChangedFanout(
        graph_changed_callbacks(sessionmaker=maker, enqueue=enqueue, store=store)
    )
    hub = LiveHub(None)
    hub.on_graph_changed = fanout
    cache = ProjectCardCache(store)  # the app's own instance, over the same store
    project_id, _ = await _project(db)
    other_id, _ = await _project(db, name="Elsewhere")
    inputs = CardInputs(
        cache=cache,
        connectors=build_registry(settings),
        findings={},
        machine=None,
        active_device_ids=frozenset(),
        budgets="no budgets",
    )

    async def card_text(project: uuid.UUID) -> str:
        section = await project_card_section(maker, project, inputs)
        assert section is not None
        return section.text

    assert "project: Rover" in await card_text(project_id)
    assert "project: Elsewhere" in await card_text(other_id)
    await db.execute(update(Project).where(Project.id == project_id).values(name="Rover II"))
    await db.commit()
    assert "Rover II" not in await card_text(project_id)  # served from the cache

    await hub.publish(
        project_id,
        graph_changed_frame(
            project_id=project_id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_created=1),
            at="now",
        ),
    )
    await asyncio.sleep(0.05)
    fanout.close()

    assert await cache.get(project_id) is None
    assert await cache.get(other_id) is not None  # only the changed project's card goes
    assert enqueued == [("recompute_budgets", str(project_id))]  # the trigger fired too
    assert "project: Rover II" in await card_text(project_id)


async def test_corrupt_cache_value_is_a_miss(
    engine: AsyncEngine, db: AsyncSession, settings: Settings
) -> None:
    """A garbage or wrong-shape value under the key is a miss: the card is rebuilt and put."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, _ = await _project(db)
    store = InMemoryCacheStore()
    cache = ProjectCardCache(store)
    key = f"solus:project_card:{project_id}"
    inputs = CardInputs(
        cache=cache,
        connectors=build_registry(settings),
        findings={},
        machine=None,
        active_device_ids=frozenset(),
        budgets="no budgets",
    )

    for garbage in ("{not json", json.dumps({"name": "Rover", "robots": "wrong shape"})):
        await store.set(key, garbage, 600)
        assert await cache.get(project_id) is None
        section = await project_card_section(maker, project_id, inputs)
        assert section is not None and section.text.startswith("project: Rover\n")
        raw = await store.get(key)
        assert raw is not None and ProjectCard.model_validate_json(raw).name == "Rover"


class _BrokenCatalog(ConnectorRegistry):
    def catalog(self) -> list[dict[str, Any]]:
        raise RuntimeError("catalog unavailable")


async def test_card_failure_yields_no_card_not_an_error(
    engine: AsyncEngine, db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A card that cannot be built, or a per-request read that fails, is no card this turn —
    logged with its traceback, never raised into the turn or the message."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, _ = await _project(db)
    cache = ProjectCardCache(InMemoryCacheStore())
    inputs = CardInputs(
        cache=cache,
        connectors=_BrokenCatalog(),
        findings={},
        machine=None,
        active_device_ids=frozenset(),
        budgets="no budgets",
    )
    unreachable = create_async_engine("postgresql+asyncpg://solus:solus@127.0.0.1:1/none")
    try:
        with caplog.at_level(logging.ERROR, logger=_LOGGER):
            assert await project_card_section(maker, project_id, inputs) is None
            async with async_sessionmaker(unreachable)() as broken:
                assert (
                    await card_inputs(
                        broken,
                        project_id=project_id,
                        user_id=uuid.uuid4(),
                        live=None,
                        cache=cache,
                        sessions=None,
                        connectors=_BrokenCatalog(),
                    )
                    is None
                )
    finally:
        await unreachable.dispose()

    records = [r for r in caplog.records if r.name == _LOGGER]
    assert len(records) == 2 and all(r.exc_info is not None for r in records)
