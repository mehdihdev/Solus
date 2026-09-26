"""Widget lifecycle invalidation; callers publish only after their transaction commits."""

import uuid

from fastapi import Request

from solus_api.graph.live import graph_changed_frame
from solus_api.models import utcnow
from solus_api.services.physical_robots import GraphChangeCounts


async def publish_widget_graph_changed(request: Request, project_id: uuid.UUID) -> None:
    """A project-only invalidation, with no invented counts or extension content."""
    await request.app.state.graph_hub.publish(
        project_id,
        graph_changed_frame(
            project_id=project_id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(),
            at=utcnow().isoformat(),
        ),
    )
