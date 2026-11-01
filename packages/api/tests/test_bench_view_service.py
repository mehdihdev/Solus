"""BenchViewService: ops, inverse ops, bounds and events (docs/api/bench-view.md §2–§3, §8)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import pytest
from pydantic import ValidationError
from solus_api.core.errors import APIError
from solus_api.livebench.view.schemas import BenchViewPatch, parse_ops
from solus_api.livebench.view.service import BenchViewService
from solus_api.models import BenchView, DataEvent, Membership, Project, Role, Team, User, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

DEV = "usb:5A7A/3"
LIFT = 'sig("usb:5A7A/3", "shoulder_lift.goal") - sig("usb:5A7A/3", "shoulder_lift.position")'


@dataclass
class World:
    team: Team
    user: User
    project: Project


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def world(maker: async_sessionmaker[AsyncSession]) -> World:
    async with maker() as s:
        team = Team(name="T")
        user = User(supabase_user_id="u", email="u@x.io", data_collection_consent=True)
        s.add_all([team, user])
        await s.flush()
        project = Project(team_id=team.id, name="P")
        s.add_all([Membership(team_id=team.id, user_id=user.id, role=Role.MEMBER), project])
        await s.commit()
        return World(team, user, project)


@pytest.fixture
async def session(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as s:
        yield s


def sig(signal: str, device_id: str = DEV) -> dict[str, str]:
    return {"kind": "signal", "device_id": device_id, "signal": signal}


def show(target: dict[str, Any], **patch: Any) -> dict[str, Any]:
    return {"kind": "set_display", "target": target, "patch": patch}


def upsert(name: str, expression: str = LIFT, **extra: Any) -> dict[str, Any]:
    return {"kind": "upsert_derived", "name": name, "expression": expression, **extra}


async def apply(
    session: AsyncSession,
    world: World,
    ops: list[dict[str, Any]],
    version: int | None = 0,
    *,
    undo: bool = False,
    actor: Literal["user", "sol"] = "user",
    role: Role | None = Role.MEMBER,
) -> Any:
    result = await BenchViewService(session).apply(
        project_id=world.project.id,
        team_id=world.team.id,
        user=world.user,
        role=role,
        ops=parse_ops(ops),
        expected_version=version,
        undo=undo,
        actor=actor,
    )
    await session.commit()
    return result


def state(view: Any) -> tuple[Any, Any]:
    """Comparable view content (timestamps excluded; derived keyed by id)."""
    data = view.model_dump(mode="json")
    derived = {
        d["id"]: {k: d[k] for k in ("name", "expression", "unit", "node_count", "refs")}
        for d in data["derived"]
    }
    return data["display"], derived


async def undo(session: AsyncSession, world: World, result: Any) -> Any:
    ops = [op.model_dump(mode="json") for op in result.inverse_ops]
    return await apply(session, world, ops, result.version, undo=True)


async def error_of(coro: Any) -> APIError:
    with pytest.raises(APIError) as caught:
        await coro
    return caught.value


# ------------------------------------------------------------------------- read


async def test_get_returns_the_default_view_before_any_write(
    session: AsyncSession, world: World
) -> None:
    view = await BenchViewService(session).get(world.project.id)
    assert view.model_dump(mode="json") == {
        "version": 0,
        "display": [],
        "derived": [],
        "updated_at": None,
    }
    assert await session.get(BenchView, world.project.id) is None


async def test_get_serves_a_corrupt_row_as_the_empty_view_at_its_version(
    session: AsyncSession, world: World
) -> None:
    session.add(
        BenchView(project_id=world.project.id, version=4, display=[{"bogus": 1}], derived=[])
    )
    await session.commit()
    view = await BenchViewService(session).get(world.project.id)
    assert (view.version, view.display, view.derived) == (4, [], [])


# ------------------------------------------------------------------ set_display


async def test_set_display_creates_merges_and_removes_all_default_entries(
    session: AsyncSession, world: World
) -> None:
    target = sig("shoulder_lift.position")
    first = await apply(session, world, [show(target, pinned=True, unit="rad")])
    assert first.version == 1
    entry = first.view.model_dump(mode="json")["display"][0]
    assert entry == {
        "target": target,
        "pinned": True,
        "hidden": False,
        "order": None,
        "unit": "rad",
        "limits": None,
        "plot_group": None,
    }
    merged = await apply(
        session, world, [show(target, limits={"min": -1.6, "max": 1.6}, order=3)], 1
    )
    entry = merged.view.model_dump(mode="json")["display"][0]
    assert entry["pinned"] is True and entry["order"] == 3
    assert entry["limits"] == {"min": -1.6, "max": 1.6}
    cleared = await apply(
        session, world, [show(target, pinned=None, unit=None, limits=None, order=None)], 2
    )
    assert cleared.view.display == []
    row = await session.get(BenchView, world.project.id)
    assert row is not None and row.version == 3 and row.display == []
    assert row.updated_by == world.user.id


async def test_set_display_inverse_restores_prior_values(
    session: AsyncSession, world: World
) -> None:
    target = sig("elbow.position")
    base = await apply(session, world, [show(target, pinned=True, plot_group="Arm")])
    before = state(base.view)
    changed = await apply(
        session, world, [show(target, pinned=False, hidden=True, plot_group="Other")], 1
    )
    assert [op.model_dump(mode="json") for op in changed.inverse_ops] == [
        show(target, pinned=True, hidden=None, plot_group="Arm")
    ]
    restored = await undo(session, world, changed)
    assert restored.version == 3
    assert state(restored.view) == before


async def test_set_display_on_a_missing_derived_target_is_not_found(
    session: AsyncSession, world: World
) -> None:
    error = await error_of(
        apply(session, world, [show({"kind": "derived", "id": str(uuid.uuid4())}, pinned=True)])
    )
    assert (error.status_code, error.code) == (404, "not_found")


async def test_set_display_may_target_a_derived_signal_created_earlier_in_the_request(
    session: AsyncSession, world: World
) -> None:
    new_id = str(uuid.uuid4())
    result = await apply(
        session,
        world,
        [upsert("Lift error", id=new_id), show({"kind": "derived", "id": new_id}, pinned=True)],
    )
    assert result.view.display[0].target.model_dump(mode="json") == {
        "kind": "derived",
        "id": new_id,
    }
    assert [op.kind for op in result.inverse_ops] == ["set_display", "delete_derived"]


# ---------------------------------------------------------------- derived ops


async def test_upsert_creates_with_server_computed_refs_and_node_count(
    session: AsyncSession, world: World
) -> None:
    result = await apply(session, world, [upsert("Lift error", unit="deg")])
    (derived,) = result.view.model_dump(mode="json")["derived"]
    assert derived["name"] == "Lift error" and derived["unit"] == "deg"
    assert derived["node_count"] == 3
    assert derived["refs"] == [
        {"device_id": DEV, "signal": "shoulder_lift.goal"},
        {"device_id": DEV, "signal": "shoulder_lift.position"},
    ]
    uuid.UUID(derived["id"])
    assert [op.model_dump(mode="json") for op in result.inverse_ops] == [
        {"kind": "delete_derived", "id": derived["id"]}
    ]
    assert state((await undo(session, world, result)).view) == ([], {})


async def test_upsert_with_existing_id_replaces_and_inverse_restores(
    session: AsyncSession, world: World
) -> None:
    created = await apply(session, world, [upsert("Lift error", unit="deg")])
    derived_id = str(created.view.derived[0].id)
    before = state(created.view)
    replaced = await apply(
        session,
        world,
        [upsert("Abs", expression='abs(sig("a", "b"))', id=derived_id)],
        1,
    )
    (entry,) = replaced.view.derived
    assert (entry.name, entry.unit, entry.node_count) == ("Abs", None, 2)
    assert entry.created_at == created.view.derived[0].created_at
    assert [op.model_dump(mode="json") for op in replaced.inverse_ops] == [
        {
            "kind": "upsert_derived",
            "id": derived_id,
            "name": "Lift error",
            "expression": LIFT,
            "unit": "deg",
        }
    ]
    assert state((await undo(session, world, replaced)).view) == before


async def test_delete_removes_display_entries_and_undo_restores_same_id(
    session: AsyncSession, world: World
) -> None:
    created = await apply(session, world, [upsert("Lift error", unit="deg")])
    derived_id = str(created.view.derived[0].id)
    target = {"kind": "derived", "id": derived_id}
    shown = await apply(
        session,
        world,
        [show(target, pinned=True, order=2), show(sig("x"), hidden=True)],
        1,
    )
    before = state(shown.view)
    deleted = await apply(session, world, [{"kind": "delete_derived", "id": derived_id}], 2)
    assert deleted.view.derived == []
    assert [e.target.model_dump(mode="json") for e in deleted.view.display] == [sig("x")]
    inverse = [op.model_dump(mode="json") for op in deleted.inverse_ops]
    assert inverse == [
        {
            "kind": "upsert_derived",
            "id": derived_id,
            "name": "Lift error",
            "expression": LIFT,
            "unit": "deg",
        },
        show(target, pinned=True, order=2),
    ]
    restored = await undo(session, world, deleted)
    assert state(restored.view) == before


async def test_delete_unknown_id_is_not_found_and_writes_nothing(
    session: AsyncSession, world: World
) -> None:
    await apply(session, world, [show(sig("x"), pinned=True)])
    error = await error_of(
        apply(session, world, [{"kind": "delete_derived", "id": str(uuid.uuid4())}], 1)
    )
    assert (error.status_code, error.code) == (404, "not_found")
    await session.rollback()
    row = await session.get(BenchView, world.project.id, populate_existing=True)
    assert row is not None and row.version == 1


async def test_multi_op_inverse_is_in_reverse_application_order(
    session: AsyncSession, world: World
) -> None:
    await apply(session, world, [show(sig("a"), pinned=True)])
    before = state(await BenchViewService(session).get(world.project.id))
    result = await apply(
        session,
        world,
        [show(sig("a"), pinned=None), show(sig("b"), hidden=True), upsert("N")],
        1,
    )
    kinds = [op.kind for op in result.inverse_ops]
    assert kinds == ["delete_derived", "set_display", "set_display"]
    assert result.inverse_ops[1].model_dump(mode="json")["target"] == sig("b")
    assert state((await undo(session, world, result)).view) == before


# ----------------------------------------------------------------- version


async def test_stale_version_is_a_conflict_with_current_version(
    session: AsyncSession, world: World
) -> None:
    await apply(session, world, [show(sig("a"), pinned=True)])
    error = await error_of(apply(session, world, [show(sig("a"), hidden=True)], 0))
    assert (error.status_code, error.code) == (409, "conflict")
    assert error.details == [{"current_version": 1}]


async def test_direct_write_with_no_expected_version_applies_onto_current(
    session: AsyncSession, world: World
) -> None:
    await apply(session, world, [show(sig("a"), pinned=True)])
    result = await apply(session, world, [show(sig("b"), pinned=True)], None, actor="sol")
    assert result.version == 2


async def test_concurrent_first_writes_have_exactly_one_winner(
    maker: async_sessionmaker[AsyncSession], world: World
) -> None:
    async def attempt(name: str) -> int:
        async with maker() as s:
            try:
                await apply(s, world, [show(sig(name), pinned=True)], 0)
            except APIError as exc:
                return exc.status_code
            return 200

    results = await asyncio.gather(attempt("a"), attempt("b"))
    assert sorted(results) == [200, 409]
    async with maker() as s:
        row = await s.get(BenchView, world.project.id)
        assert row is not None and row.version == 1 and len(row.display) == 1


# ------------------------------------------------------------------ role


@pytest.mark.parametrize("role", [Role.VIEWER, None])
async def test_viewer_or_share_only_role_is_forbidden(
    session: AsyncSession, world: World, role: Role | None
) -> None:
    error = await error_of(apply(session, world, [show(sig("a"), pinned=True)], role=role))
    assert (error.status_code, error.code) == (403, "forbidden")


async def test_deleted_project_is_not_found(session: AsyncSession, world: World) -> None:
    project = await session.get(Project, world.project.id)
    assert project is not None
    project.deleted_at = utcnow()
    await session.commit()
    error = await error_of(apply(session, world, [show(sig("a"), pinned=True)]))
    assert error.status_code == 404


# -------------------------------------------------------- expressions & bounds


@pytest.mark.parametrize(
    ("expression", "code", "position"),
    [
        ('sig("a", "b") +', "syntax", 15),
        ("1 + 2", "no_signal", 0),
        ('nope(sig("a", "b"))', "unknown_function", 0),
        ('ma(sig("a", "b"), 11)', "param_range", 18),
        ("x" * 600, "too_long", 512),
    ],
)
async def test_expression_errors_carry_op_index_and_position(
    session: AsyncSession, world: World, expression: str, code: str, position: int
) -> None:
    error = await error_of(
        apply(session, world, [show(sig("a"), pinned=True), upsert("E", expression)])
    )
    assert (error.status_code, error.code) == (422, "expression_error")
    (detail,) = error.details
    assert detail["op_index"] == 1
    assert detail["code"] == code
    assert detail["position"] == position
    assert expression not in detail["message"]
    assert set(detail) == {"op_index", "code", "position", "length", "message"}


async def test_duplicate_names_are_case_insensitive(session: AsyncSession, world: World) -> None:
    await apply(session, world, [upsert("Lift error")])
    error = await error_of(apply(session, world, [upsert("LIFT ERROR")], 1))
    assert (error.status_code, error.code) == (422, "duplicate_name")


async def test_renaming_into_a_free_name_in_one_request_is_allowed(
    session: AsyncSession, world: World
) -> None:
    created = await apply(session, world, [upsert("A"), upsert("B")])
    ids = {d.name: str(d.id) for d in created.view.derived}
    swapped = await apply(
        session,
        world,
        [upsert("C", id=ids["A"]), upsert("A", id=ids["B"]), upsert("B", id=ids["A"])],
        1,
    )
    assert {d.name: str(d.id) for d in swapped.view.derived} == {"B": ids["A"], "A": ids["B"]}


async def test_too_many_derived(session: AsyncSession, world: World) -> None:
    await apply(session, world, [upsert(f"D{i}") for i in range(32)])
    error = await error_of(apply(session, world, [upsert("one more")], 1))
    assert (error.status_code, error.code) == (422, "too_many_derived")


async def test_too_many_entries(session: AsyncSession, world: World) -> None:
    version = 0
    for batch in range(16):
        ops = [show(sig(f"s{batch}.{i}"), pinned=True) for i in range(32)]
        version = (await apply(session, world, ops, version)).version
    error = await error_of(apply(session, world, [show(sig("extra"), pinned=True)], version))
    assert (error.status_code, error.code) == (422, "too_many_entries")


async def test_too_many_groups_and_too_many_in_a_group(session: AsyncSession, world: World) -> None:
    ops = [show(sig(f"g{i}"), plot_group=f"G{i}") for i in range(17)]
    error = await error_of(apply(session, world, ops))
    assert (error.status_code, error.code) == (422, "too_many_groups")
    crowded = [show(sig(f"c{i}"), plot_group="Crowd") for i in range(9)]
    error = await error_of(apply(session, world, crowded))
    assert (error.status_code, error.code) == (422, "too_many_groups")


async def test_32_deletes_with_display_entries_need_exactly_64_inverse_ops(
    session: AsyncSession, world: World
) -> None:
    created = await apply(session, world, [upsert(f"D{i}") for i in range(32)])
    ids = [str(d.id) for d in created.view.derived]
    shown = await apply(
        session, world, [show({"kind": "derived", "id": i}, pinned=True) for i in ids], 1
    )
    before = state(shown.view)
    deleted = await apply(session, world, [{"kind": "delete_derived", "id": i} for i in ids], 2)
    assert len(deleted.inverse_ops) == 64
    assert state((await undo(session, world, deleted)).view) == before


async def test_inverse_ops_over_the_limit_are_refused(
    session: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.livebench.view import service

    monkeypatch.setattr(service, "MAX_INVERSE_OPS", 2)
    error = await error_of(apply(session, world, [upsert(f"D{i}") for i in range(3)]))
    assert (error.status_code, error.code) == (422, "too_many_ops")


# ------------------------------------------------------------------- schema


@pytest.mark.parametrize(
    "body",
    [
        {"version": 0, "ops": []},
        {"version": 0, "ops": [show(sig("a"), pinned=True)] * 33},
        {"version": 0, "ops": [show(sig("a"))]},
        {"version": 0, "ops": [show(sig("a"), pinned=True)], "extra": 1},
        {"version": 0, "ops": [show({**sig("a"), "extra": 1}, pinned=True)]},
        {"version": 0, "ops": [show(sig('a"b'), pinned=True)]},
        {"version": 0, "ops": [show(sig("a"), order=1024)]},
        {"version": 0, "ops": [show(sig("a"), limits={"min": 2, "max": 1})]},
        {"version": 0, "ops": [show(sig("a"), limits={"min": 0, "max": 1e13})]},
        {"version": 0, "ops": [show(sig("a"), plot_group="")]},
        {"version": 0, "ops": [show(sig("a"), unit="u" * 33)]},
        {"version": 0, "ops": [upsert("")]},
        {"version": 0, "ops": [upsert("n" * 65)]},
        {"version": -1, "ops": [show(sig("a"), pinned=True)]},
        {"version": 0, "ops": [show(sig("a"), pinned="yes")]},
        {"version": 0, "ops": [{"kind": "rename", "id": str(uuid.uuid4())}]},
    ],
)
def test_patch_schema_rejects_bad_bodies(body: dict[str, Any]) -> None:
    with pytest.raises((ValidationError, APIError)):
        BenchViewPatch.model_validate(body)


def test_patch_schema_rejects_non_finite_numbers_with_a_serializable_error() -> None:
    with pytest.raises(APIError) as caught:
        BenchViewPatch.model_validate(
            {"version": 0, "ops": [show(sig("a"), limits={"min": float("nan"), "max": 1})]}
        )
    assert caught.value.code == "validation_error"


# ------------------------------------------------------------------- events


async def _events(session: AsyncSession, world: World) -> list[tuple[str, dict[str, Any]]]:
    rows = await session.scalars(
        select(DataEvent)
        .where(DataEvent.project_id == world.project.id)
        .order_by(DataEvent.created_at, DataEvent.id)
    )
    return [(r.event_type, r.payload) for r in rows]


async def test_events_never_carry_names_expressions_or_values(
    session: AsyncSession, world: World
) -> None:
    created = await apply(
        session, world, [upsert("Lift error"), show(sig("a"), pinned=True)], actor="sol"
    )
    derived_id = str(created.view.derived[0].id)
    deleted = await apply(session, world, [{"kind": "delete_derived", "id": derived_id}], 1)
    await undo(session, world, deleted)
    events = await _events(session, world)
    kinds = sorted(kind for kind, _ in events)
    assert kinds == sorted(
        [
            "bench.derived_signal_created",
            "bench.view_updated",
            "bench.derived_signal_deleted",
            "bench.view_updated",
            "bench.derived_signal_created",
            "bench.view_undo",
        ]
    )
    payloads = dict(events[:2])
    assert payloads["bench.view_updated"] == {
        "actor": "sol",
        "op_kinds": ["set_display", "upsert_derived"],
        "version": 1,
    }
    assert payloads["bench.derived_signal_created"] == {"count": 1, "node_count": 3}
    assert ("bench.derived_signal_deleted", {"count": 0, "node_count": 0}) in events
    assert ("bench.view_undo", {"version": 3}) in events
    blob = repr(events)
    for secret in ("Lift error", "shoulder_lift", DEV, '"a"'):
        assert secret not in blob


async def test_no_event_on_failure(session: AsyncSession, world: World) -> None:
    await error_of(apply(session, world, [upsert("E", "1 +")]))
    await session.rollback()
    assert await _events(session, world) == []
