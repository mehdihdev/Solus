"""First-party bundle capability routes (SOLUSDEV-246, docs/api/widget-bundles.md §3).

`/api/v1/projects/{project_id}/widgets/<slug>/…` — one mount per discovered
capability that exports a router, each under `require_bundle(slug)` so a
capability's handlers can only ever run for a project where the bundle is
installed, enabled and unblocked. This module defines no routes of its own.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.schemas import serialize_entity, serialize_relation
from solus_api.widgets.graph_nodes import reconcile_workspace_graph
from solus_api.widgets.guard import require_bundle
from solus_api.widgets.registry import discover_capabilities

router = APIRouter(prefix="/api/v1/projects/{project_id}/widgets")


@router.get("/graph")
async def get_workspace_graph(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """SOLUSDEV-246 ST2 (widget-bundles.md §10): the workspace layer W5 renders —
    the `solus:workspace` root, `solus:live_bench`, and one `solus:widget` per
    install, with the `contains` edges. Reconciled on every read so installs
    that predate the layer are healed and orphans pruned; reads are exempt from
    the member floor like every other project read."""
    graph = await reconcile_workspace_graph(session, ctx.project.id, ctx.team.id)
    await session.commit()
    return envelope(
        {
            "root": serialize_entity(graph.root),
            "live_bench": serialize_entity(graph.live_bench),
            "widgets": [serialize_entity(w) for w in graph.widgets],
            "edges": [serialize_relation(e) for e in graph.edges],
        }
    )


# `graph` is reserved (registry.collect_capabilities), so a capability can never
# shadow the route above.
for _capability in discover_capabilities().values():
    if _capability.router is not None:
        router.include_router(
            _capability.router,
            prefix=f"/{_capability.id}",
            dependencies=[Depends(require_bundle(_capability.id))],
        )

__all__ = ["router"]
