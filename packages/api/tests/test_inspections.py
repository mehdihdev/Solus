"""SOLUSDEV-326 P2-T4: the inspections SOL's `hardware.inspect_device` keeps
(`hardware/inspections.py`). Each is its member's in its project alone, lasts as long as a parked
card stays approvable, and the oldest go first past the bound. The service itself is exercised
through the tool in test_hardware_onboarding.py."""

from __future__ import annotations

import uuid

from solus_api.hardware.detect import ProposalOut
from solus_api.hardware.inspections import INSPECTION_TTL_S, InspectionStore
from test_hardware_detect import _wire_proposal

PROJECT, ALICE, BOB = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _heard(device_ref: str = "usb:5B42134331") -> ProposalOut:
    return ProposalOut.model_validate({**_wire_proposal(), "device_ref": device_ref})


def test_an_inspection_is_its_members_in_its_project_alone() -> None:
    store = InspectionStore()
    kept = store.put(PROJECT, ALICE, _heard())
    assert store.get(PROJECT, ALICE, kept.id) == kept
    assert store.get(PROJECT, BOB, kept.id) is None
    assert store.get(uuid.uuid4(), ALICE, kept.id) is None
    assert store.get(PROJECT, ALICE, "not-an-id") is None


def test_the_newest_inspection_of_a_device_is_served_while_it_lasts() -> None:
    now = [0.0]
    store = InspectionStore(clock=lambda: now[0])
    store.put(PROJECT, ALICE, _heard())
    newer = store.put(PROJECT, ALICE, _heard())
    store.put(PROJECT, BOB, _heard())
    store.put(PROJECT, ALICE, _heard("usb:OTHER"))
    assert store.latest(PROJECT, ALICE, "usb:5B42134331") == newer
    assert store.latest(PROJECT, ALICE, "usb:ABSENT") is None
    now[0] = INSPECTION_TTL_S + 1
    assert store.latest(PROJECT, ALICE, "usb:5B42134331") is None
    assert store.get(PROJECT, ALICE, newer.id) is None


def test_the_oldest_inspections_go_first_past_the_bound() -> None:
    store = InspectionStore(max_entries=2)
    first = store.put(PROJECT, ALICE, _heard())
    second = store.put(PROJECT, ALICE, _heard())
    third = store.put(PROJECT, ALICE, _heard())
    assert store.get(PROJECT, ALICE, first.id) is None
    assert [store.get(PROJECT, ALICE, kept.id) for kept in (second, third)] == [second, third]


def test_the_newest_inspection_answers_as_fresh_only_within_its_window() -> None:
    """`within_s` is a shorter life than the store's own: what `inspect_device` answers instead
    of listening again, while a card can still stamp the same inspection by id."""
    now = [0.0]
    store = InspectionStore(ttl_s=100.0, clock=lambda: now[0])
    project, user = uuid.uuid4(), uuid.uuid4()
    kept = store.put(project, user, _heard())

    now[0] = 30.0
    assert store.latest(project, user, kept.device_ref, within_s=30.0) is kept
    assert store.latest(project, uuid.uuid4(), kept.device_ref, within_s=30.0) is None
    assert store.latest(uuid.uuid4(), user, kept.device_ref, within_s=30.0) is None
    now[0] = 31.0
    assert store.latest(project, user, kept.device_ref, within_s=30.0) is None
    assert store.latest(project, user, kept.device_ref) is kept
    assert store.get(project, user, kept.id) is kept


def test_an_inspection_nobody_asked_for_answers_once_while_fresh() -> None:
    """A plug-in's inspection answers the first `inspect_device` call after it and no other: a
    peek leaves it, a take spends it, and one made on request is never handed out this way."""
    now = [0.0]
    store = InspectionStore(clock=lambda: now[0])
    asked = store.put(PROJECT, ALICE, _heard("usb:ASKED"))
    kept = store.put(PROJECT, ALICE, _heard(), unasked=True)
    ref = kept.device_ref

    assert store.unasked(PROJECT, ALICE, asked.device_ref, within_s=30.0) is None
    assert store.unasked(PROJECT, BOB, ref, within_s=30.0) is None
    now[0] = 12.4
    assert store.unasked(PROJECT, ALICE, ref, within_s=30.0) is kept
    assert store.age_s(kept) == 12
    assert store.unasked(PROJECT, ALICE, ref, within_s=30.0, take=True) is kept
    assert store.unasked(PROJECT, ALICE, ref, within_s=30.0) is None
    spent = store.get(PROJECT, ALICE, kept.id)  # still there for a card to stamp
    assert spent is not None and spent.proposal == kept.proposal

    late = store.put(PROJECT, ALICE, _heard(), unasked=True)
    now[0] += 31.0
    assert store.unasked(PROJECT, ALICE, ref, within_s=30.0) is None
    assert store.latest(PROJECT, ALICE, ref) is late
