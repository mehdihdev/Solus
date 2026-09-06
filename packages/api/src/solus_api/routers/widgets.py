"""First-party bundle capability routes (SOLUSDEV-246, docs/api/widget-bundles.md §3).

`/api/v1/projects/{project_id}/widgets/<slug>/…` — one mount per discovered
capability that exports a router, each under `require_bundle(slug)` so a
capability's handlers can only ever run for a project where the bundle is
installed, enabled and unblocked. This module defines no routes of its own.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.extensions.ratelimit import (
    INSTALL_WRITE_MESSAGE,
    WRITE_WINDOW_SECONDS,
    install_write_exceeded,
)
from solus_api.models import Role
from solus_api.schemas import serialize_entity, serialize_relation
from solus_api.services.events import emit_event
from solus_api.widgets.graph_nodes import (
    WorkspaceGraph,
    load_workspace_graph,
    reconcile_workspace_graph,
)
from solus_api.widgets.guard import require_bundle
from solus_api.widgets.registry import discover_capabilities

router = APIRouter(prefix="/api/v1/projects/{project_id}/widgets")


def _graph_payload(graph: WorkspaceGraph) -> dict[str, Any]:
    return {
        "root": serialize_entity(graph.root) if graph.root is not None else None,
        "live_bench": (
            serialize_entity(graph.live_bench) if graph.live_bench is not None else None
        ),
        "widgets": [serialize_entity(w) for w in graph.widgets],
        "edges": [serialize_relation(e) for e in graph.edges],
    }


@router.get("/graph")
async def get_workspace_graph(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """SOLUSDEV-246 ST2 (widget-bundles.md §10): the workspace layer W5 renders —
    the `solus:workspace` root, `solus:live_bench`, and one `solus:widget` per
    install, with the `contains` edges. A pure READ (a viewer may call it; no
    row is written): the layer is built by the install lifecycle and healed by
    `POST …/graph/reconcile`. Until then `root`/`live_bench` are null."""
    return envelope(_graph_payload(await load_workspace_graph(session, ctx.project.id)))


@router.post("/graph/reconcile")
async def reconcile_workspace_graph_route(
    request: Request, ctx: ProjectCtx, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """Heal the layer from the install rows (backfill installs that predate ST2,
    refresh attrs, prune orphans). A WRITE: `member` floor and the shared
    install-write budget, like every other extension mutation."""
    require_role(ctx, Role.MEMBER)
    if install_write_exceeded(
        request.app.state, ctx.user.id, settings.extension_install_writes_per_minute_per_user
    ):
        raise APIError(
            429,
            "rate_limited",
            INSTALL_WRITE_MESSAGE,
            headers={"Retry-After": str(WRITE_WINDOW_SECONDS)},
        )
    outcome = await reconcile_workspace_graph(session, ctx.project.id, ctx.team.id)
    if outcome.changed:
        emit_event(
            session,
            user=ctx.user,
            event_type="widget_bundle.graph_reconciled",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload={
                "created": outcome.created,
                "refreshed": outcome.refreshed,
                "pruned": outcome.pruned,
            },
        )
    await session.commit()
    return envelope(
        {
            **_graph_payload(outcome.graph),
            "reconciled": {
                "created": outcome.created,
                "refreshed": outcome.refreshed,
                "pruned": outcome.pruned,
            },
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
