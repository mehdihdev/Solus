"""SOLUSDEV-321 P2-T1 fix 1 — which joint and which channel belong to a part
(`livebench/scene/part_bindings.py`).

One implementation for the first tier (`agent/deterministic_facts.py`) and the envelopes
(`livebench/findings/envelopes.py`), extracted from the first tier's own so the two cannot drift.
The rules are pure and are driven on hand-built inputs; the containment query runs against the
real database, through the fake arm.
"""

from __future__ import annotations

import uuid
from typing import Any

from fixtures.fake_arm import seed_fake_arm
from solus_api.graph import kinds
from solus_api.hardware.config import TelemetryChannel
from solus_api.livebench.scene.part_bindings import (
    SCENES,
    JointRange,
    bound_scenes,
    channel_for_quantity,
    scene_joint_for_part,
)
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_solus_layer import _project


def _channels(*names: str) -> list[TelemetryChannel]:
    return [TelemetryChannel(name=name, unit="u") for name in names]


def _joint_attrs(
    part: uuid.UUID | None, *joints: dict[str, Any], bound: tuple[str, ...] = ("j3",)
) -> dict[str, Any]:
    """A scene model's attrs: its joints, and a binding of each `bound` joint name to `part`."""
    return {
        "model": {"joints": list(joints)},
        "bindings": [{"joint": name, "part_entity_id": str(part)} for name in bound]
        if part
        else [],
    }


def _joint_row(name: str, lower: object, upper: object, kind: str = "revolute") -> dict[str, Any]:
    return {"name": name, "type": kind, "lower": lower, "upper": upper}


def _scene_entity(project_id: uuid.UUID, attrs: dict[str, Any], **fields: Any) -> GraphEntity:
    return GraphEntity(
        project_id=project_id,
        kind=kinds.BENCH_SCENE_MODEL,
        domain=Domain.SIMULATION,
        origin="manual",
        name="scene",
        attrs=attrs,
        **fields,
    )


# --------------------------------------------------------------------- the channel rule


def test_channel_for_quantity_is_the_one_channel_named_for_it() -> None:
    named = _channels("servo3.current", "servo3.position", "servo3.commanded_position")
    assert channel_for_quantity(named, "current") == named[0]
    assert channel_for_quantity(named, "position") == named[1]  # not `commanded_position`
    assert channel_for_quantity(named, "torque") is None  # no such channel
    assert channel_for_quantity((), "current") is None  # no channels at all
    # a name with no role in front of it is the quantity too
    assert channel_for_quantity(_channels("current"), "current") is not None
    # two channels for one quantity: which is meant is not known, so none
    assert channel_for_quantity(_channels("servo3.current", "aux.current"), "current") is None


# ---------------------------------------------------------------------- the joint rule


def test_scene_joint_for_part_reads_the_bound_joint_in_the_scenes_own_unit() -> None:
    part, other, scene = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    revolute = [(scene, _joint_attrs(part, _joint_row("j3", -2.5, 2.5)))]
    assert scene_joint_for_part(revolute, part) == JointRange(scene, "j3", -2.5, 2.5, "rad")
    slide = [(scene, _joint_attrs(part, _joint_row("s1", 0, 0.3, "prismatic"), bound=("s1",)))]
    assert scene_joint_for_part(slide, part) == JointRange(scene, "s1", 0.0, 0.3, "m")
    assert scene_joint_for_part(revolute, other) is None  # the binding names another part
    assert scene_joint_for_part([], part) is None


def test_scene_joint_for_part_needs_two_numeric_bounds_and_tolerates_junk() -> None:
    part, scene = uuid.uuid4(), uuid.uuid4()
    for lower, upper in ((True, 1.0), (-1.0, None), (None, None), ("-1", "1"), (-1.0, False)):
        scenes = [(scene, _joint_attrs(part, _joint_row("j3", lower, upper)))]
        assert scene_joint_for_part(scenes, part) is None, (lower, upper)
    # a binding to a joint the model does not hold, and attrs of the wrong shape
    missing = [(scene, _joint_attrs(part, _joint_row("j9", 0, 1)))]
    assert scene_joint_for_part(missing, part) is None
    for junk in (
        {"model": [], "bindings": "j3"},
        {"model": {"joints": "j3"}, "bindings": [7, None, {"joint": "j3"}]},
        {},
    ):
        assert scene_joint_for_part([(scene, junk)], part) is None, junk


