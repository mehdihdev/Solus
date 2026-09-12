"""Conservative, explicitly scoped QA pruning against isolated PostgreSQL."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from solus_api.models import (
    DataEvent,
    Domain,
    GraphEdge,
    GraphEntity,
    HardwareSuggestion,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    Team,
    User,
    utcnow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SPEC = importlib.util.spec_from_file_location(
    "graph_prune_qa", Path(__file__).resolve().parents[3] / "scripts/graph-prune-qa.py"
)
assert _SPEC is not None and _SPEC.loader is not None
prune = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(prune)


async def _scope(db: AsyncSession) -> tuple[Project, User]:
    user = User(supabase_user_id=str(uuid.uuid4()), email="fixture@example.invalid")
    team = Team(name="QA fixture team")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="QA fixture project", created_by=user.id)
    db.add(project)
    await db.flush()
    return project, user


async def _node(db: AsyncSession, project: Project, user: User) -> GraphEntity:
    node = GraphEntity(
        project_id=project.id,
        kind="physical_robot",
        name="QA fixture",
        origin="manual",
        domain=Domain.PROJECT,
    )
    db.add(node)
    await db.flush()
    db.add(
        DataEvent(
            project_id=project.id,
            team_id=project.team_id,
            user_id=user.id,
            event_type="workspace.robot_created",
            payload={"entity_id": str(node.id)},
        )
    )
    await db.flush()
    return node


async def test_dry_run_apply_and_idempotency(db: AsyncSession) -> None:
    project, user = await _scope(db)
    node = await _node(db, project, user)
    suggestion = HardwareSuggestion(
        project_id=project.id,
        candidate_robot_id=node.id,
        subject_ref=f"entity:{node.id}",
        subject_kind="part",
        confidence=0.9,
        tier="high",
    )
    entry = SolusEntry(
        project_id=project.id,
        entity_id=node.id,
        created_by=user.id,
        kind=SolusEntryKind.TEXT,
        section=SolusSection.DETAILS,
    )
    db.add_all([entry, suggestion])
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}) == [node.id]
    assert node.deleted_at is None and entry.deleted_at is None
    project_id, user_id, node_id = node.project_id, user.id, node.id
    await db.rollback()
    await db.refresh(node)
    await db.refresh(entry)
    await db.commit()
    assert await prune.prune_project(db, project_id, {user_id}, apply=True) == [node_id]
    await db.commit()
    await db.refresh(node)
    await db.refresh(entry)
    assert (
        await db.scalar(select(GraphEntity.deleted_at).where(GraphEntity.id == node_id)) is not None
    )
    assert (
        await db.scalar(select(SolusEntry.deleted_at).where(SolusEntry.id == entry.id)) is not None
    )
    assert await db.scalar(select(HardwareSuggestion.id)) is None
    assert await db.scalar(select(DataEvent.id)) is not None
    assert await prune.prune_project(db, project_id, {user_id}, apply=True) == []


@pytest.mark.parametrize(
    "guard",
    [
        "unknown_creator",
        "wrong_creator",
        "contradictory_creator",
        "wrong_team",
        "connector",
        "source_connector",
        "system",
        "solus_config",
        "solus_section",
        "canonical_part",
        "solus:widget",
        "name",
        "live_edge",
        "cross_project_edge",
        "canonical_ref",
        "real_config_subject",
        "external_config",
        "legacy_config",
        "artifact",
        "deleted",
    ],
)
async def test_protected_candidates_are_skipped(db: AsyncSession, guard: str) -> None:
    project, user = await _scope(db)
    node = await _node(db, project, user)
    event = await db.scalar(select(DataEvent))
    assert event is not None
    if guard == "unknown_creator":
        event.event_type = "workspace.robot_renamed"
    elif guard == "wrong_creator":
        event.user_id = uuid.uuid4()
    elif guard == "contradictory_creator":
        db.add(
            DataEvent(
                project_id=project.id,
                team_id=project.team_id,
                user_id=uuid.uuid4(),
                event_type=event.event_type,
                payload=event.payload,
            )
        )
    elif guard == "wrong_team":
        event.team_id = uuid.uuid4()
    elif guard in {"connector", "system"}:
        node.origin = guard
    elif guard == "source_connector":
        node.source_connector = "onshape"
    elif guard in {"solus_config", "solus_section", "canonical_part", "solus:widget"}:
        node.kind = guard
    elif guard == "name":
        node.name = "Contest controller"
    elif guard == "deleted":
        node.deleted_at = utcnow()
    else:
        await _add_reference(db, project, user, node, guard)
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}, apply=True) == []


async def _add_reference(
    db: AsyncSession, project: Project, user: User, node: GraphEntity, guard: str
) -> None:
    other_project, other_user = await _scope(db)
    other = await _node(db, other_project, other_user)
    if guard in {"live_edge", "cross_project_edge"}:
        db.add(
            GraphEdge(
                project_id=project.id if guard == "live_edge" else other_project.id,
                src_id=node.id,
                dst_id=other.id,
                relation_type="binds",
                domain_pair="project<->project",
                origin="manual",
            )
        )
    elif guard == "canonical_ref":
        other.canonical_part_id = node.id
    else:
        db.add(
            SolusEntry(
                project_id=project.id,
                created_by=user.id,
                section=SolusSection.HARDWARE,
                kind=SolusEntryKind.ARTIFACT if guard == "artifact" else SolusEntryKind.CONFIG,
                entity_id=other.id if guard in {"external_config", "legacy_config"} else node.id,
                configured_entity_id=(other.id if guard == "real_config_subject" else node.id)
                if guard not in {"legacy_config", "artifact"}
                else None,
                payload={"robot_entity_id": str(node.id)} if guard == "legacy_config" else None,
            )
        )


async def test_project_scope_and_entry_only_attribution(db: AsyncSession) -> None:
    project, user = await _scope(db)
    other_project, other_user = await _scope(db)
    other = await _node(db, other_project, other_user)
    node = GraphEntity(
        project_id=project.id,
        name="test controller",
        kind="controller",
        domain=Domain.PROJECT,
        origin="manual",
    )
    db.add(node)
    await db.flush()
    db.add(
        SolusEntry(
            project_id=project.id,
            entity_id=node.id,
            created_by=user.id,
            kind=SolusEntryKind.TEXT,
            section=SolusSection.DETAILS,
        )
    )
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}, apply=True) == [node.id]
    assert other.deleted_at is None


async def test_requires_explicit_existing_scope(db: AsyncSession) -> None:
    with pytest.raises(ValueError, match="test user"):
        await prune.prune_project(db, uuid.uuid4(), set(), apply=True)
    with pytest.raises(ValueError, match="project"):
        await prune.prune_project(db, uuid.uuid4(), {uuid.uuid4()})


def test_cli_requires_explicit_scope_and_defaults_to_dry_run() -> None:
    parser = prune.argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(
        ["--project-id", str(uuid.uuid4()), "--test-user-id", str(uuid.uuid4())]
    )
    assert args.apply is False


async def test_empty_allowlist_is_safe_dry_run(db: AsyncSession) -> None:
    project, user = await _scope(db)
    node = await _node(db, project, user)
    await db.commit()
    assert await prune.prune_project(db, project.id, set()) == []
    assert node.deleted_at is None


@pytest.mark.parametrize("reference", ["candidate", "subject"])
async def test_foreign_suggestion_blocks_pruning(db: AsyncSession, reference: str) -> None:
    project, user = await _scope(db)
    node = await _node(db, project, user)
    foreign_project, foreign_user = await _scope(db)
    foreign_node = await _node(db, foreign_project, foreign_user)
    suggestion = HardwareSuggestion(
        project_id=foreign_project.id,
        candidate_robot_id=node.id if reference == "candidate" else foreign_node.id,
        subject_ref=f"entity:{node.id}" if reference == "subject" else "device:fixture",
        subject_kind="part",
        confidence=0.9,
        tier="high",
    )
    db.add(suggestion)
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}, apply=True) == []
    assert node.deleted_at is None
    assert await db.get(HardwareSuggestion, suggestion.id) is not None


async def test_apply_rollback_restores_every_mutation(db: AsyncSession) -> None:
    project, user = await _scope(db)
    node = await _node(db, project, user)
    entry = SolusEntry(
        project_id=project.id,
        entity_id=node.id,
        created_by=user.id,
        section=SolusSection.DETAILS,
        kind=SolusEntryKind.TEXT,
    )
    suggestion = HardwareSuggestion(
        project_id=project.id,
        candidate_robot_id=node.id,
        subject_ref="device:fixture",
        subject_kind="device",
        confidence=0.9,
        tier="high",
    )
    db.add_all([entry, suggestion])
    await db.commit()
    project_id, user_id, node_id, entry_id, suggestion_id = (
        project.id,
        user.id,
        node.id,
        entry.id,
        suggestion.id,
    )
    assert await prune.prune_project(db, project_id, {user_id}, apply=True) == [node_id]
    await db.rollback()
    assert await db.scalar(select(GraphEntity.deleted_at).where(GraphEntity.id == node_id)) is None
    assert await db.scalar(select(SolusEntry.deleted_at).where(SolusEntry.id == entry_id)) is None
    assert await db.scalar(
        select(HardwareSuggestion.id).where(HardwareSuggestion.id == suggestion_id)
    )


@pytest.mark.parametrize("changed", ["node", "entry", "event"])
async def test_apply_revalidates_cached_rows(db: AsyncSession, changed: str) -> None:
    from sqlalchemy import update

    project, user = await _scope(db)
    node = await _node(db, project, user)
    entry = SolusEntry(
        project_id=project.id,
        entity_id=node.id,
        created_by=user.id,
        section=SolusSection.DETAILS,
        kind=SolusEntryKind.TEXT,
    )
    event = await db.scalar(select(DataEvent))
    assert event is not None
    db.add(entry)
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}) == [node.id]
    await db.commit()
    # Unsynchronized SQL reproduces a cached ORM identity after another writer
    # has committed a changed name or attribution before apply revalidation.
    if changed == "node":
        await db.execute(
            update(GraphEntity)
            .where(GraphEntity.id == node.id)
            .values(name="Production controller")
            .execution_options(synchronize_session=False)
        )
    elif changed == "entry":
        await db.execute(
            update(SolusEntry)
            .where(SolusEntry.id == entry.id)
            .values(created_by=None)
            .execution_options(synchronize_session=False)
        )
    else:
        await db.execute(
            update(DataEvent)
            .where(DataEvent.id == event.id)
            .values(user_id=None)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    assert await prune.prune_project(db, project.id, {user.id}, apply=True) == []


@pytest.mark.parametrize("extra", [[], ["--test-user-id", str(uuid.uuid4())]])
def test_cli_apply_requires_stopped_writers(
    extra: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["graph-prune-qa.py", "--project-id", str(uuid.uuid4()), "--apply", *extra]
    )
    with pytest.raises(SystemExit) as stopped:
        prune.main()
    assert stopped.value.code == 2
