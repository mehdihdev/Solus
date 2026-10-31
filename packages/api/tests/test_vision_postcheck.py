"""SOLUSDEV-321 P5 (R103, D5) — `agent/vision/vision_postcheck.py`: the graph's numbers win.

A render's read is model output describing pixels. Where it names a length of a labelled part, the
length is compared — as a number, to the digits it is written to, in its own unit, through P2-T6's
grounding tokens — with the extents the graph states for that part (`attrs.geometry`). A length the
graph states differently is replaced by the graph's value, with the render's in brackets, and files
ONE `vision_fact_disagreement` info finding per (entity, length) per render, its evidence parsed
numbers only.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from solus_api.agent.interfaces import EntityRead
from solus_api.agent.vision.vision_postcheck import (
    RULE_ID,
    LengthFact,
    PostCheck,
    _parsed_evidence,
    file_disagreements,
    length_fact,
    vision_postcheck,
)
from solus_api.graph import kinds
from solus_api.models import Domain, GraphEntity, Project, Team, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

ARM_GEOMETRY = {"frame": "part_local", "length_unit": "mm", "dimensions": [40.0, 40.0, 300.0]}
BASE_GEOMETRY = {"length_unit": "mm", "dimensions": [100.0, 100.0, 50.0]}


@dataclass(frozen=True)
class _FactScope:
    maker: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID


async def _fact_project(engine: AsyncEngine) -> _FactScope:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id=f"pc-{uuid.uuid4().hex}", email="pc@example.com")
        team = Team(name="postcheck")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="postcheck")
        db.add(project)
        await db.commit()
        return _FactScope(maker, project.id)


async def _seed_part(scope: _FactScope, name: str, geometry: dict[str, Any]) -> EntityRead:
    async with scope.maker() as db:
        part = GraphEntity(
            project_id=scope.project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name=name,
            attrs={"geometry": geometry, "fake": True},
        )
        db.add(part)
        await db.commit()
        return EntityRead.model_validate(part)


def _fact(name: str, geometry: dict[str, Any]) -> LengthFact:
    read = EntityRead(
        id=uuid.uuid4(),
        kind=kinds.PART,
        domain="mechanical",
        name=name,
        attrs={"geometry": geometry},
    )
    fact = length_fact(read)
    assert fact is not None
    return fact


async def test_disagreeing_dimension_files_one_info_and_graph_wins(engine: AsyncEngine) -> None:
    scope = await _fact_project(engine)
    arm = await _seed_part(scope, "upper arm", ARM_GEOMETRY)
    fact = length_fact(arm)
    assert fact is not None
    read = (
        "The upper arm is about 320 mm long. The upper arm is 0.04 m wide. "
        "Again, the upper arm runs 320 mm."
    )

    checked = vision_postcheck(read, [fact])

    shown = "300 mm (the graph's value; the render read 320 mm)"
    assert checked.text == (
        f"The upper arm is about {shown} long. The upper arm is 0.04 m wide. "
        f"Again, the upper arm runs {shown}."
    )
    (disagreement,) = checked.disagreements  # two disagreeing tokens, one (entity, length)
    assert (disagreement.render_value, disagreement.render_unit) == (320.0, "mm")
    assert disagreement.graph_value == 300.0

    for _render in range(2):  # the same disagreement found by two renders: one finding
        async with scope.maker() as db:
            ids = await file_disagreements(
                db, scope.project_id, checked.disagreements, view_id="face:front"
            )
            await db.commit()
    async with scope.maker() as db:
        findings = list(
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == scope.project_id, GraphEntity.kind == kinds.FINDING
                )
            )
        )
    (finding,) = findings
    assert ids == [finding.id]
    attrs = finding.attrs
    assert (attrs["rule_id"], attrs["severity"], attrs["source"]) == (RULE_ID, "info", "sol")
    assert attrs["subjects"] == [str(arm.id)] and attrs["count"] == 2
    parsed = {
        "quantity": "length",
        "graph": {"value": 300.0, "unit": "mm"},
        "render": {"value": 320.0, "unit": "mm"},
        "view": "face:front",
    }
    # Parsed numbers only, latest on top and every raise under `items`: never the read's text.
    evidence = dict(attrs["evidence"])
    assert evidence.pop("items") == [parsed, parsed]
    assert evidence == parsed


def test_a_sentence_is_checked_only_when_it_names_one_labelled_part() -> None:
    facts = [_fact("upper arm", ARM_GEOMETRY), _fact("base", BASE_GEOMETRY)]
    read = (
        "The base and the upper arm sit 320 mm apart. Something else is 999 mm. "
        "The base is 100 mm wide."
    )

    checked = vision_postcheck(read, facts)

    assert checked.text == read and checked.disagreements == ()


def test_numbers_are_compared_as_numbers_in_their_own_unit() -> None:
    """`30` is not `300` because the text `300` holds it: a substring search would accept it. A
    length agrees when the graph's extent, written to the read's own digits and unit, is it."""
    fact = _fact("upper arm", ARM_GEOMETRY)
    agrees = vision_postcheck("The upper arm is 300.0 mm long and 0.3 m tall.", [fact])
    assert agrees.disagreements == ()

    checked = vision_postcheck("The upper arm is 30 mm thick.", [fact])
    (disagreement,) = checked.disagreements
    assert disagreement.graph_value == 40.0  # the nearest extent the graph states
    assert "40 mm (the graph's value; the render read 30 mm)" in checked.text


@pytest.mark.parametrize(
    "geometry",
    [
        {},
        {"length_unit": "mm"},
        {"length_unit": "mm", "dimensions": ["40", 40, 300]},
        {"length_unit": "mm", "dimensions": [40, -1, 300]},
        {"length_unit": "mm", "dimensions": [40, float("nan"), 300]},
        {"length_unit": "mm", "dimensions": [True, 40, 300]},
        {"length_unit": "mm", "dimensions": [1, 2, 3, 4]},
        {"length_unit": "in", "dimensions": [1, 2, 3]},
    ],
)
def test_only_lengths_the_graph_states_are_facts(geometry: dict[str, Any]) -> None:
    read = EntityRead(
        id=uuid.uuid4(),
        kind=kinds.PART,
        domain="mechanical",
        name="x",
        attrs={"geometry": geometry},
    )
    assert length_fact(read) is None


def test_extents_in_metres_are_compared_and_shown_in_metres() -> None:
    fact = _fact("upper arm", {"length_unit": "m", "dimensions": [0.04, 0.04, 0.3]})
    assert fact.extents_mm == (40.0, 40.0, 300.0)
    checked = vision_postcheck("The upper arm is 320 mm long.", [fact])
    assert "0.3 m (the graph's value; the render read 320 mm)" in checked.text


def test_a_non_finite_length_is_skipped_and_never_reaches_a_finding() -> None:
    """P5 fix 1 (M1): `1e999` parses but is no float. It is no length the graph could disagree
    with: it is skipped and left as read, so a finding's evidence is always valid JSON."""
    fact = _fact("upper arm", ARM_GEOMETRY)
    read = "The upper arm is 1e999 mm long."

    assert vision_postcheck(read, [fact]) == PostCheck(read, ())
    mixed = vision_postcheck("The upper arm is 1e999 mm, or 320 mm, long.", [fact])
    (disagreement,) = mixed.disagreements
    assert disagreement.render_value == 320.0 and "1e999 mm" in mixed.text
    json.dumps(_parsed_evidence(disagreement, "iso"), allow_nan=False)
