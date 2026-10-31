"""SOLUSDEV-321 P0-T6 — `.solus` on the tree.

The standing layer carries every goal and constraint a person wrote or confirmed, and the
budgets, on every turn; the scoped layer the `errors` entries about the parts in scope, with
the machine each happened on; the findings layer the open findings on those parts; retrieval
the `.solus` entries the message matches — a row SOL filed among them, since it is a candidate
until a person confirms it. The shipped corpus is consulted only for a practice question, the
environment divergences table only for an environment question. Driven through the real
`build_context` against the real DB, with a systems double that serves the scoped graph.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.fake_systems import FakeSolSystems
from fixtures.scope_doubles import no_hits
from solus_api.agent.context import Context, build_context
from solus_api.agent.interfaces import (
    ContextBudget,
    EntityRead,
    ErrorHit,
    GraphContext,
    GraphScope,
    RagHit,
    RetrievalFilter,
)
from solus_api.agent.turn_scope import ScopeInputs, plan_scope
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import Domain, GraphEntity, Project, SolusSection, Team, User
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.enums import Complexity
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.search import search_solus
from solus_api.services.solus_config import add_text_entry, put_config_entry
from solus_api.services.solus_payloads import (
    BudgetLine,
    Budgets,
    ConstraintMeta,
    DivergenceGroup,
    DivergenceItem,
    EnvironmentDivergencesDoc,
    ErrorMeta,
    GoalMeta,
    MachineDivergences,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]
_CONFIG = load_orchestration_config()
_T0 = datetime(2026, 10, 1, tzinfo=UTC)
#: An ordinary question: no practice phrase, no environment word.
_QUESTION = "why does the servo rail brown out?"


class _ScopedGraph(FakeSolSystems):
    """The scoped graph is exactly `parts`. No error-history or document hits, so the
    retrieval layer holds only `.solus` evidence; every retrieval filter is recorded."""

    def __init__(self, *parts: GraphEntity) -> None:
        self.parts = parts
        self.filters: list[RetrievalFilter | None] = []

    async def get_graph_context(
        self, project_id: uuid.UUID, scope: GraphScope, budget: ContextBudget | None = None
    ) -> GraphContext:
        entities = [
            EntityRead(id=p.id, kind=p.kind, domain=p.domain.value, name=p.name) for p in self.parts
        ]
        return GraphContext(entities=entities, edges=[])

    async def get_error_history(
        self, query: str, k: int, filter: RetrievalFilter | None = None
    ) -> list[ErrorHit]:
        return []

    async def rag_query(
        self, text: str, k: int, filter: RetrievalFilter | None = None
    ) -> list[RagHit]:
        self.filters.append(filter)
        if filter is not None and filter.source_types == ["corpus"]:
            return await super().rag_query(text, k, filter)
        return []


async def _project(maker: Maker) -> uuid.UUID:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="Rover")
        db.add(project)
        await db.commit()
        return project.id


async def _part(db: AsyncSession, project_id: uuid.UUID, name: str) -> GraphEntity:
    part = GraphEntity(
        project_id=project_id,
        kind="component",
        domain=Domain.ELECTRICAL,
        origin="manual",
        name=name,
    )
    db.add(part)
    await db.flush()
    return part


async def _context(maker: Maker, project_id: uuid.UUID, query: str, *parts: GraphEntity) -> Context:
    return await build_context(
        _ScopedGraph(*parts),
        query,
        project_id=project_id,
        scope=GraphScope(anchor_entity_ids=[p.id for p in parts], degree=1),
        sessionmaker=maker,
    )


def _error_meta(entity_id: uuid.UUID, machine_id: uuid.UUID | None) -> dict[str, Any]:
    meta = ErrorMeta(
        entity_id=entity_id,
        machine_id=machine_id,
        dedupe_key="0" * 40,
        count=3,
        status="open",
        first_seen=_T0,
        last_seen=_T0,
    )
    return meta.model_dump(mode="json")


async def test_goals_and_constraints_in_every_manifest(engine: AsyncEngine) -> None:
    """Every goal and constraint a person wrote — and the budgets, a line per budget —
    stand in the manifest of every turn, whatever its message or anchors; the entries
    of the other sections never stand there."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part = await _part(db, project_id, "LM358")
        goal = await add_text_entry(
            db,
            project_id,
            SolusSection.GOALS,
            "Ship the arm by March",
            author="user",
            created_by=None,
        )
        rule, style = [
            await add_text_entry(
                db,
                project_id,
                SolusSection.CONSTRAINTS,
                text,
                author="user",
                created_by=None,
                subsection=subsection,
            )
            for subsection, text in (
                ("rules", "No part above 85 C"),
                ("style", "Nets in snake_case"),
            )
        ]
        for section, text in (
            (SolusSection.DOCUMENTATION, "The arm datasheet lives in the shared drive"),
            (SolusSection.ENVIRONMENT, "Builds run on Ubuntu 24.04"),
        ):
            await add_text_entry(db, project_id, section, text, author="user", created_by=None)
        lines = [
            BudgetLine(
                name="power:5v", current=1.2, limit=2, unit="A", source="graph", status="ok"
            ),
            BudgetLine(name="mass", current=0.8, unit="kg", source="graph", status="unknown"),
        ]
        budgets = await put_config_entry(
            db,
            project_id,
            SolusSection.CONSTRAINTS,
            "budgets",
            Budgets(computed_at=_T0, budgets=lines),
            text="Budgets",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await db.commit()

    standing = {
        f"[solus:goals:{goal.id}]",
        f"[solus:constraints:{rule.id}]",
        f"[solus:constraints:{style.id}]",
        f"[solus:constraints:{budgets.id}]",
    }
    for query, parts in ((_QUESTION, (part,)), ("what is I2C", ())):
        context = await _context(maker, project_id, query, *parts)
        manifest = context.manifest()
        cited = {s["citation"] for s in manifest["sections"] if s["layer"] == "solus_standing"}
        assert cited == standing, query
        (budget,) = [
            s for s in context.sections if s.citation == f"[solus:constraints:{budgets.id}]"
        ]
        assert budget.kind == "solus"
        assert budget.text == (
            "Constraints · budgets:\npower:5v 1.2/2 A (ok)\nmass 0.8 kg, no limit known (unknown)"
        )


async def test_standing_degrades_to_titles_over_1000_tokens(engine: AsyncEngine) -> None:
    """Whole while the digest costs at most 1,000 tokens; past that every entry is one title
    line — its first line, at most 80 characters — and a goal keeps its status, a quantified
    constraint its bound. A degraded entry's body stays reachable as a relevant hit."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        goal = await add_text_entry(
            db,
            project_id,
            SolusSection.GOALS,
            "Lift 2 kg at full reach\nmeasured at the wrist, arm level",
            author="user",
            created_by=None,
            payload=GoalMeta(status="met").model_dump(mode="json"),
        )
        bound = await add_text_entry(
            db,
            project_id,
            SolusSection.CONSTRAINTS,
            "Servo rail current\nmeasured at the fuse",
            author="user",
            created_by=None,
            subsection="rules",
            payload=ConstraintMeta(
                quantity="current", limit=2, unit="A", comparator="<="
            ).model_dump(mode="json"),
        )
        await db.commit()
    goal_cite, bound_cite = f"[solus:goals:{goal.id}]", f"[solus:constraints:{bound.id}]"
    wrist = "wrist arm level"  # words of the goal's second line, which its title drops

    whole = await _context(maker, project_id, wrist)
    assert goal_cite not in {s.citation for s in whole.layers.retrieval.sections}  # carried
    texts = {s.citation: s.text for s in whole.layers.solus_standing.sections}
    assert texts == {
        goal_cite: "Goals · user: Lift 2 kg at full reach\nmeasured at the wrist, arm level",
        bound_cite: "Constraints · user: Servo rail current\nmeasured at the fuse",
    }

    async with maker() as db:
        for i in range(9):  # nine ~125-token goals take the digest past 1,000 tokens
            await add_text_entry(
                db,
                project_id,
                SolusSection.GOALS,
                f"goal {i}: " + "keep the arm stiff " * 25,
                author="user",
                created_by=None,
            )
        await db.commit()
    titled = await _context(maker, project_id, wrist)
    assert goal_cite in {s.citation for s in titled.layers.retrieval.sections}  # by its body
    texts = {s.citation: s.text for s in titled.layers.solus_standing.sections}
    assert texts.pop(goal_cite) == "Goals · user: Lift 2 kg at full reach [status=met]"
    assert texts.pop(bound_cite) == "Constraints · user: Servo rail current [current <= 2 A]"
    assert len(texts) == 9
    for text in texts.values():
        title = text.removeprefix("Goals · user: ").removesuffix("… [status=open]")
        assert len(title) == 80 and title.startswith("goal ")


async def test_scoped_errors_resolve_machine(engine: AsyncEngine) -> None:
    """An `errors` entry that blames a part in scope renders in the scoped layer with its
    status, its count and the machine it happened on; one that blames a part out of scope
    does not, and neither ever stands in the digest."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        user = User(supabase_user_id=uuid.uuid4().hex, email="ana@example.dev")
        db.add(user)
        await db.flush()
        part, other = await _part(db, project_id, "LM358"), await _part(db, project_id, "C1")
        machine = await upsert_machine(
            db,
            project_id,
            user.id,
            "c" * 32,
            MachineIn(hostname="bench-pc", os="linux", arch="arm64"),
        )
        here = await add_text_entry(
            db,
            project_id,
            SolusSection.ERRORS,
            "I2C NACK at 0x68",
            author="sol",
            created_by=None,
            payload=_error_meta(part.id, machine.id),
        )
        away = await add_text_entry(
            db,
            project_id,
            SolusSection.ERRORS,
            "C1 cracked under vibration",
            author="user",
            created_by=None,
            payload=_error_meta(other.id, None),
        )
        await db.commit()

    context = await _context(maker, project_id, _QUESTION, part)
    (scoped,) = context.layers.solus_scoped.sections
    assert scoped.kind == "solus_scoped" and scoped.citation == f"[solus:errors:{here.id}]"
    assert scoped.text == (
        "Error logging · sol: I2C NACK at 0x68 [status=open count=3] on bench-pc (linux/arm64)"
    )
    assert f"[solus:errors:{away.id}]" not in {s.citation for s in context.sections}
    assert context.layers.solus_standing.empty_reason == "no standing .solus entries"


async def test_divergences_only_for_environment_questions(engine: AsyncEngine) -> None:
    """The divergences table — a line per machine counting each cause, then named items,
    within 200 tokens — is retrieval evidence for an environment question, and never
    reaches another turn, even one whose word the stored document contains."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    missing = [DivergenceItem(name="opencv-python"), DivergenceItem(name="pyserial")]
    drift = [DivergenceItem(name="numpy", expected="==1.26.4", actual="2.0.1")]
    doc = EnvironmentDivergencesDoc(
        computed_at=_T0,
        spec_entry_id=None,
        machines=[
            MachineDivergences(
                machine_id=uuid.uuid4(),
                hostname="bench-pc",
                causes=[
                    DivergenceGroup(cause="missing", items=missing),
                    DivergenceGroup(cause="version_drift", items=drift),
                ],
            )
        ],
    )
    async with maker() as db:
        entry = await put_config_entry(
            db,
            project_id,
            SolusSection.ENVIRONMENT,
            "divergences",
            doc,
            text="Environment divergences",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await db.commit()
    citation = f"[solus:environment:{entry.id}]"

    asked = await _context(maker, project_id, "which numpy version does the build machine have?")
    (table,) = [s for s in asked.layers.retrieval.sections if s.citation == citation]
    assert table.kind == "document" and table.tokens <= 200
    assert table.text.splitlines() == [
        "Environment divergences by machine:",
        "bench-pc: missing 2 · version_drift 1 · platform_build 0 · extra 0",
        "missing opencv-python",
        "missing pyserial",
        "version_drift numpy expected ==1.26.4 actual 2.0.1",
    ]

    # Teeth: `.solus` search finds the document for its hostname, which is no environment word.
    async with maker() as db:
        assert [hit.id for hit in await search_solus(db, project_id, "bench-pc")] == [entry.id]
    other = await _context(maker, project_id, "bench-pc")
    assert citation not in {s.citation for s in other.sections}


async def test_corpus_only_on_practice_question() -> None:
    """The shipped corpus is consulted only when the message asks for practice guidance
    (models.yaml `practice_patterns`): an ordinary question makes no corpus retrieval at
    all, and its corpus layer is honestly empty."""

    async def built(query: str) -> tuple[list[RetrievalFilter], Context]:
        systems, project_id = _ScopedGraph(), uuid.uuid4()
        plan = await plan_scope(
            ScopeInputs(message=query, tier=Complexity.STANDARD),
            search=no_hits,
            load=lambda scope, budget: systems.get_graph_context(project_id, scope, budget),
            disambiguate=None,
            config=_CONFIG,
        )
        context = await build_context(
            systems,
            query,
            project_id=project_id,
            scope=plan.scope,
            graph=plan.graph,
            budget=plan.budget,
            practice_question=plan.practice_question,
        )
        corpus = [f for f in systems.filters if f is not None and f.source_types == ["corpus"]]
        return corpus, context

    ordinary, context = await built("where should the decoupling capacitor go?")
    assert ordinary == []
    assert context.layers.corpus.empty_reason == "no corpus hits"
    practice, context = await built("what is the best practice for decoupling")
    assert len(practice) == 1 and practice[0].project_id is None
    assert context.layers.corpus.sections


async def test_sol_filed_constraint_never_reaches_standing_block(engine: AsyncEngine) -> None:
    """A constraint SOL filed is a candidate until a person confirms it: it never stands in
    the digest, and it is still retrieval evidence for a message that matches it."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        human, sol = [
            await add_text_entry(
                db,
                project_id,
                SolusSection.CONSTRAINTS,
                text,
                author=author,
                created_by=None,
                subsection="rules",
            )
            for author, text in (
                ("user", "Keep every connector keyed"),
                ("sol", "Servo rail current stays under 2 amps"),
            )
        ]
        await db.commit()

    context = await _context(maker, project_id, "servo rail current")
    standing = {s.citation for s in context.layers.solus_standing.sections}
    assert standing == {f"[solus:constraints:{human.id}]"}
    retrieved = {s.citation: s for s in context.layers.retrieval.sections}
    hit = retrieved[f"[solus:constraints:{sol.id}]"]
    assert hit.kind == "document"
    assert hit.text == "Constraints · sol: Servo rail current stays under 2 amps"


