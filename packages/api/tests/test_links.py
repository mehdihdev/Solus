"""R5 link-suggestion engine (docs/api/hardware.md §3, CTR-08 bands, ADR-012 propose-never-assert).

`suggest_links` is a pure, deterministic function: graph observation + candidate robots in,
ranked suggestions out — precision over recall, nothing auto-accepts. `persist_suggestions` /
`list_suggestions` / `decide_suggestion` are the durable side of the same contract.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.config import BusMapEntry, HardwareConfig
from solus_api.hardware.links import (
    SUGGESTION_FLOOR,
    TIER_CEILING,
    LinkSuggestion,
    LinkTier,
    PartObservation,
    RobotCandidate,
    decide_suggestion,
    list_suggestions,
    persist_suggestions,
    serialize_suggestion,
    suggest_links,
)
from solus_api.models import HardwareSuggestion, SuggestionStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES = Path(__file__).parent / "fixtures" / "hardware"


# --------------------------------------------------------------------- helpers


def _raw_fixture(machine: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES / f"{machine}.json").read_text()))


def _candidate(
    machine: str, robot_id: uuid.UUID, *, bus_map: list[dict[str, Any]] | None = None
) -> RobotCandidate:
    raw = _raw_fixture(machine)
    raw["robot_entity_id"] = str(robot_id)
    if bus_map is not None:
        raw["bus_map"] = bus_map
    return RobotCandidate(
        robot_entity_id=robot_id, name=machine, config=HardwareConfig.model_validate(raw)
    )


def _match(
    modality: Modality, confidence: float, *, external_ref: str, value: str | None = None
) -> ModalityMatch:
    evidence: dict[str, Any] = {"matched_on": modality.value}
    if value is not None:
        evidence["value"] = value
    return ModalityMatch(
        modality=modality,
        source_ref=SourceRef(source_connector="bench", external_ref=external_ref),
        confidence=confidence,
        state=MatchState.MATCHED,
        evidence=evidence,
    )


def _free_slot(address: str) -> list[dict[str, Any]]:
    return [{"protocol": "feetech-sts", "address": address, "part_entity_id": None, "model": None}]


async def _hw_project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"])


async def _hw_robot(client: AsyncClient, headers: dict[str, str], project_id: str) -> uuid.UUID:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=headers,
        json={"type": "physical_robot"},
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["id"])


def _suggestion(
    subject_ref: str,
    candidate_robot_id: uuid.UUID,
    *,
    tier: LinkTier = LinkTier.HIGH,
    confidence: float = 0.80,
) -> LinkSuggestion:
    return LinkSuggestion(
        subject_ref=subject_ref,
        subject_kind="part",
        candidate_robot_id=candidate_robot_id,
        confidence=confidence,
        tier=tier,
        evidence=[
            _match(Modality.BUS_ENUMERATION, confidence, external_ref=subject_ref, value="STS3215")
        ],
        reason="bus enumeration matched a free slot",
    )


async def _sibling(db: AsyncSession, suggestion_id: uuid.UUID) -> HardwareSuggestion:
    row = await db.scalar(
        select(HardwareSuggestion)
        .where(HardwareSuggestion.id == suggestion_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


# ----------------------------------------------------------------- pure engine


def test_tier_ceilings_and_floor_match_the_ctr08_bands() -> None:
    assert TIER_CEILING == {
        Modality.BUS_ENUMERATION: 0.92,
        Modality.FIRMWARE_SYMBOL: 0.55,
        Modality.TELEMETRY_CHANNEL: 0.30,
    }
    assert SUGGESTION_FLOOR == 0.30
    assert [tier.value for tier in LinkTier] == ["high", "medium", "low"]


def test_gripper_observed_on_two_candidate_robots_yields_two_suggestions_never_one_winner() -> None:
    robot_a, robot_b = uuid.uuid4(), uuid.uuid4()
    slot = _free_slot("6")
    candidates = [
        _candidate("serial_arm", robot_a, bus_map=slot),
        _candidate("serial_arm", robot_b, bus_map=slot),
    ]
    observation = PartObservation(
        subject_ref="usb:AAAA/6",
        subject_kind="part",
        address="6",
        model="STS3215",
        evidence=[
            _match(Modality.BUS_ENUMERATION, 0.9, external_ref="usb:AAAA/6", value="STS3215")
        ],
    )
    suggestions = suggest_links(observation, candidates)
    assert len(suggestions) == 2
    assert {s.candidate_robot_id for s in suggestions} == {robot_a, robot_b}
    assert all(s.confidence == pytest.approx(0.80) for s in suggestions)
    assert all(s.tier is LinkTier.HIGH for s in suggestions)


def test_bus_identity_match_confidence_is_capped_at_the_bus_ceiling() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)  # identity.device_ref == "usb:5B42134331"
    observation = PartObservation(
        subject_ref="usb:5B42134331",
        subject_kind="device",
        device_ref="usb:5B42134331",
        evidence=[_match(Modality.BUS_ENUMERATION, 0.99, external_ref="usb:5B42134331")],
    )
    suggestions = suggest_links(observation, [candidate])
    assert len(suggestions) == 1
    assert suggestions[0].confidence == pytest.approx(0.92)
    assert suggestions[0].tier is LinkTier.HIGH


def test_firmware_prefix_match_confidence_is_capped_at_the_firmware_ceiling() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)  # part a101 has "shoulder_pan.position"
    observation = PartObservation(
        subject_ref="usb:5B42134331/1",
        subject_kind="part",
        evidence=[
            _match(
                Modality.FIRMWARE_SYMBOL,
                0.99,
                external_ref="usb:5B42134331/1",
                value="shoulder_pan",
            )
        ],
    )
    suggestions = suggest_links(observation, [candidate])
    assert len(suggestions) == 1
    assert suggestions[0].confidence == pytest.approx(0.55)
    assert suggestions[0].tier is LinkTier.MEDIUM


def test_telemetry_shape_full_overlap_hits_the_floor_at_tier_low() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)
    observation = PartObservation(
        subject_ref="usb:5B42134331/1",
        subject_kind="part",
        channel_names=["shoulder_pan.position"],
    )
    suggestions = suggest_links(observation, [candidate])
    assert len(suggestions) == 1
    assert suggestions[0].confidence == pytest.approx(0.30)
    assert suggestions[0].tier is LinkTier.LOW
    assert suggestions[0].evidence == []


def test_telemetry_shape_partial_overlap_is_below_floor_and_emits_nothing() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)
    observation = PartObservation(
        subject_ref="usb:5B42134331/1",
        subject_kind="part",
        channel_names=["shoulder_pan.position", "no_such_channel"],
    )
    assert suggest_links(observation, [candidate]) == []


def test_no_evidence_and_no_channel_names_yields_nothing() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)
    observation = PartObservation(subject_ref="usb:ZZZZ", subject_kind="device")
    assert suggest_links(observation, [candidate]) == []


def test_an_unmatched_device_ref_with_no_other_evidence_yields_nothing() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)
    observation = PartObservation(
        subject_ref="usb:ZZZZ",
        subject_kind="device",
        device_ref="usb:ZZZZ",
        evidence=[_match(Modality.BUS_ENUMERATION, 0.9, external_ref="usb:ZZZZ")],
    )
    assert suggest_links(observation, [candidate]) == []


def _library_robot(
    robot_id: uuid.UUID, *, identity: dict[str, Any] | None = None
) -> RobotCandidate:
    """A platform imported from the library: a full bus map, nothing bound to the wire yet."""
    raw = _raw_fixture("serial_arm")
    raw["robot_entity_id"] = str(robot_id)
    raw["identity"] = identity
    raw["provenance"] = {k: v for k, v in raw["provenance"].items() if not k.startswith("identity")}
    if identity is not None:
        raw["provenance"]["identity"] = {"by": "detected"}
    return RobotCandidate(
        robot_entity_id=robot_id, name="SO-101", config=HardwareConfig.model_validate(raw)
    )


def _six_servo_device(count: int = 6) -> PartObservation:
    return PartObservation(
        subject_ref="usb:AAAA",
        subject_kind="device",
        device_ref="usb:AAAA",
        bus_map=[
            BusMapEntry(protocol="feetech-sts", address=str(i), model="STS3215")
            for i in range(1, count + 1)
        ],
        evidence=[
            _match(Modality.BUS_ENUMERATION, 0.92, external_ref=f"usb:AAAA/{i}")
            for i in range(1, count + 1)
        ],
    )


def test_a_whole_bus_map_matches_a_library_robot_that_has_no_identity_yet() -> None:
    """The R4 trap: a platform imported from the library and the same machine on the wire
    must reconcile to ONE robot. The device's bus map (addresses + models) equals the
    identity-less robot's bus map -> a high suggestion; two identical library robots -> two."""
    follower, leader = uuid.uuid4(), uuid.uuid4()
    suggestions = suggest_links(
        _six_servo_device(), [_library_robot(follower), _library_robot(leader)]
    )
    assert {s.candidate_robot_id for s in suggestions} == {follower, leader}
    assert all(s.confidence == pytest.approx(0.80) and s.tier is LinkTier.HIGH for s in suggestions)
    assert all("bus map" in s.reason for s in suggestions)


