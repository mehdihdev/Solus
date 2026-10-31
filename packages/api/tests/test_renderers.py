"""SOLUSDEV-321 P5 (R104) — `agent/vision/renderers.py`: who draws a view, by what an entity HAS.

A scene model wins: an entity that is one, the robot one names, or a part such a robot `contains`
is drawn by the livebench offscreen renderer (stubbed here, so the API suite stays hermetic; the
engine itself is proven in `livebench/tests/lb_offscreen_test.py`). Otherwise a source whose
connector declares `Capability.RENDER` draws it: KiCad through the companion's flagged PDF export,
consumed by the upload path and rasterised by `render_pages`; Onshape through its own entry. An
entity with neither has no renderer: empty beats invented.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fixtures.fake_arm import PART_NAMES, seed_fake_arm
from PIL import Image
from solus_api.agent.documents.pdf import render_pages
from solus_api.agent.interfaces import EntityRead
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.agent.vision import body_key, renderers
from solus_api.agent.vision.renderers import (
    SCENE,
    Renderers,
    RenderRefusedError,
    ViewSpec,
)
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import checked_image, ingest_result
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry, build_registry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.config import Settings
from solus_api.graph import kinds
from solus_api.graph.read_scope import bind_scope, resolve_scope
from solus_api.models import (
    Artifact,
    Domain,
    GraphEntity,
    Membership,
    Project,
    Source,
    SourceRevision,
    SourceStatus,
    SourceType,
    SourceViewSelection,
    Team,
    User,
)
from solus_api.services.artifacts import create_artifact
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SHEET = Path(__file__).parent / "fixtures" / "render_sheet.pdf"
EXPORT_TOOL = "kicad.export_schematic_pdf"
#: The fake arm's scene, as the scene model's artifact holds it (synthetic, primitive geoms only).
FAKE_ARM_SCENE = """<mujoco model="fake_arm">
  <worldbody>
    <light pos="0 0 3"/>
    <body name="base" pos="0 0 0.05">
      <geom type="box" size="0.08 0.08 0.05"/>
      <body name="servo_1_joint_1" pos="0 0 0.05">
        <joint name="joint_1" type="hinge" axis="0 0 1"/>
        <geom type="cylinder" size="0.03 0.02"/>
        <body name="servo_2_joint_2" pos="0 0 0.02">
          <joint name="joint_2" type="hinge" axis="0 1 0"/>
          <geom type="capsule" fromto="0 0 0 0 0 0.3" size="0.02"/>
        </body>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


def _drawn_png(width: int = 320, height: int = 240) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(out, format="PNG")
    return out.getvalue()


@dataclass(frozen=True)
class _BodyStub:
    name: str
    joints: tuple[str, ...]
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class _ShotStub:
    png: bytes
    width: int
    height: int
    bodies: tuple[_BodyStub, ...]


class _StubOffscreen:
    """The livebench renderer's surface, recording each picture it is asked for."""

    MAX_SCENE_BYTES = 512 * 1024

    def __init__(self, bodies: tuple[_BodyStub, ...] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.bodies = bodies or (
            _BodyStub("base", (), (100, 180, 220, 239)),
            _BodyStub("servo_1_joint_1", ("joint_1",), (140, 170, 180, 190)),
            _BodyStub("servo_2_joint_2", ("joint_2",), (150, 40, 170, 175)),
        )

    def render_scene_png(self, mjcf: str, **kwargs: Any) -> _ShotStub:
        self.calls.append({"mjcf": mjcf, **kwargs})
        return _ShotStub(_drawn_png(), 320, 240, self.bodies)


@dataclass(frozen=True)
class _RenderScope:
    maker: async_sessionmaker[AsyncSession]
    store: LocalArtifactStore
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    connectors: ConnectorRegistry


async def _render_scope(engine: AsyncEngine, tmp_path: Path) -> _RenderScope:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id=f"rn-{uuid.uuid4().hex}", email="rn@example.com")
        team = Team(name="render")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="render")
        db.add(project)
        await db.commit()
    registry = build_registry(
        Settings(supabase_jwt_secret="dummy-value-tests-only", database_url="sqlite+aiosqlite://")
    )
    store = LocalArtifactStore(str(tmp_path / "store"))
    return _RenderScope(maker, store, project.id, team.id, user.id, registry)


