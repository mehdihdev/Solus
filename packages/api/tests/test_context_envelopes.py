"""SOLUSDEV-321 P2-T1 — the `envelope` sections of the findings layer.

Each part in scope that has an envelope renders up to four of its quantities, one line each, after
the open findings that observe it: what normal, warn and limit look like and where each bound came
from, cited `[envelope:<part>:<quantity>]` so the reply's citations verify. They are read in the
same one session as the rest of the `.solus` layers, and a failed envelope read costs only them.
Driven through the real `build_context` against the real database and the fake arm.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

import pytest
from fixtures.fake_arm import seed_fake_arm
from solus_api.agent.context import Context, build_context
from solus_api.agent.interfaces import GraphScope
from solus_api.agent.layers import LayerBudget, LayeredContextBudget
from solus_api.agent.reason import verified_citations
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    PartLimits,
    ProvenanceRecord,
    TelemetryChannel,
)
from solus_api.hardware.store import put_entity_config
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_solus_layer import _context, _part, _project, _ScopedGraph

_WIDE_LIMITS: Final[dict[str, float]] = {
    "current_a": 3.0,
    "stall_current_a": 6.0,
    "temp_c": 80.0,
    "voltage_min_v": 10.0,
    "voltage_max_v": 14.0,
    "position_min": -90.0,
    "position_max": 90.0,
    "velocity_max": 200.0,
    "torque_nm": 4.0,
}
#: Six channels, one per quantity: the part has six envelopes, the layer shows four.
_WIDE_CHANNELS: Final = (
    ("w.current", "A"),
    ("w.temperature", "degC"),
    ("w.voltage", "V"),
    ("w.position", "deg"),
    ("w.velocity", "deg/s"),
    ("w.torque", "N·m"),
)
_FIRST_FOUR: Final = ("current", "temperature", "voltage", "position")
_QUESTION = "why does servo 3 stall?"


async def _wide_part(db: AsyncSession, project_id: uuid.UUID) -> GraphEntity:
    """A part whose config states a limit and a channel for all six quantities."""
    part = await _part(db, project_id, "wide actuator")
    part.kind = "part"
    await put_entity_config(
        db,
        project_id,
        part,
        EntityHardwareConfig(
            entity_id=part.id,
            component=PartConfig(
                telemetry=[TelemetryChannel(name=n, unit=u) for n, u in _WIDE_CHANNELS],
                limits=PartLimits(values=dict(_WIDE_LIMITS)),
            ),
            provenance={"component": ProvenanceRecord(by=FieldProvenance.USER)},
        ),
        expected_version=0,
        created_by=None,
    )
    return part


async def _seeded_scope(
    maker: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> dict[str, GraphEntity]:
    """The fake arm's servo 3 and robot, a six-quantity part, and a part with no config at all."""
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        wide = await _wide_part(db, project_id)
        bare = await _part(db, project_id, "bare part")
        await raise_finding(
            db,
            project_id,
            FindingSpec(
                rule_id="current_over_rating",
                severity=Severity.WARNING,
                source="observer",
                headline="servo 3 current over its rating",
                subjects=[arm.parts[2]],
                domain=Domain.ELECTRICAL,
            ),
        )
        await db.commit()
        servo, robot = await db.get(GraphEntity, arm.parts[2]), await db.get(GraphEntity, arm.robot)
        assert servo is not None and robot is not None
        return {"servo": servo, "wide": wide, "bare": bare, "robot": robot}


def _cites(part: GraphEntity, *quantities: str) -> list[str]:
    return [f"[envelope:{part.id}:{quantity}]" for quantity in quantities]