def test_a_bound_or_differently_shaped_robot_never_matches_a_whole_bus_map() -> None:
    bound = _library_robot(uuid.uuid4(), identity={"kind": "usb_serial", "binding": "ZZZZ"})
    assert suggest_links(_six_servo_device(), [bound]) == []
    assert suggest_links(_six_servo_device(5), [_library_robot(uuid.uuid4())]) == []


def test_a_candidates_score_is_the_max_rule_not_the_sum_of_rules() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id, bus_map=_free_slot("6"))
    observation = PartObservation(
        subject_ref="usb:5B42134331/6",
        subject_kind="part",
        device_ref="usb:5B42134331",  # rule (a) fires too: identity matches
        address="6",
        model="STS3215",
        evidence=[
            _match(Modality.BUS_ENUMERATION, 0.6, external_ref="usb:5B42134331/6", value="STS3215")
        ],
        channel_names=["shoulder_pan.position"],  # rule (d) fires too: full overlap
    )
    suggestions = suggest_links(observation, [candidate])
    assert len(suggestions) == 1
    # max(rule a=0.6, rule b=0.80, rule d=0.30) == 0.80 -- never 0.6+0.8+0.3 clipped to 1.0
    assert suggestions[0].confidence == pytest.approx(0.80)
    assert suggestions[0].tier is LinkTier.HIGH


