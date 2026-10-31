"""SOLUSDEV-321 P4-T1 — simulation as a capability: the shape every rung implements, and a result
that carries its whole provenance (solver, inputs with their sources, what the model leaves out)
or does not validate at all."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import pytest
from pydantic import ValidationError
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.simulation.sim_capability import (
    MAX_RESULT_BYTES,
    MissingInputs,
    SimInput,
    SimProvenance,
    SimProvider,
    SimQuestion,
    SimResult,
    SimValue,
)

MATERIAL: Final = FactNeed(name="material", set_in="the part's `material` attr: {name, yield_mpa}")


def _beam_result(**provenance: Any) -> dict[str, Any]:
    """A rung-1 stress result as a provider returns it; `provenance` overrides its keys."""
    return {
        "values": {"stress_mpa": {"value": 41.4, "unit": "MPa"}},
        "provenance": {
            "solver": "beam_bending",
            "inputs": {
                "material": {"value": {"name": "fake-6061", "yield_mpa": 276}, "source": "known"},
                "section_modulus_mm3": {"value": 120.5, "source": "derived"},
                "load_factor": {"value": 1.0, "source": "assumed"},
            },
            "leaves_out": ["dynamic loads", "fatigue"],
            **provenance,
        },
    }


def test_a_result_carries_its_solver_inputs_with_sources_and_what_it_leaves_out() -> None:
    result = SimResult.model_validate(_beam_result())
    assert result.provenance.solver == "beam_bending"
    assert {name: given.source for name, given in result.provenance.inputs.items()} == {
        "material": "known",
        "section_modulus_mm3": "derived",
        "load_factor": "assumed",
    }
    assert result.provenance.leaves_out == ("dynamic loads", "fatigue")
    assert (result.values["stress_mpa"].value, result.values["stress_mpa"].unit) == (41.4, "MPa")
    assert SimResult.model_validate(result.model_dump(mode="json")) == result


@pytest.mark.parametrize(
    "provenance",
    [
        {"solver": ""},
        {"solver": "   "},
        {"inputs": {}},
        {"leaves_out": []},
        {"leaves_out": ["fatigue", " "]},
        {"inputs": {"material": {"value": 1}}},
        {"inputs": {"material": {"value": 1, "source": "guessed"}}},
        {"inputs": {"material": {"value": 1, "source": "known", "trust": "me"}}},
        {"citation": "a vendor sheet"},
    ],
    ids=[
        "no-solver",
        "a-blank-solver",
        "no-inputs",
        "leaves-out-nothing",
        "a-blank-leaves-out-entry",
        "an-input-without-a-source",
        "a-source-that-is-not-one",
        "an-input-with-an-unknown-key",
        "an-unknown-provenance-key",
    ],
)
def test_a_result_without_its_full_provenance_does_not_validate(
    provenance: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        SimResult.model_validate(_beam_result(**provenance))


def test_a_result_without_provenance_or_with_a_value_nobody_can_read_does_not_validate() -> None:
    stated = _beam_result()
    with pytest.raises(ValidationError):
        SimResult.model_validate({"values": stated["values"]})
    for values in (
        {},
        {"stress_mpa": {"value": float("nan")}},
        {"stress_mpa": {"value": float("inf"), "unit": "MPa"}},
        {"Stress MPa": {"value": 1.0}},  # a quantity a style line could not name back
    ):
        with pytest.raises(ValidationError):
            SimResult.model_validate({**stated, "values": values})
    with pytest.raises(ValidationError):  # an input is JSON, or it is not an input
        SimInput.model_validate({"value": object(), "source": "known"})


def test_an_instance_is_revalidated_so_a_constructed_one_cannot_skip_its_provenance() -> None:
    """The facts writer validates what it is handed: a `model_construct` shell is refused."""
    shell = SimResult.model_construct(values={}, provenance=None)
    with pytest.raises(ValidationError):
        SimResult.model_validate(shell)


def test_a_constructed_provenance_input_or_value_inside_a_result_is_refused_too() -> None:
    """Every model re-validates what it is handed, so a shell at any depth is refused: an empty
    provenance, an input with no real source, a value that is not a number."""
    stated = SimResult.model_validate(_beam_result())
    empty = SimProvenance.model_construct(solver="", inputs={}, leaves_out=())
    guessed = SimProvenance.model_construct(
        solver="beam_bending",
        inputs={"material": SimInput.model_construct(value=1, source="guessed")},
        leaves_out=("fatigue",),
    )
    not_a_number = {"stress_mpa": SimValue.model_construct(value=float("nan"), unit="MPa")}
    for shell in (
        SimResult.model_construct(values=stated.values, provenance=empty),
        SimResult.model_construct(values=stated.values, provenance=guessed),
        SimResult.model_construct(values=not_a_number, provenance=stated.provenance),
    ):
        with pytest.raises(ValidationError):
            SimResult.model_validate(shell)


def test_a_result_is_bounded() -> None:
    copied = {"inputs": {"mesh": {"value": "v" * MAX_RESULT_BYTES, "source": "known"}}}
    with pytest.raises(ValidationError, match="bytes"):
        SimResult.model_validate(_beam_result(**copied))


@dataclass(frozen=True)
class _Beam:
    """A rung-1 provider double. Its members are read-only, as the Protocol allows."""

    name: str = "beam"
    domain: str = "mechanical"
    rung: int = 1
    quantities: frozenset[str] = frozenset({"stress_mpa"})

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        if "material" in question.facts:
            return MissingInputs()
        return MissingInputs(missing=(MATERIAL,), covered=("mass_kg",))

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        return SimResult.model_validate(_beam_result())


def test_a_provider_names_what_a_question_lacks_and_runs_to_a_result() -> None:
    provider: SimProvider = _Beam()  # mypy holds the double to the Protocol
    bracket = uuid.uuid4()
    bare = provider.can_answer(SimQuestion(subject_id=bracket, quantity="stress_mpa"))
    assert (bare.names, bare.missing[0].set_in, bare.covered) == (
        ("material",),
        "the part's `material` attr: {name, yield_mpa}",
        ("mass_kg",),
    )
    facts = {"material": {"name": "fake-6061", "yield_mpa": 276}}
    stated = SimQuestion(subject_id=bracket, quantity="stress_mpa", facts=facts)
    assert provider.can_answer(stated).names == ()
    known = {"material": SimInput(value={"name": "fake-6061", "yield_mpa": 276}, source="known")}
    assert provider.run(known).provenance.solver == "beam_bending"
    with pytest.raises(ValidationError):  # a question names its quantity the way the yaml does
        SimQuestion(subject_id=bracket, quantity="stress MPa")
