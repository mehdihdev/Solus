"""Authenticated creation of the reviewed graph-only SO101 template."""

from typing import Any

from fastapi import APIRouter, Request, Response

from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, RequireVerified, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.models import Role, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.simulation_models import SimulationModelService, TemplateCreate

router = APIRouter(prefix="/api/v1/projects/{project_id}")


@router.post("/simulation-models", status_code=201)
async def create_simulation_model(
    body: TemplateCreate,
    request: Request,
    response: Response,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    root, model, created = await SimulationModelService(session).create(ctx.project.id)
    if created:
        emit_event(
            session,
            user=ctx.user,
            event_type="simulation.model_created",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload={"entity_id": str(root.id), "template": body.template},
        )
    await session.commit()
    if created:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(entities_created=17, relations_created=30),
                at=utcnow().isoformat(),
            ),
        )
    response.status_code = 201 if created else 200
    return envelope(
        {"model": serialize_entity(root), "bindings": model.model_dump(), "created": created}
    )
