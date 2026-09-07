"""CORPUS C2 — the deterministic domain router (precision over recall)."""

from __future__ import annotations

import pytest
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import CorpusDomain


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("how wide does a 2 A trace need to be on 1 oz copper?", [CorpusDomain.ELECTRICAL]),
        ("what tolerance can a hobby CNC mill hold on a bearing bore?", [CorpusDomain.MECHANICAL]),
        ("my ROS node drops sensor messages, is it QoS?", [CorpusDomain.SOFTWARE]),
        ("the 5 V rail browns out when the servo moves; power budget?", None),
        (
            "how do I tune the PID gains on the arm joint without overshoot?",
            [CorpusDomain.ROBOTICS],
        ),
        ("do I need an e-stop interlock chain for the enclosure?", [CorpusDomain.SYSTEMS]),
    ],
)
def test_clear_questions_route_to_one_domain(
    query: str, expected: list[CorpusDomain] | None
) -> None:
    routed = route_domains(query)
    if expected is None:
        assert routed is None or len(routed) >= 2  # genuinely cross-domain: never one alone
    else:
        assert routed == expected


def test_a_trace_width_question_with_mechanical_words_stays_electrical() -> None:
    # "tolerance" and "clearance" are mechanical words; the copper/trace/current
    # vocabulary must still win, so machining tolerances are never loaded.
    routed = route_domains(
        "what is the current tolerance of a 0.3 mm trace with 0.2 mm clearance on the pcb?"
    )
    assert routed == [CorpusDomain.ELECTRICAL]


def test_no_domain_words_means_no_filter() -> None:
    assert route_domains("why does this keep happening every morning?") is None
    assert route_domains("") is None


def test_routing_is_deterministic_and_case_insensitive() -> None:
    a = route_domains("I2C ADDRESS conflict on the IMU")
    b = route_domains("i2c address conflict on the imu")
    assert a == b