def test_ordering_is_deterministic_by_confidence_desc_then_candidate_robot_id() -> None:
    robot_low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    robot_high = uuid.UUID("00000000-0000-0000-0000-000000000002")
    slot = _free_slot("6")
    candidate_low = _candidate("serial_arm", robot_low, bus_map=slot)
    candidate_high = _candidate("serial_arm", robot_high, bus_map=slot)
    observation = PartObservation(
        subject_ref="usb:AAAA/6",
        subject_kind="part",
        address="6",
        model="STS3215",
        evidence=[
            _match(Modality.BUS_ENUMERATION, 0.9, external_ref="usb:AAAA/6", value="STS3215")
        ],
    )
    forward = suggest_links(observation, [candidate_low, candidate_high])
    backward = suggest_links(observation, [candidate_high, candidate_low])
    assert [s.candidate_robot_id for s in forward] == [robot_low, robot_high]
    assert forward == backward


def test_confidence_never_exceeds_the_ceiling_of_its_strongest_present_evidence_modality() -> None:
    robot_id = uuid.uuid4()
    candidate = _candidate("serial_arm", robot_id)  # identity matches + firmware channel matches
    observation = PartObservation(
        subject_ref="usb:5B42134331",
        subject_kind="device",
        device_ref="usb:5B42134331",
        evidence=[
            _match(
                Modality.FIRMWARE_SYMBOL, 0.99, external_ref="usb:5B42134331", value="shoulder_pan"
            ),
            _match(Modality.BUS_ENUMERATION, 0.4, external_ref="usb:5B42134331"),
        ],
    )
    suggestions = suggest_links(observation, [candidate])
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.evidence
    ceiling = max(TIER_CEILING[match.modality] for match in suggestion.evidence)
    assert suggestion.confidence <= ceiling


# ------------------------------------------------------------------ persistence