async def test_open_finding_on_scoped_part_enters_context_and_routes_hard(
    engine: AsyncEngine,
) -> None:
    """An open finding observing a part in scope renders in the findings layer — headline,
    severity, rule, the scoped subjects it names and one evidence line — and marks the turn
    `finding_in_scope` unless it is only info (P0-T7 F1: advisory, it renders but routes
    nothing); a finding only on parts out of scope does neither."""
    # The "routes hard" half — the runner reading `finding_in_scope` — is pinned by P0-T7's
    # tests/test_sol_routing.py::test_finding_in_scope_routes_hard.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part, other = await _part(db, project_id, "LM358"), await _part(db, project_id, "C1")
        shared = FindingSpec(
            rule_id="i2c.address_conflict",
            severity=Severity.CRITICAL,
            source="checker",
            headline="I2C address 0x68 is claimed twice",
            subjects=[part.id, other.id],
            evidence={"address": "0x68"},
            domain=Domain.ELECTRICAL,
        )
        hit = await raise_finding(db, project_id, shared)
        elsewhere = shared.model_copy(
            update={"rule_id": "thermal.hot", "headline": "C1 runs hot", "subjects": [other.id]}
        )
        miss = await raise_finding(db, project_id, elsewhere)
        await db.commit()

    context = await _context(maker, project_id, _QUESTION, part)
    (section,) = context.layers.findings.sections
    assert section.kind == "finding" and section.citation == f"[finding:{hit.id}]"
    manifest = {s["citation"]: s["layer"] for s in context.manifest()["sections"]}
    assert manifest[f"[finding:{hit.id}]"] == "findings"
    assert f"[finding:{miss.id}]" not in manifest
    assert section.text == (
        "I2C address 0x68 is claimed twice [severity=critical rule=i2c.address_conflict] "
        "subjects: LM358\nEvidence: {'address': '0x68'}"
    )
    assert context.finding_in_scope is True

    unscoped = await _context(maker, project_id, _QUESTION)
    assert unscoped.finding_in_scope is False
    assert unscoped.layers.findings.empty_reason == "no findings in scope"

    async with maker() as db:
        quiet = await _part(db, project_id, "R7")
        advisory = shared.model_copy(
            update={
                "rule_id": "i2c.unchecked",
                "severity": Severity.INFO,
                "headline": "Could not check R7 for an I2C address",
                "subjects": [quiet.id],
            }
        )
        note = await raise_finding(db, project_id, advisory)
        await db.commit()
    noted = await _context(maker, project_id, _QUESTION, quiet)
    assert [s.citation for s in noted.layers.findings.sections] == [f"[finding:{note.id}]"]
    assert noted.finding_in_scope is False


