"""SOLUSDEV-246 (STORE ST1) — first-party bundle capabilities, the non-HTTP half.

Capability discovery (CTR-01's loud, glob-style rule ported to `pkgutil`), the
publish gate as a pure function, per-request SOL tool registration through the
untouched W0-04 registry, the fixture bundle's tools and gate flags, the
`.solus/project.toml` `[ext.<id>]` reader, and the uninstall trace sweep.
Route-level behaviour lives in `test_widget_bundle_routes.py`.
"""

from __future__ import annotations

import json
import types
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import API_DIR
from fastapi import APIRouter
from fixtures.injection_corpus import PAYLOADS, Surface
from solus_api.agent.prompt import tool_specs
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    Team,
    TeamKind,
    User,
    WidgetLayout,
)
from solus_api.widgets.capability import BundleScope, DeclaredKind, WidgetCapability
from solus_api.widgets.fixture_bundle import CAPABILITY as FIXTURE
from solus_api.widgets.publish_gate import RESERVED_ID, first_party_problems
from solus_api.widgets.registry import collect_capabilities, discover_capabilities
from solus_api.widgets.solus_config import (
    SOLUS_CONFIG_KIND,
    merge_bundle_config,
    read_bundle_config,
    typed_subset,
)
from solus_api.widgets.uninstall import remove_bundle_traces
from solus_contracts.extension_manifest import ExtensionManifest, parse_extension_manifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

FIXTURES = API_DIR.parent / "shared-types" / "fixtures" / "extension-manifest"
V2_FIRST_PARTY: dict[str, Any] = json.loads(
    Path(FIXTURES / "manifest-v2-first-party.json").read_text()
)
SLUG = "fixture-bundle"
NOTE_KIND = "ext:fixture-bundle:note"