def test_a_non_finite_bound_makes_no_range_exactly_like_a_missing_one() -> None:
    """jsonb reads `1e400` back as `inf`; `nan` and `-inf` are as little a bound. The joint
    contributes nothing, and another joint bound to the part still answers."""
    part, scene = uuid.uuid4(), uuid.uuid4()
    for lower, upper in (
        (float("inf"), 1.0),
        (-1.0, float("-inf")),
        (float("nan"), 1.0),
        (-1.0, float("inf")),
    ):
        scenes = [(scene, _joint_attrs(part, _joint_row("j3", lower, upper)))]
        assert scene_joint_for_part(scenes, part) is None, (lower, upper)
    both = _joint_attrs(
        part, _joint_row("j3", float("inf"), 1.0), _joint_row("j4", -1.0, 1.0), bound=("j3", "j4")
    )
    assert scene_joint_for_part([(scene, both)], part) == JointRange(scene, "j4", -1.0, 1.0, "rad")


def test_an_integer_beyond_float_range_makes_no_range_and_raises_nothing() -> None:
    """`float(10**400)` raises OverflowError; a bound nobody could use must not take the read
    of every other part down with it."""
    part, scene = uuid.uuid4(), uuid.uuid4()
    for lower, upper in ((-1.0, 10**400), (-(10**400), 1.0)):
        scenes = [(scene, _joint_attrs(part, _joint_row("j3", lower, upper)))]
        assert scene_joint_for_part(scenes, part) is None, (lower, upper)
    big = 2**53 + 1  # an int that is a bound: kept, as the float it rounds to
    scenes = [(scene, _joint_attrs(part, _joint_row("j3", -big, big)))]
    assert scene_joint_for_part(scenes, part) == JointRange(
        scene, "j3", -float(big), float(big), "rad"
    )


def test_scene_joint_for_part_with_several_scenes_answers_only_when_they_agree() -> None:
    part = uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    wide = _joint_attrs(part, _joint_row("j3", -2.5, 2.5))
    same = _joint_attrs(part, _joint_row("elbow", -2.5, 2.5), bound=("elbow",))
    narrow = _joint_attrs(part, _joint_row("j3", -1.0, 1.0))
    assert scene_joint_for_part([(first, wide), (second, same)], part) == JointRange(
        first, "j3", -2.5, 2.5, "rad"
    )
    # which of two ranges is meant is not known
    assert scene_joint_for_part([(first, wide), (second, narrow)], part) is None
    # the same numbers in another unit are another range
    slide = _joint_attrs(part, _joint_row("j3", -2.5, 2.5, "prismatic"))
    assert scene_joint_for_part([(first, wide), (second, slide)], part) is None


# ----------------------------------------------------------------- the containment query


async def test_bound_scenes_reads_only_this_projects_scenes_that_bind_the_parts(
    engine: AsyncEngine,
) -> None:
    """The query is jsonb containment on the bindings, so scenes that bind nothing here — fifty
    of them with ids that sort first, another project's scene that binds the same part id — are
    never read, and the cap never hides the one that does."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    mine, theirs = await _project(maker), await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, mine, user_id=None)
        servo_3, servo_1, servo_2 = arm.parts[2], arm.parts[0], arm.parts[1]
        db.add_all(
            _scene_entity(mine, _joint_attrs(None), id=uuid.UUID(int=n)) for n in range(1, 51)
        )
        wide = _scene_entity(mine, _joint_attrs(servo_3, _joint_row("j3", -2.5, 2.5)))
        narrow = _scene_entity(mine, _joint_attrs(servo_1, _joint_row("j3", -1.0, 1.0)))
        db.add_all([wide, narrow])
        db.add(_scene_entity(theirs, _joint_attrs(servo_3, _joint_row("j3", -9.0, 9.0))))
        await db.commit()
        scenes = await bound_scenes(db, mine, [servo_3, servo_1, servo_2])

    assert sorted(scene_id for scene_id, _ in scenes) == sorted([wide.id, narrow.id])
    assert scene_joint_for_part(scenes, servo_3) == JointRange(wide.id, "j3", -2.5, 2.5, "rad")
    assert scene_joint_for_part(scenes, servo_1) == JointRange(narrow.id, "j3", -1.0, 1.0, "rad")
    assert scene_joint_for_part(scenes, servo_2) is None  # no scene binds it


async def test_bound_scenes_is_capped_and_ordered_by_scene_id(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        servo = arm.parts[2]
        db.add_all(
            _scene_entity(
                project_id, _joint_attrs(servo, _joint_row("j3", -n, n)), id=uuid.UUID(int=n)
            )
            for n in range(1, SCENES + 3)
        )
        await db.commit()
        scenes = await bound_scenes(db, project_id, [servo])
        assert await bound_scenes(db, project_id, []) == []

    assert SCENES == 50
    assert [scene_id.int for scene_id, _ in scenes] == list(range(1, SCENES + 1))
