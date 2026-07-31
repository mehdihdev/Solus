"""Round-trip persistence for the canonical shared models (SOLUSDEV-72).

Exercises the full tenancy -> graph chain against Postgres + pgvector: embeddings
round-trip, foreign keys resolve, and the graph_entity self-reference
(canonical_part_id) links a cross-domain observation to its canonical part.
"""

from datetime import timedelta
from typing import Any

import pytest
from solus_api.models import (
    Activity,
    CreditBalance,
    CreditLedger,
    CreditTxnType,
    DataEvent,
    Domain,
    ErrorSolution,
    GraphEdge,
    GraphEntity,
    Invite,
    Job,
    JobKind,
    Membership,
    Notification,
    NotificationType,
    PlanType,
    Project,
    ProjectMembership,
    Role,
    Subscription,
    Team,
    TeamKind,
    User,
    default_limits,
    utcnow,
)
from solus_api.schemas import (
    ActivityRead,
    CreditBalanceRead,
    CreditLedgerRead,
    DataEventRead,
    ErrorSolutionRead,
    GraphEdgeRead,
    GraphEntityRead,
    InviteRead,
    JobRead,
    MembershipRead,
    NotificationRead,
    ProjectMembershipRead,
    ProjectRead,
    ReadModel,
    SubscriptionRead,
    TeamRead,
    UserRead,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

EMBEDDING_DIM = 1536


def _vec(seed: float) -> list[float]:
    """A distinctive 1536-d embedding so the round-trip is verifiable."""
    return [seed + i * 0.0001 for i in range(EMBEDDING_DIM)]


async def test_full_graph_round_trip(db: AsyncSession, engine: AsyncEngine) -> None:
    user = User(supabase_user_id="sub-roundtrip", email="rt@example.com", display_name="RT")
    team = Team(name="RT Team", kind=TeamKind.PERSONAL)
    db.add_all([user, team])
    await db.flush()

    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()

    db.add(ProjectMembership(project_id=project.id, user_id=user.id))

    # Canonical physical part + a cross-domain observation that points at it.
    canonical = GraphEntity(
        project_id=project.id,
        kind="canonical_part",
        domain=Domain.ELECTRICAL,
        name="OV9281",
        embedding=_vec(0.10),
    )
    db.add(canonical)
    await db.flush()

    observation = GraphEntity(
        project_id=project.id,
        kind="component",
        domain=Domain.MECHANICAL,
        name="CAM_v2",
        canonical_part_id=canonical.id,
        embedding=_vec(0.20),
    )
    db.add(observation)
    await db.flush()

    db.add(
        GraphEdge(
            project_id=project.id,
            src_id=observation.id,
            dst_id=canonical.id,
            relation_type="same_as",
            domain_pair="mechanical<->electrical",
            confidence=0.92,
        )
    )
    db.add(
        ErrorSolution(
            project_id=project.id,
            error_text="I2C address 0x40 conflicts with the IMU",
            solution_text="Re-strap AD0 high on the camera board",
            domain=Domain.ELECTRICAL,
            embedding=_vec(0.30),
        )
    )
    await db.commit()

    project_id, user_id, team_id = project.id, user.id, team.id
    canonical_id, observation_id = canonical.id, observation.id

    # Read back in a fresh session (empty identity map = a true database round-trip).
    async with async_sessionmaker(engine, expire_on_commit=False)() as read:
        # Spec: "reads them all back" — every inserted row is re-read and asserted.
        got_user = await read.get(User, user_id)
        assert got_user is not None
        assert got_user.supabase_user_id == "sub-roundtrip"

        got_team = await read.get(Team, team_id)
        assert got_team is not None
        assert got_team.kind is TeamKind.PERSONAL

        got_membership = await read.scalar(
            select(Membership).where(Membership.team_id == team_id, Membership.user_id == user_id)
        )
        assert got_membership is not None
        assert got_membership.role is Role.OWNER

        got_pm = await read.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
            )
        )
        assert got_pm is not None

        got_project = await read.get(Project, project_id)
        assert got_project is not None
        assert got_project.created_by == user_id  # FK resolves

        got_obs = await read.scalar(select(GraphEntity).where(GraphEntity.name == "CAM_v2"))
        assert got_obs is not None
        assert got_obs.project_id == project_id
        assert got_obs.canonical_part_id == canonical_id  # self-reference resolves
        assert got_obs.embedding is not None
        assert len(got_obs.embedding) == EMBEDDING_DIM  # vector round-trips
        assert float(got_obs.embedding[0]) == pytest.approx(0.20, abs=1e-3)

        # pgvector reads embeddings back as numpy.ndarray; assert the Read DTO
        # coerces that to list[float] on the real read path (not just embedding=None).
        obs_view = GraphEntityRead.model_validate(got_obs)
        assert isinstance(obs_view.embedding, list)
        assert len(obs_view.embedding) == EMBEDDING_DIM

        got_canonical = await read.get(GraphEntity, canonical_id)
        assert got_canonical is not None
        assert got_canonical.canonical_part_id is None
        assert got_canonical.embedding is not None
        assert len(got_canonical.embedding) == EMBEDDING_DIM
        assert float(got_canonical.embedding[0]) == pytest.approx(0.10, abs=1e-3)

        got_edge = await read.scalar(select(GraphEdge).where(GraphEdge.project_id == project_id))
        assert got_edge is not None
        assert (got_edge.src_id, got_edge.dst_id) == (observation_id, canonical_id)
        assert got_edge.relation_type == "same_as"
        assert got_edge.confidence == pytest.approx(0.92, abs=1e-4)

        got_err = await read.scalar(
            select(ErrorSolution).where(ErrorSolution.project_id == project_id)
        )
        assert got_err is not None
        assert got_err.embedding is not None
        assert len(got_err.embedding) == EMBEDDING_DIM
        assert float(got_err.embedding[0]) == pytest.approx(0.30, abs=1e-3)