def _renderers(scope: _RenderScope, **overrides: Any) -> Renderers:
    kwargs: dict[str, Any] = {
        "sessions": scope.maker,
        "project_id": scope.project_id,
        "user_id": scope.user_id,
        "team_id": scope.team_id,
        "connectors": scope.connectors,
        "secret_store": InMemorySecretStore(),
        "artifact_store": scope.store,
        "artifact_ttl_seconds": 3600,
        **overrides,
    }
    return Renderers(**kwargs)


async def _entity_read(scope: _RenderScope, entity_id: uuid.UUID) -> EntityRead:
    async with scope.maker() as db:
        row = await db.get(GraphEntity, entity_id)
        assert row is not None
        return EntityRead.model_validate(row)


async def _source(scope: _RenderScope, provider: SourceType, **attrs: Any) -> Source:
    async with scope.maker() as db:
        source = Source(
            project_id=scope.project_id,
            team_id=scope.team_id,
            type=provider,
            name=provider.value,
            status=SourceStatus.CONNECTED,
            created_by=scope.user_id,
            **attrs,
        )
        db.add(source)
        await db.commit()
        return source


async def _sourced(
    scope: _RenderScope, source: Source, kind: str, name: str, **attrs: Any
) -> uuid.UUID:
    async with scope.maker() as db:
        entity = GraphEntity(
            project_id=scope.project_id,
            source_id=source.id,
            source_connector=source.type.value,
            kind=kind,
            domain=Domain.ELECTRICAL if kind == kinds.NET else Domain.MECHANICAL,
            origin="connector",
            name=name,
            attrs=attrs,
        )
        db.add(entity)
        await db.commit()
        return entity.id


async def _member(scope: _RenderScope) -> uuid.UUID:
    """A second member of the project's team."""
    async with scope.maker() as db:
        member = User(supabase_user_id=f"rn-{uuid.uuid4().hex}", email="member@example.com")
        db.add(member)
        await db.flush()
        db.add(Membership(team_id=scope.team_id, user_id=member.id))
        await db.commit()
        return member.id


async def _hidden_base_for(scope: _RenderScope, member: uuid.UUID) -> uuid.UUID:
    """A base source whose entities `member`'s own view hides: their active revision snapshot
    replaces it (the rows tests/test_search.py::test_search_runs_under_the_graph_read_scope
    builds, inline: there is no shared fixture)."""
    async with scope.maker() as db:
        base = Source(
            project_id=scope.project_id,
            team_id=scope.team_id,
            type=SourceType.GITHUB,
            name="repo",
            status=SourceStatus.CONNECTED,
            config={"repo": "acme/robot"},
        )
        db.add(base)
        await db.flush()
        snapshot = Source(
            project_id=scope.project_id,
            team_id=scope.team_id,
            type=SourceType.GITHUB,
            name="snapshot",
            status=SourceStatus.CONNECTED,
            revision_base_source_id=base.id,
        )
        db.add(snapshot)
        await db.flush()
        revision = SourceRevision(
            project_id=scope.project_id,
            base_source_id=base.id,
            materialized_source_id=snapshot.id,
            commit_id="a" * 40,
            branch="feature",
        )
        db.add(revision)
        await db.flush()
        db.add(
            SourceViewSelection(
                project_id=scope.project_id,
                user_id=member,
                base_source_id=base.id,
                active_revision_id=revision.id,
                active_branch="feature",
                status="ready",
                request_generation=uuid.uuid4(),
            )
        )
        await db.commit()
        return base.id