def _manifest(**over: Any) -> ExtensionManifest:
    data = json.loads(json.dumps(V2_FIRST_PARTY))
    data.update(over)
    return parse_extension_manifest(data)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(project_id, user_id, team_id) with nothing else in the graph."""
    user = User(supabase_user_id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@x.io")
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.commit()
    return project.id, user.id, team.id


def _scope(engine: AsyncEngine, project_id: uuid.UUID, user_id: uuid.UUID) -> BundleScope:
    return BundleScope(session_factory=_factory(engine), project_id=project_id, user_id=user_id)


# ------------------------------------------------------------------ discovery


def test_the_fixture_capability_is_discovered_by_package_name() -> None:
    caps = discover_capabilities()
    assert SLUG in caps
    cap = caps[SLUG]
    assert cap.id == SLUG
    assert cap.kind_names() == (NOTE_KIND,)
    assert set(cap.tools) == {"add_note", "clear_notes"}
    assert cap.router is not None


def _module(name: str, capability: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    if capability is not None:
        module.CAPABILITY = capability
    return module


def test_collect_capabilities_is_loud_on_duplicates_and_missing_exports() -> None:
    a = WidgetCapability(id="alpha", kinds=(), tools={}, router=None)
    with pytest.raises(ValueError, match="alpha"):
        collect_capabilities(
            [("pkg.one", _module("pkg.one", a)), ("pkg.two", _module("pkg.two", a))]
        )
    with pytest.raises(ValueError, match="pkg.three"):
        collect_capabilities([("pkg.three", _module("pkg.three", None))])
    with pytest.raises(ValueError, match="pkg.four"):
        collect_capabilities([("pkg.four", _module("pkg.four", object()))])


def test_collect_capabilities_is_id_sorted() -> None:
    b = WidgetCapability(id="beta", kinds=(), tools={}, router=None)
    a = WidgetCapability(id="alpha", kinds=(), tools={}, router=None)
    caps = collect_capabilities([("p.b", _module("p.b", b)), ("p.a", _module("p.a", a))])
    assert list(caps) == ["alpha", "beta"]


# ---------------------------------------------------------------- publish gate


def _caps(*caps: WidgetCapability) -> dict[str, WidgetCapability]:
    return {c.id: c for c in caps}


def test_publish_gate_passes_a_community_manifest_for_anyone() -> None:
    community = parse_extension_manifest(
        json.loads(Path(FIXTURES / "manifest-v2-community.json").read_text())
    )
    assert first_party_problems(community, is_staff=False, capabilities={}) == []
    minimal = parse_extension_manifest(
        json.loads(Path(FIXTURES / "manifest-minimal.json").read_text())
    )
    assert first_party_problems(minimal, is_staff=False, capabilities={}) == []


def test_publish_gate_refuses_first_party_tables_from_non_staff() -> None:
    problems = first_party_problems(_manifest(), is_staff=False, capabilities=_caps(FIXTURE))
    assert problems == ["backend: first-party only (publisher is not Solus staff)"]


def test_publish_gate_requires_a_matching_in_repo_capability() -> None:
    problems = first_party_problems(_manifest(), is_staff=True, capabilities={})
    assert problems == [f"backend.capability: no in-repo capability named {SLUG}"]


def test_publish_gate_requires_the_package_to_provide_every_declared_kind_tool_and_router() -> None:
    thin = WidgetCapability(id=SLUG, kinds=(DeclaredKind("note", "code"),), tools={}, router=None)
    problems = first_party_problems(_manifest(), is_staff=True, capabilities=_caps(thin))
    assert problems == [
        f"backend.routes: capability {SLUG} has no router",
        f"tools.names.0: not provided by capability {SLUG}",
        f"tools.names.1: not provided by capability {SLUG}",
    ]
    wrong_kind = _manifest(graph={"kinds": [{"name": "todo", "domain": "code"}]})
    problems = first_party_problems(wrong_kind, is_staff=True, capabilities=_caps(FIXTURE))
    assert problems == [f"graph.kinds.0: not provided by capability {SLUG}"]


def test_publish_gate_passes_the_fixture_for_staff() -> None:
    assert first_party_problems(_manifest(), is_staff=True, capabilities=_caps(FIXTURE)) == []


def test_a_capability_id_is_reserved_for_staff_even_on_a_plain_manifest() -> None:
    # M4: a community publisher must not squat "fixture-bundle" with a v1 manifest.
    data = json.loads(Path(FIXTURES / "manifest-minimal.json").read_text())
    data["extension"]["id"] = SLUG
    squat = parse_extension_manifest(data)
    assert first_party_problems(squat, is_staff=False, capabilities=_caps(FIXTURE)) == [RESERVED_ID]
    assert first_party_problems(squat, is_staff=True, capabilities=_caps(FIXTURE)) == []
    data["extension"]["id"] = "hello-widget"
    assert (
        first_party_problems(
            parse_extension_manifest(data), is_staff=False, capabilities=_caps(FIXTURE)
        )
        == []
    )


def test_graph_or_tools_alone_are_still_first_party() -> None:
    data = json.loads(json.dumps(V2_FIRST_PARTY))
    del data["backend"]
    del data["graph"]
    tools_only = parse_extension_manifest(data)
    assert first_party_problems(tools_only, is_staff=False, capabilities=_caps(FIXTURE)) == [
        "backend: first-party only (publisher is not Solus staff)"
    ]
    assert first_party_problems(tools_only, is_staff=True, capabilities=_caps(FIXTURE)) == []


# ------------------------------------------------------------ tool registration


async def test_registry_adds_bundle_tools_only_when_asked(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    bare = build_sol_registry(_factory(engine), project_id)
    assert not any(d.name.startswith(f"{SLUG}.") for d in bare.list())

    registry = build_sol_registry(
        _factory(engine),
        project_id,
        user_id=user_id,
        bundle_capabilities=[(FIXTURE, _manifest())],
    )
    names = [d.name for d in registry.list()]
    assert f"{SLUG}.add_note" in names
    assert f"{SLUG}.clear_notes" in names


async def test_registry_registers_only_the_names_the_manifest_declares(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    manifest = _manifest(tools={"names": ["add_note"]})
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, manifest)]
    )
    names = [d.name for d in registry.list()]
    assert f"{SLUG}.add_note" in names
    assert f"{SLUG}.clear_notes" not in names


async def test_a_capability_that_fails_to_build_never_takes_the_registry_down(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)

    def boom(_scope: BundleScope) -> Any:
        raise RuntimeError("wiring bug")

    broken = WidgetCapability(id=SLUG, kinds=(), tools={"add_note": boom}, router=None)
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(broken, _manifest())]
    )
    assert "get_entity" in [d.name for d in registry.list()]
    assert not any(d.name.startswith(f"{SLUG}.") for d in registry.list())


# -------------------------------------------------------------- fixture tools


async def test_add_note_writes_a_namespaced_extension_origin_entity(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, _manifest())]
    )
    result = await registry.invoke(
        ToolCall(tool=f"{SLUG}.add_note", args={"text": "check the IMU"})
    )
    assert result.ok, result.error
    assert result.value is not None
    row = await db.get(GraphEntity, uuid.UUID(result.value["id"]))
    assert row is not None
    assert row.project_id == project_id
    assert row.kind == NOTE_KIND
    assert row.domain.value == "code"
    assert row.origin == "extension"
    assert row.source_id is None and row.external_ref is None
    assert row.name == "check the IMU"


async def test_add_note_rejects_bad_args_as_structured_results(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, _manifest())]
    )
    missing = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={}))
    assert not missing.ok and missing.error is not None
    assert missing.error.code.value == "invalid_args"
    too_long = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": "x" * 201}))
    assert not too_long.ok
    # Scope comes from Solus code: a project id in args is not even a valid arg.
    smuggled = await registry.invoke(
        ToolCall(tool=f"{SLUG}.add_note", args={"text": "hi", "project_id": str(uuid.uuid4())})
    )
    assert not smuggled.ok


async def test_clear_notes_is_gated_with_a_solus_authored_summary_and_preview(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, _manifest())]
    )
    for text in ("a", "b"):
        assert (await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": text}))).ok
    descriptor = next(d for d in registry.list() if d.name == f"{SLUG}.clear_notes")
    assert descriptor.requires_confirmation is True
    assert descriptor.description_trusted is True
    assert descriptor.consent_summary and "note" in descriptor.consent_summary.lower()

    tool = FIXTURE.tools["clear_notes"](_scope(engine, project_id, user_id))
    preview = getattr(tool, "preview", None)
    assert preview is not None
    rows = await preview({})
    assert rows == [{"label": "Notes in this project", "before": "2", "after": "0"}]

    cleared = await registry.invoke(ToolCall(tool=f"{SLUG}.clear_notes", args={}))
    assert cleared.ok and cleared.value == {"cleared": 2}
    live = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == NOTE_KIND,
            GraphEntity.deleted_at.is_(None),
        )
    )
    assert live.all() == []


async def test_tools_are_bound_to_their_own_project(db: AsyncSession, engine: AsyncEngine) -> None:
    project_a, user_a, _ = await _seed_project(db)
    project_b, user_b, _ = await _seed_project(db)
    reg_a = build_sol_registry(
        _factory(engine), project_a, user_id=user_a, bundle_capabilities=[(FIXTURE, _manifest())]
    )
    reg_b = build_sol_registry(
        _factory(engine), project_b, user_id=user_b, bundle_capabilities=[(FIXTURE, _manifest())]
    )
    assert (await reg_a.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": "A's"}))).ok
    tool_b = FIXTURE.tools["clear_notes"](_scope(engine, project_b, user_b))
    assert await tool_b.preview({}) == [  # type: ignore[attr-defined]
        {"label": "Notes in this project", "before": "0", "after": "0"}
    ]
    cleared = await reg_b.invoke(ToolCall(tool=f"{SLUG}.clear_notes", args={}))
    assert cleared.ok and cleared.value == {"cleared": 0}
    a_rows = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_a, GraphEntity.deleted_at.is_(None)
        )
    )
    assert len(a_rows.all()) == 1


# ------------------------------------------------------------- .solus config


async def test_read_bundle_config_returns_the_typed_ext_table_or_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, _, _ = await _seed_project(db)
    manifest = _manifest(
        settings={
            "fields": [
                {"key": "max_notes", "type": "number", "label": "Max", "default": 10},
                {"key": "prefix", "type": "string", "label": "Prefix"},
            ]
        }
    )
    assert await read_bundle_config(db, project_id, SLUG, manifest) == {}
    # A same-kind row a bundle or a user wrote is NOT the repo config.
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=SOLUS_CONFIG_KIND,
            domain=Domain.CODE,
            name="impostor",
            origin="extension",
            attrs={"ext": {SLUG: {"max_notes": 1}}},
        )
    )
    await db.commit()
    assert await read_bundle_config(db, project_id, SLUG, manifest) == {}
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=SOLUS_CONFIG_KIND,
            domain=Domain.CODE,
            name=".solus/project.toml",
            origin="connector",
            attrs={
                "ext": {
                    SLUG: {"max_notes": 3, "prefix": 7, "unknown": True},
                    "other-bundle": {"max_notes": 99},
                }
            },
        )
    )
    await db.commit()
    # Typed against the bundle's own settings schema: wrong types and unknown
    # keys are dropped, other bundles' tables never leak.
    assert await read_bundle_config(db, project_id, SLUG, manifest) == {"max_notes": 3}


def test_effective_config_precedence_is_manifest_then_repo_then_install() -> None:
    manifest = _manifest(
        settings={
            "fields": [
                {"key": "max_notes", "type": "number", "label": "Max", "default": 100},
                {"key": "prefix", "type": "string", "label": "Prefix"},
                {"key": "flag", "type": "boolean", "label": "Flag", "default": False},
            ]
        }
    )
    merged = merge_bundle_config(
        manifest,
        repo_defaults={"max_notes": 5, "prefix": "team: ", "flag": "yes", "unknown": 1},
        install_settings={"max_notes": 2, "bogus": True},
    )
    assert merged == {"max_notes": 2, "prefix": "team: ", "flag": False}


async def test_add_note_honours_the_repo_config_prefix_and_cap(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=SOLUS_CONFIG_KIND,
            domain=Domain.CODE,
            name=".solus/project.toml",
            origin="connector",
            attrs={"ext": {SLUG: {"prefix": "fx: ", "max_notes": 1}}},
        )
    )
    await db.commit()
    manifest = _manifest(
        settings={
            "fields": [
                {"key": "max_notes", "type": "number", "label": "Max", "default": 100},
                {"key": "prefix", "type": "string", "label": "Prefix"},
            ]
        }
    )
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, manifest)]
    )
    first = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": "one"}))
    assert first.ok and first.value is not None and first.value["name"] == "fx: one"
    second = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": "two"}))
    assert not second.ok and second.error is not None
    assert "max_notes" in second.error.message  # structured, never a raise


# ---------------------------------------------------------------- red team


def _solus_payload_text() -> str:
    return next(p.text for p in PAYLOADS if p.surface is Surface.SOLUS_CONFIG)


async def test_a_hostile_solus_config_value_is_data_and_widens_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """CLAUDE.md §7 red team for the new ingestion channel: an adversarial
    `[ext.fixture-bundle].prefix` reaches the graph as a typed string, changes
    no tool spec, and is applied only as the inert prefix it is."""
    project_id, user_id, _ = await _seed_project(db)
    manifest = _manifest(
        settings={"fields": [{"key": "prefix", "type": "string", "label": "Prefix"}]}
    )
    baseline = tool_specs(
        tuple(
            build_sol_registry(
                _factory(engine),
                project_id,
                user_id=user_id,
                bundle_capabilities=[(FIXTURE, manifest)],
            ).list()
        )
    )
    hostile = _solus_payload_text()
    db.add(
        GraphEntity(
            project_id=project_id,
            kind=SOLUS_CONFIG_KIND,
            domain=Domain.CODE,
            name=".solus/project.toml",
            origin="connector",
            attrs={"ext": {SLUG: {"prefix": hostile}}},
        )
    )
    await db.commit()
    registry = build_sol_registry(
        _factory(engine), project_id, user_id=user_id, bundle_capabilities=[(FIXTURE, manifest)]
    )
    assert tool_specs(tuple(registry.list())) == baseline
    assert typed_subset(manifest, {"prefix": hostile}) == {
        "prefix": hostile
    }  # a string, nothing more
    # Nothing was cleared and no confirmation was parked: the only effect is a
    # note whose NAME carries the text as inert data.
    result = await registry.invoke(ToolCall(tool=f"{SLUG}.add_note", args={"text": "hello"}))
    assert result.ok and result.value is not None
    assert result.value["name"].startswith(hostile)
    live = await db.scalars(
        select(GraphEntity).where(GraphEntity.kind == NOTE_KIND, GraphEntity.deleted_at.is_(None))
    )
    assert len(live.all()) == 1


# ---------------------------------------------------------------- uninstall


async def test_remove_bundle_traces_soft_deletes_kinds_and_prunes_layouts(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, _ = await _seed_project(db)
    other_project, other_user, _ = await _seed_project(db)
    note = GraphEntity(
        project_id=project_id, kind=NOTE_KIND, domain=Domain.CODE, name="n", origin="extension"
    )
    keep = GraphEntity(project_id=project_id, kind="code_file", domain=Domain.CODE, name="main.c")
    foreign = GraphEntity(
        project_id=other_project,
        kind=NOTE_KIND,
        domain=Domain.CODE,
        name="theirs",
        origin="extension",
    )
    db.add_all([note, keep, foreign])
    await db.flush()
    db.add(
        GraphEdge(
            project_id=project_id,
            src_id=keep.id,
            dst_id=note.id,
            relation_type="annotates",
            domain_pair="code<->code",
        )
    )
    db.add_all(
        [
            WidgetLayout(
                project_id=project_id,
                user_id=user_id,
                layout=[
                    {"ref": "builtin:livebench", "size": "wide"},
                    {"ref": f"ext:{SLUG}", "size": "standard"},
                ],
            ),
            WidgetLayout(
                project_id=other_project,
                user_id=other_user,
                layout=[{"ref": f"ext:{SLUG}", "size": "standard"}],
            ),
        ]
    )
    await db.commit()

    swept = await remove_bundle_traces(db, project_id, SLUG, _manifest())
    await db.commit()
    assert swept.entities_soft_deleted == 1
    assert swept.layout_slots_pruned == 1

    await db.refresh(note)
    await db.refresh(keep)
    await db.refresh(foreign)
    assert note.deleted_at is not None
    assert keep.deleted_at is None
    assert foreign.deleted_at is None
    edge = await db.scalar(select(GraphEdge).where(GraphEdge.dst_id == note.id))
    assert edge is not None and edge.deleted_at is not None
    mine = await db.scalar(select(WidgetLayout).where(WidgetLayout.user_id == user_id))
    assert mine is not None and mine.layout == [{"ref": "builtin:livebench", "size": "wide"}]
    theirs = await db.scalar(select(WidgetLayout).where(WidgetLayout.user_id == other_user))
    assert theirs is not None and theirs.layout == [{"ref": f"ext:{SLUG}", "size": "standard"}]


def test_capability_router_is_a_fastapi_router() -> None:
    assert isinstance(FIXTURE.router, APIRouter)