async def test_persist_suggestions_inserts_a_pending_row_per_candidate(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_a = await _hw_robot(client, alice_headers, project_id)
    robot_b = await _hw_robot(client, alice_headers, project_id)
    rows = await persist_suggestions(
        db,
        uuid.UUID(project_id),
        [_suggestion("usb:AAAA/6", robot_a), _suggestion("usb:AAAA/6", robot_b)],
    )
    await db.commit()
    assert len(rows) == 2
    assert {row.candidate_robot_id for row in rows} == {robot_a, robot_b}
    assert all(row.status is SuggestionStatus.PENDING for row in rows)
    assert all(row.subject_ref == "usb:AAAA/6" for row in rows)
    assert all(row.tier == "high" for row in rows)
    assert all(row.confidence == pytest.approx(0.80) for row in rows)
    assert all(row.evidence[0]["modality"] == "bus_enumeration" for row in rows)


async def test_persist_suggestions_skips_a_subject_candidate_pair_already_pending(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_id = await _hw_robot(client, alice_headers, project_id)
    suggestion = _suggestion("usb:AAAA/6", robot_id)
    first = await persist_suggestions(db, uuid.UUID(project_id), [suggestion])
    await db.commit()
    second = await persist_suggestions(db, uuid.UUID(project_id), [suggestion])
    await db.commit()
    assert len(first) == 1
    assert len(second) == 0
    assert len(await list_suggestions(db, uuid.UUID(project_id))) == 1


async def test_list_suggestions_returns_newest_first_and_defaults_to_pending(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_a = await _hw_robot(client, alice_headers, project_id)
    robot_b = await _hw_robot(client, alice_headers, project_id)
    first = await persist_suggestions(
        db, uuid.UUID(project_id), [_suggestion("usb:AAAA/6", robot_a)]
    )
    await db.commit()
    second = await persist_suggestions(
        db, uuid.UUID(project_id), [_suggestion("usb:BBBB/1", robot_b)]
    )
    await db.commit()
    rows = await list_suggestions(db, uuid.UUID(project_id))
    assert [row.id for row in rows] == [second[0].id, first[0].id]
    assert await list_suggestions(db, uuid.UUID(project_id), status=SuggestionStatus.ACCEPTED) == []


async def test_decide_suggestion_accept_supersedes_pending_siblings_for_the_same_subject(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_a = await _hw_robot(client, alice_headers, project_id)
    robot_b = await _hw_robot(client, alice_headers, project_id)
    alice = await me(client, alice_headers)
    rows = await persist_suggestions(
        db,
        uuid.UUID(project_id),
        [_suggestion("usb:AAAA/6", robot_a), _suggestion("usb:AAAA/6", robot_b)],
    )
    await db.commit()
    accepted = await decide_suggestion(
        db, uuid.UUID(project_id), rows[0].id, True, uuid.UUID(alice["id"])
    )
    await db.commit()
    assert accepted.status is SuggestionStatus.ACCEPTED
    assert accepted.decided_at is not None
    assert accepted.decided_by == uuid.UUID(alice["id"])
    sibling = await _sibling(db, rows[1].id)
    assert sibling.status is SuggestionStatus.SUPERSEDED


async def test_decide_suggestion_reject_stores_the_reason_and_leaves_siblings_pending(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_a = await _hw_robot(client, alice_headers, project_id)
    robot_b = await _hw_robot(client, alice_headers, project_id)
    alice = await me(client, alice_headers)
    rows = await persist_suggestions(
        db,
        uuid.UUID(project_id),
        [_suggestion("usb:AAAA/6", robot_a), _suggestion("usb:AAAA/6", robot_b)],
    )
    await db.commit()
    rejected = await decide_suggestion(
        db, uuid.UUID(project_id), rows[0].id, False, uuid.UUID(alice["id"]), reason="wrong arm"
    )
    await db.commit()
    assert rejected.status is SuggestionStatus.REJECTED
    assert rejected.reason == "wrong arm"
    sibling = await _sibling(db, rows[1].id)
    assert sibling.status is SuggestionStatus.PENDING


async def test_decide_suggestion_unknown_or_foreign_project_id_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    other_project_id = await _hw_project(client, alice_headers)
    robot_id = await _hw_robot(client, alice_headers, project_id)
    alice = await me(client, alice_headers)
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_suggestion("usb:AAAA/6", robot_id)]
    )
    await db.commit()
    with pytest.raises(APIError) as unknown:
        await decide_suggestion(
            db, uuid.UUID(project_id), uuid.uuid4(), True, uuid.UUID(alice["id"])
        )
    assert unknown.value.status_code == 404
    with pytest.raises(APIError) as foreign:
        await decide_suggestion(
            db, uuid.UUID(other_project_id), rows[0].id, True, uuid.UUID(alice["id"])
        )
    assert foreign.value.status_code == 404


async def test_deciding_an_already_decided_suggestion_is_a_conflict(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_id = await _hw_robot(client, alice_headers, project_id)
    alice = await me(client, alice_headers)
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_suggestion("usb:AAAA/6", robot_id)]
    )
    await db.commit()
    await decide_suggestion(db, uuid.UUID(project_id), rows[0].id, True, uuid.UUID(alice["id"]))
    await db.commit()
    with pytest.raises(APIError) as excinfo:
        await decide_suggestion(db, uuid.UUID(project_id), rows[0].id, True, uuid.UUID(alice["id"]))
    assert excinfo.value.status_code == 409


async def test_serialize_suggestion_matches_the_documented_shape(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _hw_project(client, alice_headers)
    robot_id = await _hw_robot(client, alice_headers, project_id)
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_suggestion("usb:AAAA/6", robot_id)]
    )
    await db.commit()
    row = rows[0]
    payload = serialize_suggestion(row)
    assert set(payload) == {
        "id",
        "subject_ref",
        "subject_kind",
        "candidate_robot_id",
        "confidence",
        "tier",
        "evidence",
        "reason",
        "status",
        "created_at",
        "decided_at",
    }
    assert payload["id"] == row.id
    assert payload["subject_ref"] == row.subject_ref
    assert payload["subject_kind"] == row.subject_kind
    assert payload["candidate_robot_id"] == row.candidate_robot_id
    assert payload["confidence"] == row.confidence
    assert payload["tier"] == row.tier
    assert payload["evidence"] == row.evidence
    assert payload["reason"] == row.reason
    assert payload["status"] == row.status
    assert payload["created_at"] == row.created_at
    assert payload["decided_at"] == row.decided_at
