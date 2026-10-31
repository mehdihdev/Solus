"""SOLUSDEV-321 P5 (R104, D7) — who draws a view of an entity, chosen by what the entity HAS.

- A scene model wins: the entity is one, the robot one names (`attrs.robot_id`), a part one binds,
  or a part its robot `contains`. The livebench member's offscreen renderer draws it, reached
  through the optional runtime import (`livebench/sessions.py:load_local`'s pattern): the engine's
  renderer is called there, never in this package.
- Else the entity's source, when its connector declares `Capability.RENDER` (`providers_of`, never
  a name). A connector naming companion `render_tools` has the person's own live companion run the
  flagged export, which uploads the file as that call's one artifact; `consume_tool_image` reads
  it once (R124), and a PDF's first page is rasterised by `render_pages` (D9). Any other connector
  draws through its own `render_view` entry, under its own cache, meter and refusals.
- Else nothing draws it: empty beats invented.

Every picture passes `checked_image` (R102) before it leaves. Whatever stops a picture is a
`RenderRefusedError` whose message says why.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from solus_contracts.relations import RelationType
from sqlalchemy import String, cast, or_, select

from solus_api.agent.documents.pdf import DocumentError, render_pages
from solus_api.agent.interfaces import EntityRead
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.vision import body_key
from solus_api.agent.vision.render_annotate import MAX_LABELS, Box
from solus_api.bridge.service import (
    MAX_TOOL_IMAGE_BYTES,
    PDF_MEDIA_TYPE,
    ImageRefusedError,
    checked_image,
    consume_tool_image,
    dispatch,
)
from solus_api.connectors.contracts import Capability, ConnectorError
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.neighborhood import load_neighborhood, to_graph_context
from solus_api.graph.read_scope import GraphReadScope, current_scope
from solus_api.livebench.scene.service import digest
from solus_api.models import AccountConnection, GraphEdge, GraphEntity, Source
from solus_api.services.artifacts import fetch_artifact_bytes
from solus_api.simulation.sim_capability import SimulationFailedError, SimulationRefusedError

if TYPE_CHECKING:
    from types import ModuleType

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.tools.shapes import ToolResult
    from solus_api.bridge.registry import BridgeSession, BridgeSessionRegistry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.storage import ArtifactStore

SCENE: Final = "scene"
PICTURE_WIDTH: Final = 800
PICTURE_HEIGHT: Final = 600
#: How long the person's companion may take to export a sheet or a board.
EXPORT_TIMEOUT_SECONDS: Final = 60.0
#: The most of a companion's own reason a refusal quotes.
REASON_CHARS: Final = 200
#: A joint name the offscreen renderer takes as a target; any other falls back to the name match.
_TARGET_JOINT: Final = re.compile(r"[A-Za-z0-9_\-]{1,128}")

type ViewKind = Literal["face", "bounds", "iso", "sheet", "board"]


class RenderRefusedError(Exception):
    """No picture; the message says why, in words the person can act on."""


@dataclass(frozen=True, slots=True)
class ViewSpec:
    """One view: a face (and which), a part's bounds, the isometric view, a sheet or a board."""

    kind: ViewKind
    side: str | None = None

    @property
    def view_id(self) -> str:
        return f"{self.kind}:{self.side}" if self.side else self.kind


@dataclass(frozen=True)
class RenderPlan:
    """Who draws the subject (`labelled[0]`), and from what. `revision` names what the picture is
    drawn from, for the cache's change signal; `tools` maps a view kind to the companion export
    that draws it."""

    renderer: str
    revision: str
    labelled: tuple[EntityRead, ...]
    tools: Mapping[str, str] = field(default_factory=dict)
    scene_artifact: uuid.UUID | None = None
    bindings: Mapping[str, str] = field(default_factory=dict)
    source_id: uuid.UUID | None = None

    @property
    def sheets(self) -> bool:
        """Whether this renderer draws sheets and boards rather than the model in space."""
        return bool(self.tools)


@dataclass(frozen=True, slots=True)
class Render:
    """A checked picture, and the pixel bounds of each labelled entity drawn in it."""

    png: bytes
    boxes: Mapping[uuid.UUID, Box]


