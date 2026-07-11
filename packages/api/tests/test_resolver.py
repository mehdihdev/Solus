"""Device/topic id → graph entity resolution (SOLUS-LNK-06).

The DB resolver runs against Postgres. The security-critical case is tenant isolation: a device
id known in project A must never resolve under project B (§7).
"""

import uuid

from solus_api.graph.resolver import DbEntityResolver, DictEntityResolver
from solus_api.models import Domain, GraphEntity, Membership, Project, Role, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def test_dict_resolver_maps_and_misses() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    resolver = DictEntityResolver({(project, "motor0"): entity})
    assert await resolver.resolve(project, "motor0") == entity
    assert await resolver.resolve(project, "ghost") is None
    assert await resolver.resolve(uuid.uuid4(), "motor0") is None  # other project → miss


async def _seed_entity(
    db: AsyncSession, name: str, external_ref: str
) -> tuple[Project, GraphEntity]:
    user = User(supabase_user_id=f"sub-{name}-{uuid.uuid4().hex[:8]}", email=f"{name}@ex.com")
    team = Team(name=name)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=name, created_by=user.id)
    db.add(project)
    await db.flush()
    entity = GraphEntity(
        project_id=project.id,
        kind="sensor",
        domain=Domain.RUNTIME,
        name=f"{name}-imu",
        external_ref=external_ref,
        attrs={},
    )
    db.add(entity)
    await db.flush()
    await db.commit()
    return project, entity


async def test_db_resolver_finds_entity_by_external_ref(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, entity = await _seed_entity(db, "resolveok", "imu-42")
    resolver = DbEntityResolver(async_sessionmaker(engine, expire_on_commit=False))
    assert await resolver.resolve(project.id, "imu-42") == entity.id


async def test_db_resolver_is_project_scoped(db: AsyncSession, engine: AsyncEngine) -> None:
    """Tenant isolation: a device id present in project A never resolves under project B."""
    await _seed_entity(db, "tenantA", "imu-shared")
    project_b, _ = await _seed_entity(db, "tenantB", "other-ref")
    resolver = DbEntityResolver(async_sessionmaker(engine, expire_on_commit=False))
    assert await resolver.resolve(project_b.id, "imu-shared") is None


async def test_db_resolver_returns_none_for_unknown_device(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, _ = await _seed_entity(db, "unknowndev", "imu-known")
    resolver = DbEntityResolver(async_sessionmaker(engine, expire_on_commit=False))
    assert await resolver.resolve(project.id, "nope") is None