async def test_credit_balance_and_ledger(db: AsyncSession) -> None:
    user = User(supabase_user_id="sub-credit", email="credit@example.com")
    db.add(user)
    await db.flush()
    db.add(CreditBalance(user_id=user.id, balance=100))
    db.add(
        CreditLedger(user_id=user.id, amount=100, type=CreditTxnType.TRIAL_GRANT, balance_after=100)
    )
    await db.commit()

    balance = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    assert balance is not None and balance.balance == 100
    entries = (await db.scalars(select(CreditLedger).where(CreditLedger.user_id == user.id))).all()
    assert len(entries) == 1
    assert entries[0].type == CreditTxnType.TRIAL_GRANT
    assert entries[0].balance_after == 100


async def test_read_schemas_validate_from_orm(db: AsyncSession) -> None:
    user = User(supabase_user_id="sub-read", email="read@example.com", display_name="Reader")
    team = Team(name="Read Team", slug="read-team", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.commit()

    user_view = UserRead.model_validate(user)
    assert user_view.supabase_user_id == "sub-read"
    assert user_view.display_name == "Reader"
    assert user_view.sol_mode.value == "guide"

    team_view = TeamRead.model_validate(team)
    assert team_view.kind is TeamKind.COLLABORATIVE
    assert team_view.slug == "read-team"


def test_plan_default_limits() -> None:
    assert default_limits(PlanType.BASIC) == {
        "max_integrations": 4,
        "max_projects": 3,
        "max_teams": 2,
        "byo_paid_tools": 0,  # MCP-05: BYO-license tools blocked on BASIC
    }
    assert default_limits(PlanType.PRO) == {
        "max_integrations": None,
        "max_projects": None,
        "max_teams": None,
        "byo_paid_tools": None,  # MCP-05: explicit null = unlimited on PRO
    }
    assert default_limits(PlanType.ENTERPRISE) == {}
    # Returned dict is a copy: mutating it must not corrupt the shared defaults.
    default_limits(PlanType.BASIC)["max_projects"] = 999
    assert default_limits(PlanType.BASIC)["max_projects"] == 3


async def test_all_read_schemas_mirror_orm(db: AsyncSession) -> None:
    """Every *Read schema validates against a real ORM row — proves field/type parity."""
    user = User(supabase_user_id="sub-all", email="all@example.com")
    team = Team(name="All Team", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="P", created_by=user.id)
    db.add(project)
    await db.flush()
    entity = GraphEntity(project_id=project.id, kind="part", domain=Domain.ELECTRICAL, name="A")
    db.add(entity)
    await db.flush()

    rows: dict[type[ReadModel], Any] = {
        UserRead: user,
        TeamRead: team,
        MembershipRead: Membership(team_id=team.id, user_id=user.id, role=Role.OWNER),
        InviteRead: Invite(
            team_id=team.id, email="i@example.com", expires_at=utcnow() + timedelta(days=7)
        ),
        ProjectRead: project,
        ProjectMembershipRead: ProjectMembership(project_id=project.id, user_id=user.id),
        SubscriptionRead: Subscription(
            user_id=user.id,
            plan=PlanType.BASIC,
            limits=default_limits(PlanType.BASIC),
        ),
        CreditBalanceRead: CreditBalance(user_id=user.id, balance=0),
        CreditLedgerRead: CreditLedger(
            user_id=user.id, amount=1, type=CreditTxnType.TRIAL_GRANT, balance_after=1
        ),
        NotificationRead: Notification(
            user_id=user.id, type=NotificationType.CREDIT_LOW, title="low"
        ),
        GraphEntityRead: entity,
        GraphEdgeRead: GraphEdge(
            project_id=project.id,
            src_id=entity.id,
            dst_id=entity.id,
            relation_type="same_as",
            domain_pair="a<->b",
        ),
        ErrorSolutionRead: ErrorSolution(project_id=project.id, error_text="e", domain=Domain.CODE),
        JobRead: Job(project_id=project.id, team_id=team.id, kind=JobKind.SYNC),
        ActivityRead: Activity(team_id=team.id, type="x"),
        DataEventRead: DataEvent(event_type="y"),
    }
    seeded = {UserRead, TeamRead, ProjectRead, GraphEntityRead}
    db.add_all([obj for cls, obj in rows.items() if cls not in seeded])
    await db.flush()

    for read_cls, obj in rows.items():
        view = read_cls.model_validate(obj)
        assert view.model_dump()["id"] == obj.id