async def test_re_raised_finding_keeps_the_findings_section_byte_identical(
    engine: AsyncEngine,
) -> None:
    """A finding raised again with nothing new — only its count and history grow — leaves the
    findings layer, and so the prompt prefix, byte-identical."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part = await _part(db, project_id, "LM358")
        await db.commit()
    spec = FindingSpec(
        rule_id="power.rail_budget",
        severity=Severity.WARNING,
        source="checker",
        headline="The 5V rail draws 2.4 A of a 2 A budget",
        subjects=[part.id],
        evidence={"rail": "5V", "current_a": 2.4},
        domain=Domain.ELECTRICAL,
    )
    contexts = []
    for _ in range(2):
        async with maker() as db:
            await raise_finding(db, project_id, spec)
            await db.commit()
        contexts.append(await _context(maker, project_id, _QUESTION, part))
    before, after = contexts

    assert len(before.layers.findings.sections) == 1
    assert after.layers.findings.sections == before.layers.findings.sections
    assert after.fenced_prefix("0" * 16) == before.fenced_prefix("0" * 16)


async def test_findings_evidence_line_shows_the_newest_values(engine: AsyncEngine) -> None:
    """A re-raise with new evidence shows its newest values on the evidence line — never the
    merge history (`items`) the finding keeps of earlier observations."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part = await _part(db, project_id, "LM358")
        spec = FindingSpec(
            rule_id="power.rail_budget",
            severity=Severity.WARNING,
            source="checker",
            headline="The 5V rail is over budget",
            subjects=[part.id],
            evidence={"current_a": 2.4},
            domain=Domain.ELECTRICAL,
        )
        await raise_finding(db, project_id, spec)
        await raise_finding(
            db, project_id, spec.model_copy(update={"evidence": {"current_a": 3.1}})
        )
        await db.commit()

    context = await _context(maker, project_id, _QUESTION, part)
    (section,) = context.layers.findings.sections
    assert section.text.splitlines()[-1] == "Evidence: {'current_a': 3.1}"
    assert "items" not in section.text


