"""Graph-evidenced static CAD import through SOL's existing approval gate."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool
from solus_api.livebench.scene.cad_import import (
    IMPORT_KIND,
    STATIC_REASON,
    propose,
    selection,
    status,
)
from solus_api.livebench.scene.cad_refresh import source_options
from solus_api.livebench.scene.schemas import CadImport
from solus_api.livebench.scene.service import SceneService
from solus_api.models import GraphEntity


class CadImportTool(InProcessTool):
    requires_complete_preview = True


@dataclass
class SceneOperations:
    service: SceneService
    enqueue: Callable[[GraphEntity], Awaitable[UUID]]

    async def sources(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"sources": await source_options(self.service, include_assemblies=True)}

    async def read_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return status(await self.service.entity(UUID(args["import_id"]), IMPORT_KIND))

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        body = CadImport.model_validate(args)
        robot = await self.service.entity(body.robot_id, "physical_robot")
        root, leaves = await selection(self.service, body.source_entity_id, body.expected_revision)
        return [
            {"label": "Robot", "before": None, "after": robot.name},
            {"label": "CAD source", "before": None, "after": root.name},
            {"label": "Source revision", "before": None, "after": body.expected_revision},
            {
                "label": "Geometry",
                "before": None,
                "after": f"{len(leaves)} measured CAD occurrences. {STATIC_REASON}",
            },
        ]

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        body = CadImport.model_validate(args)
        row = await propose(
            self.service, body.robot_id, body.source_entity_id, body.expected_revision
        )
        if row.attrs.get("job_id") is None:
            job_id = await self.enqueue(row)
            await self.service.session.refresh(row)
            row.attrs = {**row.attrs, "job_id": str(job_id)}
            await self.service.session.commit()
        return status(row)


def scene_descriptors() -> list[ToolDescriptor]:
    return [
        ToolDescriptor(
            name="bench.list_cad_sources",
            description="List scoped synced CAD scene sources and exact observed revisions.",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            returns={"type": "object"},
        ),
        ToolDescriptor(
            name="bench.import_cad_scene",
            description=(
                "Import measured CAD geometry as a static Bench model. "
                "Does not infer joints or start robot motion."
            ),
            params=CadImport.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary=(
                "Import the reviewed graph CAD source into the Bench scene as static geometry."
            ),
        ),
        ToolDescriptor(
            name="bench.cad_import_status",
            description="Read progress and resulting model identity for a CAD scene import.",
            params={
                "type": "object",
                "properties": {"import_id": {"type": "string", "format": "uuid"}},
                "required": ["import_id"],
                "additionalProperties": False,
            },
            returns={"type": "object"},
        ),
    ]


def build_bench_scene_tools(
    session_factory: "async_sessionmaker[AsyncSession]",
    project_id: UUID,
    user_id: UUID,
    enqueue: "Callable[[AsyncSession, GraphEntity], Awaitable[UUID]]",
) -> list[InProcessTool]:
    """Metadata is pure; preview/invoke each acquire their own short-lived session."""

    def bind(descriptor: ToolDescriptor) -> InProcessTool:
        async def invoke(args: dict[str, Any]) -> dict[str, Any]:
            async with session_factory() as session:
                operations = scoped(session)
                handler = {
                    "bench.list_cad_sources": operations.sources,
                    "bench.import_cad_scene": operations.execute,
                    "bench.cad_import_status": operations.read_status,
                }[descriptor.name]
                return await handler(args)

        async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
            async with session_factory() as session:
                return await scoped(session).preview(args)

        if descriptor.requires_confirmation:
            return CadImportTool(descriptor, invoke, preview)
        return InProcessTool(descriptor, invoke)

    def scoped(session: AsyncSession) -> SceneOperations:
        async def queue(row: GraphEntity) -> UUID:
            return await enqueue(session, row)

        return SceneOperations(SceneService(session, project_id, user_id), queue)

    return [bind(descriptor) for descriptor in scene_descriptors()]