@dataclass(frozen=True)
class Renderers:
    """The renderers one person may use in one project, bound by Solus code before any model sees
    anything (CLAUDE.md §7): every read is this project's, every companion call this person's."""

    sessions: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    user_id: uuid.UUID
    team_id: uuid.UUID
    secret_store: SecretStore
    artifact_store: ArtifactStore
    artifact_ttl_seconds: int
    connectors: ConnectorRegistry | None = None
    bridge: BridgeSessionRegistry | None = None
    call_cap_bytes: int = 262_144
    #: The artifact upload route's own cap: an export it could refuse is never run (R124).
    artifact_max_bytes: int | None = None

    async def plan(self, session: AsyncSession, subject: EntityRead) -> RenderPlan | None:
        """What draws `subject` (module docstring), or None when nothing does."""
        scene = await self._scene_plan(session, subject)
        return scene if scene is not None else await self._source_plan(session, subject)

    async def render(self, plan: RenderPlan, view: ViewSpec) -> Render:
        """One picture of `plan`'s subject, or `RenderRefusedError`."""
        if plan.renderer == SCENE:
            return await self._scene_picture(plan, view)
        if plan.sheets:
            tool = plan.tools.get(view.kind)
            if tool is None:
                raise RenderRefusedError(f"this source draws {' and '.join(plan.tools)} views")
            return await self._exported_picture(plan, tool)
        return await self._connector_picture(plan, view)

    async def _scene_plan(self, session: AsyncSession, subject: EntityRead) -> RenderPlan | None:
        # P5 fix 1 (M6): a graph read like any other, in the asker's scope (`render_view` binds it).
        scope = current_scope(self.project_id)
        scene = await session.scalar(
            select(GraphEntity)
            .where(
                scope.entity_predicate(),
                GraphEntity.kind == kinds.BENCH_SCENE_MODEL,
                GraphEntity.deleted_at.is_(None),
                or_(*_scene_predicates(scope, subject.id)),
            )
            .order_by(GraphEntity.id)
            .limit(1)
        )
        attrs = scene.attrs if scene is not None and isinstance(scene.attrs, dict) else {}
        artifact_id = _attr_uuid(attrs.get("artifact_id"))
        if scene is None or artifact_id is None:
            return None
        return RenderPlan(
            renderer=SCENE,
            revision=f"{SCENE}:{scene.id}:{scene.version}",
            labelled=await self._labelled(session, subject, _attr_uuid(attrs.get("robot_id"))),
            scene_artifact=artifact_id,
            bindings=_scene_bindings(attrs),
        )

    async def _labelled(
        self, session: AsyncSession, subject: EntityRead, robot_id: uuid.UUID | None
    ) -> tuple[EntityRead, ...]:
        """The subject, then the parts the scene's robot contains: what one picture labels."""
        if robot_id is None:
            return (subject,)
        hood = await load_neighborhood(
            session,
            self.project_id,
            roots=[robot_id],
            relation_types=[RelationType.CONTAINS.value],
            max_entities=MAX_LABELS + 1,
        )
        parts = [e for e in to_graph_context(hood).entities if e.id not in (robot_id, subject.id)]
        return (subject, *parts[: MAX_LABELS - 1])

    async def _source_plan(self, session: AsyncSession, subject: EntityRead) -> RenderPlan | None:
        if self.connectors is None:
            return None
        source = await session.scalar(
            select(Source)
            .join(GraphEntity, GraphEntity.source_id == Source.id)
            .where(
                GraphEntity.id == subject.id,
                GraphEntity.project_id == self.project_id,
                Source.project_id == self.project_id,
            )
        )
        if source is None or source.type.value not in self.connectors.providers_of(
            Capability.RENDER
        ):
            return None
        provider = source.type.value
        tools = getattr(self.connectors.create(provider), "render_tools", None)
        return RenderPlan(
            renderer=provider,
            revision=f"{provider}:{digest(source.cursor)}",
            labelled=(subject,),
            tools=dict(tools) if isinstance(tools, Mapping) else {},
            source_id=source.id,
        )

    async def _scene_picture(self, plan: RenderPlan, view: ViewSpec) -> Render:
        offscreen = _offscreen()
        if offscreen is None:
            raise RenderRefusedError("the scene renderer is not installed on this server")
        mjcf = await self._scene_text(plan, int(offscreen.MAX_SCENE_BYTES))
        subject = plan.labelled[0]
        joint = plan.bindings.get(str(subject.id))
        try:
            shot = await asyncio.to_thread(
                offscreen.render_scene_png,
                mjcf,
                view=view.kind,
                side=view.side,
                target_joint=joint if joint and _TARGET_JOINT.fullmatch(joint) else None,
                target_name=body_key(subject.name) or None,
                width=PICTURE_WIDTH,
                height=PICTURE_HEIGHT,
            )
        except (SimulationRefusedError, SimulationFailedError) as exc:
            raise RenderRefusedError(str(exc)) from None
        return Render(_gated(shot.png), _placed_boxes(plan, shot.bodies))

    async def _scene_text(self, plan: RenderPlan, max_bytes: int) -> str:
        """The scene model's own file, read as this person within the scene's size bound."""
        if plan.scene_artifact is None:
            raise RenderRefusedError("this scene model names no file")
        async with self.sessions() as db:
            try:
                _, raw = await fetch_artifact_bytes(
                    db,
                    self.artifact_store,
                    project_id=self.project_id,
                    artifact_id=plan.scene_artifact,
                    requester_id=self.user_id,
                    ttl_seconds=self.artifact_ttl_seconds,
                    max_bytes=max_bytes,
                )
            except APIError:
                raise RenderRefusedError("the scene model's file is gone or too large") from None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RenderRefusedError("the scene model's file is not text") from None

    async def _exported_picture(self, plan: RenderPlan, tool: str) -> Render:
        """The person's companion exports the subject's source; its one artifact is read once."""
        cap = self.artifact_max_bytes
        if cap is not None and cap < MAX_TOOL_IMAGE_BYTES:
            raise RenderRefusedError(
                f"the artifact store accepts {cap} bytes, less than an export may need"
            )
        live = self.bridge.get(self.user_id, self.team_id, self.project_id) if self.bridge else None
        if live is None:
            raise RenderRefusedError("no companion is connected to export this view")
        spec = next((s for s in live.inventory if s.descriptor.name == tool), None)
        if spec is None or not spec.returns_image:
            raise RenderRefusedError(f"the connected companion does not offer {tool}")
        source, _ = await self._loaded_source(plan.source_id)
        path = source.config.get("project_path") if isinstance(source.config, dict) else None
        if not isinstance(path, str) or not path:
            raise RenderRefusedError("this source names no project path to export")
        result = await self._export(live, tool, path)
        async with self.sessions() as db:
            image = await consume_tool_image(
                db,
                self.artifact_store,
                spec=spec,
                result=result,
                project_id=self.project_id,
                team_id=self.team_id,
                user_id=self.user_id,
                ttl_seconds=self.artifact_ttl_seconds,
            )
        if image is None:
            raise RenderRefusedError("the companion's export was not a usable picture")
        png = await _first_page(image.data) if image.media_type == PDF_MEDIA_TYPE else image.data
        return Render(_gated(png), {})

    async def _export(self, live: BridgeSession, tool: str, path: str) -> ToolResult:
        try:
            async with asyncio.timeout(EXPORT_TIMEOUT_SECONDS):
                result = await dispatch(
                    live, tool, {"project_path": path}, call_cap_bytes=self.call_cap_bytes
                )
        except (ToolException, TimeoutError):
            raise RenderRefusedError("the companion did not finish the export") from None
        value = result.value if result.ok else None
        if not isinstance(value, dict) or value.get("degraded"):
            reason = value.get("reason") if isinstance(value, dict) else None
            raise RenderRefusedError(
                str(reason)[:REASON_CHARS] if reason else "the companion could not export it"
            )
        return result

    async def _connector_picture(self, plan: RenderPlan, view: ViewSpec) -> Render:
        """The connector's own entry draws it (its cache, its meter, its refusals)."""
        if self.connectors is None:
            raise RenderRefusedError("no connector is bound to draw this source")
        draw = getattr(self.connectors.create(plan.renderer), "render_view", None)
        if draw is None:
            raise RenderRefusedError("this source's connector draws no view")
        source, account = await self._loaded_source(plan.source_id)
        try:
            png = await draw(
                registry=self.connectors,
                source=source,
                account=account,
                secret_store=self.secret_store,
                project_id=self.project_id,
                team_id=self.team_id,
                target=dict(plan.labelled[0].attrs),
                view=view.side or "iso",
                width=PICTURE_WIDTH,
                height=PICTURE_HEIGHT,
            )
        except ConnectorError as exc:
            raise RenderRefusedError(exc.message) from None
        return Render(_gated(png), {})

    async def _loaded_source(
        self, source_id: uuid.UUID | None
    ) -> tuple[Source, AccountConnection | None]:
        """The subject's source, re-read for this picture (a token rotates, a grant is revoked),
        and the account connection it is bound to, if any."""
        async with self.sessions() as db:
            source = await db.scalar(
                select(Source).where(Source.id == source_id, Source.project_id == self.project_id)
            )
            account = (
                await db.get(AccountConnection, source.connection_id)
                if source is not None and source.connection_id is not None
                else None
            )
        if source is None:
            raise RenderRefusedError("the entity's source is no longer connected")
        return source, account


