"""Default and personal graph scope cannot expose hidden branch snapshots."""

import uuid
from collections.abc import AsyncIterator

from solus_api.graph.read_scope import GraphReadScope, bind_scope, current_scope


def test_scope_is_request_bound_and_restored() -> None:
    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(project, ((base, snapshot),))
    assert current_scope(project).replacements == ()
    with bind_scope(scope):
        assert current_scope(project) == scope
        assert current_scope(uuid.uuid4()).replacements == ()
    assert current_scope(project).replacements == ()


def test_default_scope_excludes_internal_sources_in_sql() -> None:
    predicate = str(GraphReadScope(uuid.uuid4()).entity_predicate())
    assert "revision_base_source_id IS NULL" in predicate
    assert "source_id IS NULL" in predicate


async def test_stream_keeps_admitted_scope_after_request_scope_ends() -> None:
    from solus_api.graph.read_scope import scoped_stream

    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(project, ((base, snapshot),))

    async def stream() -> AsyncIterator[tuple[tuple[uuid.UUID, uuid.UUID], ...]]:
        yield current_scope(project).replacements

    with bind_scope(scope):
        frozen = scoped_stream(current_scope(project), stream())
    assert [item async for item in frozen] == [scope.replacements]
    assert current_scope(project).replacements == ()


def test_clone_edge_projection_is_read_only() -> None:
    from solus_api.models import GraphEdge

    project, base_source, snapshot_source = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    base_root, snapshot_root, local = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(
        project, ((base_source, snapshot_source),), ((base_root, snapshot_root),)
    )
    edge = GraphEdge(project_id=project, src_id=local, dst_id=base_root, relation_type="clone_of")
    projected = scope.project_edge(edge)
    assert projected.src_id == local and projected.dst_id == snapshot_root
    assert edge.dst_id == base_root
    assert scope.aliases([snapshot_root]) == [snapshot_root, base_root]


def test_shared_snapshot_keeps_each_users_selected_branch() -> None:
    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first = GraphReadScope(project, ((base, snapshot),), source_branches=((snapshot, "main"),))
    second = GraphReadScope(project, ((base, snapshot),), source_branches=((snapshot, "release"),))
    assert first.branch_for_source(snapshot) == "main"
    assert second.branch_for_source(snapshot) == "release"
    assert second.branch_for_source(base) is None