async def test_scoped_error_never_names_another_projects_machine(engine: AsyncEngine) -> None:
    """Tenant isolation: an `errors` entry in project A whose metadata names project B's
    machine renders with no machine at all — B's hostname reaches nothing in A's context."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    mine, theirs = await _project(maker), await _project(maker)
    async with maker() as db:
        user = User(supabase_user_id=uuid.uuid4().hex, email="bo@example.dev")
        db.add(user)
        await db.flush()
        rival = await upsert_machine(
            db, theirs, user.id, "d" * 32, MachineIn(hostname="rival-rig", os="linux", arch="x86")
        )
        part = await _part(db, mine, "LM358")
        entry = await add_text_entry(
            db,
            mine,
            SolusSection.ERRORS,
            "I2C NACK at 0x68",
            author="user",
            created_by=None,
            payload=_error_meta(part.id, rival.id),
        )
        await db.commit()

    context = await _context(maker, mine, _QUESTION, part)
    (scoped,) = context.layers.solus_scoped.sections
    assert scoped.citation == f"[solus:errors:{entry.id}]"
    assert scoped.text == "Error logging · user: I2C NACK at 0x68 [status=open count=3]"
    assert "rival-rig" not in context.fenced("0" * 16)


async def test_relevant_hits_bound_to_scope_lead_retrieval(engine: AsyncEngine) -> None:
    """A `.solus` hit bound to an entity in scope — a part's datasheet note — leads the
    retrieval layer, ahead of a better-scoring hit that is not bound to the scope."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        loose, bound = [
            await add_text_entry(
                db,
                project_id,
                SolusSection.DOCUMENTATION,
                text,
                author="user",
                created_by=None,
                subsection="datasheets",
            )
            for text in ("servo rail current", "servo rail current limits of the elbow driver")
        ]
        await db.commit()
        assert bound.entity_id is not None
        node = await db.get(GraphEntity, bound.entity_id)
    assert node is not None

    context = await _context(maker, project_id, "servo rail current", node)
    hits = context.layers.retrieval.sections
    first, second = f"[solus:documentation:{bound.id}]", f"[solus:documentation:{loose.id}]"
    scores = {s.citation: s.score for s in hits}
    assert scores[first] < scores[second]  # relevance alone would rank it second
    order = [s.citation for s in hits]
    assert order.index(first) < order.index(second)


async def test_failed_solus_reads_leave_the_layers_not_loaded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing `.solus` read never fails the turn: the context still builds, the standing,
    scoped and findings layers all say ".solus not loaded", and the failure is logged with the
    project id."""

    class _Down:
        def __call__(self) -> _Down:
            return self

        async def __aenter__(self) -> AsyncSession:
            raise OSError("database unavailable")

        async def __aexit__(self, *exc: object) -> None:
            return None

    project_id = uuid.uuid4()
    with caplog.at_level("ERROR", logger="solus.agent.solus_layer"):
        context = await build_context(
            _ScopedGraph(),
            _QUESTION,
            project_id=project_id,
            scope=GraphScope(anchor_entity_ids=[], degree=1),
            sessionmaker=_Down(),  # type: ignore[arg-type]
        )
    layers = context.layers
    reasons = {
        layers.solus_standing.empty_reason,
        layers.solus_scoped.empty_reason,
        layers.findings.empty_reason,
    }
    assert reasons == {".solus not loaded"}
    assert context.finding_in_scope is False
    assert f"project_id={project_id}" in caplog.text