async def test_envelope_section_for_scoped_part(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    scope = await _seeded_scope(maker, project_id)
    servo, wide, bare, robot = (scope[name] for name in ("servo", "wide", "bare", "robot"))

    context = await _context(maker, project_id, _QUESTION, robot, bare, wide, servo)

    sections = context.layers.findings.sections
    # the open finding first, then each part's envelopes: parts by name, quantities in the fixed
    # order, four at most — `wide actuator` has six, its velocity and torque are not shown
    assert [section.kind for section in sections] == ["finding"] + ["envelope"] * 8
    assert [section.citation for section in sections[1:]] == [
        *_cites(servo, *_FIRST_FOUR),
        *_cites(wide, *_FIRST_FOUR),
    ]
    assert {section.score for section in sections[1:]} == {1.0}
    by_citation = {section.citation: section.text for section in sections}
    assert by_citation[_cites(servo, "current")[0]] == (
        "servo 3 (joint 3) · current A: nominal <= 1, warn <= 1.6, limit <= 2 "
        "(sources: nominal=config, warn=derived, limit=config)"
    )
    assert by_citation[_cites(servo, "voltage")[0]] == (
        "servo 3 (joint 3) · voltage V: warn 6.24 to 8.16, limit 6 to 8.4 "
        "(sources: warn=derived, limit=config)"
    )
    assert by_citation[_cites(wide, "position")[0]] == (
        "wide actuator · position deg: warn -72 to 72, limit -90 to 90 "
        "(sources: warn=derived, limit=config)"
    )
    # a part with no config and the robot itself have nothing to say, and say nothing
    rendered = " ".join(section.text for section in sections)
    assert str(bare.id) not in rendered and "bare part" not in rendered
    assert not [c for c in by_citation if str(robot.id) in str(c) or str(bare.id) in str(c)]

    # the manifest names the layer; the reply's citations verify against it, an invented one not
    layers = {s["citation"]: s["layer"] for s in context.manifest()["sections"]}
    assert {layers[c] for c in _cites(servo, *_FIRST_FOUR)} == {"findings"}
    invented = f"[envelope:{uuid.uuid4()}:current]"
    reply = f"the rating is in {_cites(servo, 'current')[0]}, not in {invented}"
    assert verified_citations(reply, context) == tuple(_cites(servo, "current"))

    # the same turn again renders the same prefix, byte for byte
    again = await _context(maker, project_id, _QUESTION, robot, bare, wide, servo)
    assert again.layers.findings.sections == sections


async def test_envelopes_pack_under_the_findings_cap_after_the_findings(
    engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    scope = await _seeded_scope(maker, project_id)
    servo = scope["servo"]
    whole = (await _context(maker, project_id, _QUESTION, servo)).layers.findings.sections
    assert [section.kind for section in whole] == ["finding", *["envelope"] * 4]

    cap = whole[0].tokens + whole[1].tokens  # room for the finding and one envelope
    budget = LayeredContextBudget(layers=LayerBudget(findings=cap))
    capped = await build_context(
        _ScopedGraph(servo),
        _QUESTION,
        project_id=project_id,
        scope=GraphScope(anchor_entity_ids=[servo.id], degree=1),
        sessionmaker=maker,
        budget=budget,
    )
    assert [s.citation for s in capped.layers.findings.sections] == [
        whole[0].citation,
        whole[1].citation,
    ]
    assert list(capped.dropped) == [s.citation for s in whole[2:]]
    assert capped.truncated is True


async def test_envelopes_are_read_in_the_one_session_of_the_turn(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    servo = (await _seeded_scope(maker, project_id))["servo"]
    opened: list[int] = []

    def counting() -> Any:
        opened.append(1)
        return maker()

    context: Context = await build_context(
        _ScopedGraph(servo),
        _QUESTION,
        project_id=project_id,
        scope=GraphScope(anchor_entity_ids=[servo.id], degree=1),
        sessionmaker=counting,  # type: ignore[arg-type]
    )
    assert [s.kind for s in context.layers.findings.sections].count("envelope") == 4
    assert len(opened) == 1  # `.solus`, findings and envelopes: one read-only session


async def test_a_failed_envelope_read_costs_only_the_envelopes(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The envelope read is the last of the turn's reads and its own failure domain: the finding
    still renders and the `.solus` layers still say what they hold, not ".solus not loaded"."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    servo = (await _seeded_scope(maker, project_id))["servo"]

    async def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the envelope read broke")

    monkeypatch.setattr("solus_api.agent.solus_layer.part_envelopes", explode)
    with caplog.at_level(logging.ERROR, logger="solus.agent.solus_layer"):
        context = await _context(maker, project_id, _QUESTION, servo)

    assert [s.kind for s in context.layers.findings.sections] == ["finding"]
    assert context.solus_empty_reason == "no standing .solus entries"
    assert any(
        "envelope" in record.getMessage() and str(project_id) in record.getMessage()
        for record in caplog.records
    )