async def _scene_for_arm(scope: _RenderScope) -> tuple[Any, uuid.UUID]:
    """The fake arm, and a scene model of it whose bindings move servo 2 with `joint_2`."""
    async with scope.maker() as db:
        arm = await seed_fake_arm(db, scope.project_id, user_id=scope.user_id)
        artifact = await create_artifact(
            db,
            scope.store,
            project_id=scope.project_id,
            created_by=scope.user_id,
            data=FAKE_ARM_SCENE.encode(),
            media_type="application/xml",
            source_tool=None,
            tool_call_id=None,
        )
        artifact.retained = True
        scene = GraphEntity(
            project_id=scope.project_id,
            kind=kinds.BENCH_SCENE_MODEL,
            domain=Domain.SIMULATION,
            origin="manual",
            name="fake arm scene",
            attrs={
                "robot_id": str(arm.robot),
                "artifact_id": str(artifact.id),
                "model": {"joints": []},
                "bindings": [{"part_entity_id": str(arm.parts[1]), "joint": "joint_2"}],
            },
        )
        db.add(scene)
        await db.commit()
        return arm, scene.id


async def test_mujoco_offscreen_selected_for_scene_models(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    arm, scene_id = await _scene_for_arm(scope)
    # Servo 2 also came from a source whose connector declares RENDER: the scene still wins.
    kicad = await _source(scope, SourceType.KICAD, config={"project_path": "proj/a.kicad_pro"})
    async with scope.maker() as db:
        part = await db.get(GraphEntity, arm.parts[1])
        assert part is not None
        part.source_id, part.source_connector = kicad.id, "kicad"
        await db.commit()
    offscreen = _StubOffscreen()
    monkeypatch.setattr(renderers, "_offscreen", lambda: offscreen)
    drawer = _renderers(scope)
    servo_2 = await _entity_read(scope, arm.parts[1])

    async with scope.maker() as db:
        plans = [
            await drawer.plan(db, await _entity_read(scope, entity))
            for entity in (arm.parts[1], arm.robot, scene_id)
        ]
    assert all(plan is not None and plan.renderer == SCENE for plan in plans)
    plan = plans[0]
    assert plan is not None and plan.sheets is False
    assert plan.labelled[0].id == servo_2.id
    assert {entity.name for entity in plan.labelled} == set(PART_NAMES)

    render = await drawer.render(plan, ViewSpec("face", "front"))

    (call,) = offscreen.calls
    assert call["mjcf"] == FAKE_ARM_SCENE  # read from the scene model's own artifact
    assert (call["view"], call["side"], call["target_joint"]) == ("face", "front", "joint_2")
    assert checked_image(render.png)[0] == "image/png"
    # Servo 2 is placed by its binding's joint; servo 1 by its normalised name.
    assert render.boxes[arm.parts[1]] == (150, 40, 170, 175)
    assert render.boxes[arm.parts[0]] == (140, 170, 180, 190)


async def test_a_body_named_in_another_case_still_labels_its_part(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P5 fix 1 (M8): one name rule (`agent/vision.body_key`) both names the renderer's target and
    places a label, so a body named `Servo_1__JOINT_1` is servo 1 (joint 1)'s."""
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    offscreen = _StubOffscreen((_BodyStub("Servo_1__JOINT_1", (), (140, 170, 180, 190)),))
    monkeypatch.setattr(renderers, "_offscreen", lambda: offscreen)
    drawer = _renderers(scope)
    async with scope.maker() as db:
        plan = await drawer.plan(db, await _entity_read(scope, arm.parts[0]))
    assert plan is not None

    render = await drawer.render(plan, ViewSpec("iso"))

    assert render.boxes == {arm.parts[0]: (140, 170, 180, 190)}
    assert offscreen.calls[0]["target_name"] == body_key("servo 1 (joint 1)") == "servo_1_joint_1"


async def test_a_scene_hidden_from_the_askers_view_draws_nothing_for_them(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """P5 fix 1 (M6): the scene read is a graph read like any other, made in the asker's scope. A
    scene model their view hides (here one from a base source their revision snapshot replaces)
    draws nothing for them, while the person who sees it still gets it."""
    scope = await _render_scope(engine, tmp_path)
    arm, scene_id = await _scene_for_arm(scope)
    member = await _member(scope)
    base = await _hidden_base_for(scope, member)
    async with scope.maker() as db:
        scene = await db.get(GraphEntity, scene_id)
        assert scene is not None
        scene.source_id = base
        await db.commit()
    drawer = _renderers(scope)
    servo = await _entity_read(scope, arm.parts[1])

    async with scope.maker() as db:
        seen = await drawer.plan(db, servo)
        with bind_scope(await resolve_scope(db, scope.project_id, member)):
            hidden = await drawer.plan(db, servo)

    assert seen is not None and seen.renderer == SCENE
    assert hidden is None


async def test_nothing_draws_an_entity_without_a_scene_or_a_render_source(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    scope = await _render_scope(engine, tmp_path)
    async with scope.maker() as db:
        loose = GraphEntity(
            project_id=scope.project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name="loose bracket",
            attrs={},
        )
        db.add(loose)
        await db.commit()
    code = await _source(scope, SourceType.GITHUB, config={})
    from_code = await _sourced(scope, code, kinds.CODE_FILE, "fw/main.c")
    drawer = _renderers(scope)

    async with scope.maker() as db:
        assert await drawer.plan(db, await _entity_read(scope, loose.id)) is None
        assert await drawer.plan(db, await _entity_read(scope, from_code)) is None


def _bridge_with(
    scope: _RenderScope,
    *,
    flagged: bool,
    sent: list[str],
    user_id: uuid.UUID | None = None,
    registry: InMemoryBridgeSessionRegistry | None = None,
) -> Any:
    """`user_id`'s (the scope's person by default) live companion session, offering the sheet
    export, bound into `registry` (a fresh one by default)."""
    spec = BridgeToolSpec(
        server="kicad",
        remote_name="export_schematic_pdf",
        descriptor=ToolDescriptor(
            name=EXPORT_TOOL, description="export", params={"type": "object"}, returns={}
        ),
        returns_image=flagged,
    )
    registry = registry or InMemoryBridgeSessionRegistry()
    holder: dict[str, BridgeSession] = {}

    async def send(frame: str) -> None:
        sent.append(frame)
        data = json.loads(frame)["data"]
        asyncio.get_running_loop().create_task(_companion_answers(scope, holder["live"], data))

    async def close(code: int) -> None:
        return None

    live = BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id or scope.user_id,
        team_id=scope.team_id,
        project_id=scope.project_id,
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(spec,),
        send=send,
        close=close,
        max_inflight=4,
    )
    holder["live"] = live
    registry.bind(live)
    return registry


async def _companion_answers(
    scope: _RenderScope, live: BridgeSession, call: dict[str, Any]
) -> None:
    """What the fork and the companion do: upload the export as this call's artifact, and answer
    with its reference in place of the local path."""
    pdf = SHEET.read_bytes()
    async with scope.maker() as db:
        artifact = await create_artifact(
            db,
            scope.store,
            project_id=scope.project_id,
            created_by=live.user_id,  # the companion uploads as its own session's person
            data=pdf,
            media_type="application/pdf",
            source_tool=call["tool"],
            tool_call_id=call["call_id"],
        )
        await db.commit()
    ref = {
        "artifact_id": str(artifact.id),
        "uri": artifact.uri,
        "media_type": "application/pdf",
        "storage": "local",
        "size_bytes": len(pdf),
    }
    value = {"format": "pdf", "filename": "a-schematic.pdf", "bytes": len(pdf), "artifact_ref": ref,
             "degraded": False, "reason": None}  # fmt: skip
    ingest_result(live, ToolResult.success(call["call_id"], value))


async def test_kicad_pdf_pages_rasterised_through_render_pages(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    kicad = await _source(
        scope, SourceType.KICAD, config={"project_path": "/home/fake/proj/a.kicad_pro"}
    )
    net = await _sourced(scope, kicad, kinds.NET, "SDA")
    sent: list[str] = []
    pages: list[dict[str, Any]] = []
    real_render_pages = render_pages

    def spy(pdf: bytes, **kwargs: Any) -> Any:
        pages.append(kwargs)
        return real_render_pages(pdf, **kwargs)

    monkeypatch.setattr(renderers, "render_pages", spy)
    drawer = _renderers(scope, bridge=_bridge_with(scope, flagged=True, sent=sent))

    async with scope.maker() as db:
        plan = await drawer.plan(db, await _entity_read(scope, net))
    assert plan is not None and (plan.renderer, plan.sheets) == ("kicad", True)

    render = await drawer.render(plan, ViewSpec("sheet"))

    (frame,) = sent
    call = json.loads(frame)["data"]
    assert (call["tool"], call["args"]) == (
        EXPORT_TOOL,
        {"project_path": "/home/fake/proj/a.kicad_pro"},
    )
    assert pages == [{"pages": [1], "max_pages": 1}]  # the first page, rasterised by render_pages
    assert checked_image(render.png)[1:] == (1400, 1000) and render.boxes == {}
    async with scope.maker() as db:
        consumed = list(
            await db.scalars(select(Artifact).where(Artifact.source_tool == EXPORT_TOOL))
        )
    assert len(consumed) == 1 and consumed[0].deleted_at is not None  # read once


async def test_an_unflagged_or_unreachable_export_is_refused_and_never_called(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    scope = await _render_scope(engine, tmp_path)
    kicad = await _source(scope, SourceType.KICAD, config={"project_path": "/p/a.kicad_pro"})
    net = await _sourced(scope, kicad, kinds.NET, "SDA")
    sent: list[str] = []
    cases = [
        ({"bridge": _bridge_with(scope, flagged=False, sent=sent)}, "does not offer"),
        ({"bridge": InMemoryBridgeSessionRegistry()}, "no companion is connected"),
        ({"bridge": _bridge_with(scope, flagged=True, sent=sent), "artifact_max_bytes": 1024},
         "artifact store"),
    ]  # fmt: skip
    for overrides, why in cases:
        drawer = _renderers(scope, **overrides)
        async with scope.maker() as db:
            plan = await drawer.plan(db, await _entity_read(scope, net))
        assert plan is not None
        with pytest.raises(RenderRefusedError, match=why):
            await drawer.render(plan, ViewSpec("sheet"))
    assert sent == []


async def test_the_cloud_renderer_is_asked_through_its_own_entry(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    onshape = await _source(scope, SourceType.ONSHAPE, config={"documents": ["a1" * 12]})
    target = {"document_id": "a1" * 12, "element_id": "b2" * 12, "observed_microversion": "c3" * 12}
    part = await _sourced(scope, onshape, kinds.PART, "bracket", **target)
    asked: list[dict[str, Any]] = []
    answer: list[bytes | Exception] = [_drawn_png(), ConnectorError("quota_degraded", "paused")]

    async def render_view(self: OnshapeConnector, **request: Any) -> bytes:
        asked.append(request)
        outcome = answer.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(OnshapeConnector, "render_view", render_view)
    drawer = _renderers(scope)
    async with scope.maker() as db:
        plan = await drawer.plan(db, await _entity_read(scope, part))
    assert plan is not None and (plan.renderer, plan.sheets) == ("onshape", False)

    render = await drawer.render(plan, ViewSpec("face", "top"))

    (request,) = asked
    assert request["view"] == "top" and request["target"] == target
    assert request["source"].id == onshape.id and request["account"] is None
    assert (request["project_id"], request["team_id"]) == (scope.project_id, scope.team_id)
    assert checked_image(render.png)[0] == "image/png"
    with pytest.raises(RenderRefusedError, match="paused"):
        await drawer.render(plan, ViewSpec("iso"))
