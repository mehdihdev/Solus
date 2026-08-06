"""SOLUSDEV-219 (CTR-04) — the impact result contract, Python half.

Validates the SAME fixture files that `packages/shared-types/src/impact.test.ts`
type-checks. One artefact, two enforcers: a field added or renamed on either
side breaks one of the two suites.

The hero fixture is also the acceptance criterion in executable form — one
mechanical change reaching electrical, code and mechanical.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.checkers.interface import Severity, severity_rank
from solus_api.contracts.impact import Consequence, ImpactNode, ImpactResult, worst_severity

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "impact"

ALL = ["hero-motor-3a", "no-impact", "truncated"]


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return loaded


def hero() -> ImpactResult:
    return ImpactResult.model_validate(load("hero-motor-3a"))


def test_the_fixture_directory_is_the_one_typescript_reads() -> None:
    assert FIXTURES.is_dir(), FIXTURES
    assert (FIXTURES.parents[1] / "src" / "impact.test.ts").is_file()


@pytest.mark.parametrize("name", ALL)
def test_fixtures_validate(name: str) -> None:
    ImpactResult.model_validate(load(name))


def test_an_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ImpactResult.model_validate({**load("no-impact"), "surprise": 1})


# ── the hero cross-domain case ───────────────────────────────────────────────


def test_one_mechanical_change_reaches_three_domains() -> None:
    # The product thesis in one fixture: a motor swap breaking electrical, code
    # and mechanical, none of which the change touched.
    assert {node.domain.value for node in hero().nodes} == {"electrical", "code", "mechanical"}


def test_the_hero_names_the_driver_the_pwm_ceiling_and_the_harness() -> None:
    assert [node.label for node in hero().nodes] == [
        "U3 TB6612FNG",
        "motor_ctl.cpp",
        "drive_harness",
    ]


def test_the_code_consequence_points_at_a_real_location() -> None:
    code = next(node for node in hero().nodes if node.domain.value == "code")
    assert code.consequences[0].evidence[0].locator == "firmware/motor_ctl/motor_ctl.cpp:88"


def test_the_driver_is_the_critical_one() -> None:
    driver = hero().nodes[0]
    assert driver.severity is Severity.CRITICAL
    assert severity_rank(driver.severity) > severity_rank(Severity.WARNING)


# ── what every row must carry ────────────────────────────────────────────────


def _consequences(result: ImpactResult) -> list[Consequence]:
    return [c for node in result.nodes for c in node.consequences]


def test_every_consequence_explains_why_it_matters() -> None:
    # A rationale short enough to restate the headline is not a rationale. This
    # field is what makes Impact worth reading instead of a list of rule names.
    for consequence in _consequences(hero()):
        assert consequence.headline
        assert len(consequence.rationale) > 80


def test_every_node_carries_a_traversal_path_starting_at_the_focus() -> None:
    result = hero()
    for node in result.nodes:
        assert node.distance == len(node.path)
        assert node.path[0].entity.entity_id == result.focus.entity.entity_id


def test_a_node_severity_is_the_worst_of_its_consequences() -> None:
    # Precomputed so a widget can sort without walking every consequence.
    for node in hero().nodes:
        assert node.severity is worst_severity([c.severity for c in node.consequences])


def test_worst_severity_of_nothing_is_the_mildest() -> None:
    assert worst_severity([]) is Severity.INFO


def test_every_row_can_launch_an_action_or_says_it_cannot() -> None:
    assert all(c.action is not None for c in _consequences(hero()))
    ldo = ImpactResult.model_validate(load("truncated")).nodes[0]
    # Nullable, never absent: a widget never has to tell "no fix" from
    # "field forgotten".
    assert ldo.consequences[0].action is None


def test_distance_must_match_the_path_length() -> None:
    # Two ways to say the same thing is two ways to be wrong; the model refuses
    # a result whose distance and path disagree rather than letting a widget
    # render a breadcrumb that contradicts its own hop count.
    broken = load("hero-motor-3a")
    broken["nodes"][0]["distance"] = 5
    with pytest.raises(ValidationError):
        ImpactResult.model_validate(broken)


# ── the states a widget must handle ──────────────────────────────────────────


def test_no_consequences_is_an_empty_result_not_an_error() -> None:
    result = ImpactResult.model_validate(load("no-impact"))
    assert result.nodes == []
    assert result.truncated is False


def test_a_bounded_traversal_says_so() -> None:
    # IMP-01 traverses to a bounded depth. A widget that did not surface this
    # would present a partial answer as a complete one.
    assert ImpactResult.model_validate(load("truncated")).truncated is True


def test_every_result_carries_the_change_that_caused_it() -> None:
    for name in ALL:
        assert ImpactResult.model_validate(load(name)).change


def test_the_change_reuses_the_action_gate_diff_row() -> None:
    # One diff shape in the product: what a user approves and what an impact was
    # caused by render identically.
    from solus_api.contracts.action_gate import DiffRow

    assert all(isinstance(row, DiffRow) for row in hero().change)


def test_a_node_with_no_consequences_is_rejected() -> None:
    # An affected entity with nothing wrong at it is not an impact; it is noise
    # the widget would render as an empty row.
    empty = load("hero-motor-3a")
    empty["nodes"][0]["consequences"] = []
    with pytest.raises(ValidationError):
        ImpactNode.model_validate(empty["nodes"][0])


# ── SOLUSDEV-216 security review ────────────────────────────────────────────


@pytest.mark.parametrize(
    "locator",
    [
        "javascript:alert(1)",
        "javascript:alert1",
        "https://attacker.example/?leak=schematic",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
    ],
)
def test_an_evidence_locator_can_never_be_a_url(locator: str) -> None:
    # An impact result is data a model may have influenced, and `locator` is
    # documented as "the thing a UI turns into a link". Unconstrained, that is a
    # model-driven XSS/exfil primitive handed to six widget authors.
    broken = load("hero-motor-3a")
    broken["nodes"][0]["consequences"][0]["evidence"][0]["locator"] = locator
    with pytest.raises(ValidationError):
        ImpactResult.model_validate(broken)


@pytest.mark.parametrize(
    "locator", ["firmware/motor_ctl/motor_ctl.cpp:88", "sch:U3", "cad:drive_harness"]
)
def test_every_documented_locator_form_still_validates(locator: str) -> None:
    ok = load("hero-motor-3a")
    ok["nodes"][0]["consequences"][0]["evidence"][0]["locator"] = locator
    assert ImpactResult.model_validate(ok)


def test_a_sol_action_is_inert_data_not_a_dispatch_surface() -> None:
    """`SolAction` is a PROPOSAL. Pinned so nobody grows it into an invoker.

    The claim was verified against the shipped gate: `decide_confirmation` calls
    `registry.invoke(ToolCall(tool=row.tool, args=dict(row.args), ...))` — the
    args come from the stored row, never from a client. So an impact row cannot
    bypass the gate. But nothing stops a widget calling a NON-gated tool straight
    from `args`, so the contract must stay data-only: a row is submitted to SOL
    as a proposal, never invoked against a tool registry by a widget.
    """
    action = hero().nodes[0].consequences[0].action
    assert action is not None
    assert set(type(action).model_fields) == {"tool", "label", "args"}
    assert not any(callable(getattr(action, n, None)) for n in ("invoke", "run", "execute"))