def _offscreen() -> ModuleType | None:
    """The livebench member's offscreen renderer when it is installed beside the API, else None."""
    if importlib.util.find_spec("livebench") is None:
        return None
    return importlib.import_module("livebench.sim.offscreen")


def _scene_predicates(
    scope: GraphReadScope, entity_id: uuid.UUID
) -> tuple[ColumnElement[bool], ...]:
    """A scene model draws the entity when it IS the scene, the robot the scene names, a part the
    scene binds, or a part the scene's robot contains (an edge the asker's scope shows)."""
    robot = GraphEntity.attrs["robot_id"].astext
    containers = select(cast(GraphEdge.src_id, String)).where(
        scope.edge_predicate(),
        GraphEdge.dst_id == entity_id,
        GraphEdge.relation_type == RelationType.CONTAINS.value,
        GraphEdge.deleted_at.is_(None),
    )
    return (
        GraphEntity.id == entity_id,
        robot == str(entity_id),
        robot.in_(containers),
        GraphEntity.attrs["bindings"].contains([{"part_entity_id": str(entity_id)}]),
    )


def _scene_bindings(attrs: Mapping[str, Any]) -> dict[str, str]:
    """Part id → the scene joint the person bound it to."""
    rows = attrs.get("bindings")
    return {
        row["part_entity_id"]: row["joint"]
        for row in (rows if isinstance(rows, list) else ())
        if isinstance(row, dict)
        and isinstance(row.get("part_entity_id"), str)
        and isinstance(row.get("joint"), str)
    }


def _placed_boxes(plan: RenderPlan, bodies: Sequence[Any]) -> dict[uuid.UUID, Box]:
    """Each labelled entity's pixel bounds: the body its bound joint moves, else the body whose
    normalised name is its own; an entity matching neither stays unplaced."""
    by_joint = {joint: tuple(body.box) for body in bodies for joint in body.joints if joint}
    by_name = {key: tuple(body.box) for body in bodies if (key := body_key(body.name))}
    boxes: dict[uuid.UUID, Box] = {}
    for entity in plan.labelled:
        box = by_joint.get(plan.bindings.get(str(entity.id), "")) or by_name.get(
            body_key(entity.name)
        )
        if box is not None:
            boxes[entity.id] = box
    return boxes


def _attr_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _first_page(pdf: bytes) -> bytes:
    """The export's first page as a PNG, by the document reader's own rasteriser (D9)."""
    try:
        rendered = await asyncio.to_thread(render_pages, pdf, pages=[1], max_pages=1)
    except DocumentError as exc:
        raise RenderRefusedError(str(exc)) from None
    if not rendered.pages:
        raise RenderRefusedError("the export has no page to draw")
    return rendered.pages[0].png


def _gated(png: bytes) -> bytes:
    try:
        checked_image(png)
    except ImageRefusedError as exc:
        raise RenderRefusedError(f"the renderer's picture was refused: {exc}") from None
    return png
