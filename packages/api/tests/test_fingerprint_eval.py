"""FP-01 labeled eval: exact reproduction, the zero-false-merge hard gate, metrics.

The fixture labels ARE the spec (fixtures/fingerprint_labels.py). Doctrine:
every label reproduces exactly (like the MO-02 estimator fixtures), the
confusable set tolerates ZERO false merges, and the corpus metrics report
precision, recall, and — separately, never inside an F-score — the false-merge
count. Runs the pure matcher with NO escalation: this file passing IS the
"full eval passes with the LLM disabled" verify point.

False merge = one unordered pair of observations co-located in a predicted
CanonicalPart (any state — LOW_CONFIDENCE counts as merged) whose labels do
not co-locate them.
"""

import itertools
import uuid

import pytest
from fixtures.fingerprint_labels import ALL_CASES, CONFUSABLE_CASES, MATCHED_CASES, Case
from solus_api.fingerprint.config import load_fingerprint_config
from solus_api.fingerprint.contract import FingerprintOutput, SourceRef
from solus_api.fingerprint.matcher import Observation, match

_CFG = load_fingerprint_config()
_EVAL_NS = uuid.UUID("00000000-0000-0000-0000-00000000e7a1")


def _observation(case: Case, index: int) -> Observation:
    obs = case.observations[index]
    return Observation(
        source_ref=SourceRef(
            graph_entity_id=uuid.uuid5(_EVAL_NS, f"{case.case_id}:{obs.ref}"),
            source_connector=obs.source_connector,
            external_ref=obs.external_ref or obs.ref,
        ),
        modality=obs.modality,
        value=obs.value,
        manufacturer=obs.manufacturer,
        footprint=obs.footprint,
    )


def run_case(case: Case) -> FingerprintOutput:
    return match([_observation(case, i) for i in range(len(case.observations))], config=_CFG)


def _ref_of(case: Case, source_ref: SourceRef) -> str:
    by_id = {
        uuid.uuid5(_EVAL_NS, f"{case.case_id}:{obs.ref}"): obs.ref for obs in case.observations
    }
    assert source_ref.graph_entity_id in by_id, f"{case.case_id}: unknown source_ref"
    return by_id[source_ref.graph_entity_id]


class Predicted:
    """Output of one case mapped back to fixture refs."""

    def __init__(self, case: Case, output: FingerprintOutput) -> None:
        self.output = output
        self.groups: dict[frozenset[str], str] = {}  # refs → predicted part_number
        for part in output.canonical_parts:
            refs = frozenset(_ref_of(case, m.source_ref) for m in part.modalities)
            self.groups[refs] = part.part_number or ""
        self.unmatched = frozenset(_ref_of(case, r) for r in output.unmatched)
        self.ambiguous = frozenset(_ref_of(case, a.source_ref) for a in output.ambiguous)


def _pair_stats(case: Case, predicted: Predicted) -> tuple[int, int, int]:
    """(true-merge pairs, FALSE-MERGE pairs, missed-merge pairs) for one case."""
    predicted_pairs = {
        frozenset(pair)
        for refs in predicted.groups
        for pair in itertools.combinations(sorted(refs), 2)
    }
    expected_pairs = {
        frozenset(pair)
        for group in case.groups
        for pair in itertools.combinations(sorted(group.refs), 2)
    }
    true_merges = len(predicted_pairs & expected_pairs)
    false_merges = len(predicted_pairs - expected_pairs)
    missed_merges = len(expected_pairs - predicted_pairs)
    return true_merges, false_merges, missed_merges


# --- Exact reproduction: every label is spec ---------------------------------------


@pytest.mark.parametrize("case", ALL_CASES, ids=[c.case_id for c in ALL_CASES])
def test_labeled_case_reproduced(case: Case) -> None:
    predicted = Predicted(case, run_case(case))
    assert set(predicted.groups) == {group.refs for group in case.groups}, (
        f"{case.case_id}: predicted partition {sorted(map(sorted, predicted.groups))} != "
        f"labeled {sorted(sorted(g.refs) for g in case.groups)}"
    )
    for group in case.groups:
        if group.part_number is not None:
            assert predicted.groups[group.refs] == group.part_number, case.case_id
    assert predicted.unmatched == case.unmatched, case.case_id
    assert predicted.ambiguous == case.ambiguous, case.case_id
    part_ids = {part.canonical_id for part in predicted.output.canonical_parts}
    for ambiguous in predicted.output.ambiguous:
        assert len(ambiguous.candidate_canonical_ids) >= 1
        assert set(ambiguous.candidate_canonical_ids) <= part_ids, case.case_id
    conflict_refs = {
        _ref_of(case, m.source_ref)
        for part in predicted.output.canonical_parts
        for m in part.modalities
        if m.evidence.get("conflict") or m.evidence.get("package") or m.evidence.get("grade")
    }
    assert case.expect_conflict_in <= conflict_refs, (
        f"{case.case_id}: expected visible delta/conflict evidence on "
        f"{sorted(case.expect_conflict_in - conflict_refs)}"
    )


# --- The hard gate ------------------------------------------------------------------


@pytest.mark.parametrize("case", CONFUSABLE_CASES, ids=[c.case_id for c in CONFUSABLE_CASES])
def test_hard_gate_zero_false_merges(case: Case) -> None:
    """ZERO tolerance: a single false merge on the confusable set is a failure."""
    _, false_merges, _ = _pair_stats(case, Predicted(case, run_case(case)))
    assert false_merges == 0, f"{case.case_id}: {false_merges} FALSE MERGE PAIR(S)"


# --- Corpus metrics (for the completion report; run with -s to see the block) --------


def test_corpus_metrics_report_and_hard_gate() -> None:
    true_merges = false_merges = missed_merges = 0
    bucket_hits = bucket_total = 0
    for case in ALL_CASES:
        predicted = Predicted(case, run_case(case))
        tp, fp, fn = _pair_stats(case, predicted)
        true_merges += tp
        false_merges += fp
        missed_merges += fn
        grouped_labeled = {ref for group in case.groups for ref in group.refs}
        grouped_predicted = {ref for refs in predicted.groups for ref in refs}
        for obs in case.observations:
            bucket_total += 1
            if obs.ref in grouped_labeled:
                bucket_hits += obs.ref in grouped_predicted
            elif obs.ref in case.unmatched:
                bucket_hits += obs.ref in predicted.unmatched
            else:
                bucket_hits += obs.ref in predicted.ambiguous
    precision = true_merges / (true_merges + false_merges) if true_merges + false_merges else 1.0
    recall = true_merges / (true_merges + missed_merges) if true_merges + missed_merges else 1.0
    print(
        f"\nFP-01 eval: cases={len(ALL_CASES)} "
        f"(matched={len(MATCHED_CASES)} confusable={len(CONFUSABLE_CASES)})\n"
        f"pair_precision={precision:.3f}  pair_recall={recall:.3f}  "
        f"bucket_accuracy={bucket_hits / bucket_total:.3f}\n"
        f"FALSE MERGES: {false_merges}   (hard gate: 0 required)"
    )
    assert false_merges == 0, "HARD GATE: false-merge count must be ZERO"
    assert precision == 1.0 and recall == 1.0  # exact-reproduction doctrine


# --- Determinism at corpus level -------------------------------------------------------


def test_deterministic_across_runs() -> None:
    for case in ALL_CASES:
        first = run_case(case)
        second = run_case(case)
        assert first.model_dump_json() == second.model_dump_json(), case.case_id


# --- Red team: the hard gate must hold WITH escalation enabled --------------------------


def test_hard_gate_holds_with_adversarial_escalation() -> None:
    """Verify point 8's enabled half, corpus-wide: an adversarial escalator that
    'confirms' every unknown-format value as a SIBLING part's identity (the
    hallucinated-echo / one-sided-failure model) must not change a single
    bucket — LLM proposals are evidence, never partition changes."""
    import asyncio

    from solus_api.fingerprint.matcher import match_with_escalation

    for case in ALL_CASES:
        sibling_bases = [group.part_number for group in case.groups if group.part_number]

        async def escalate(value: str, _bases: list[str] = sibling_bases) -> str | None:
            others = [base for base in _bases if base != value.strip().upper()]
            return others[0] if others else None

        observations = [_observation(case, i) for i in range(len(case.observations))]
        escalated = asyncio.run(match_with_escalation(observations, escalate=escalate, config=_CFG))
        baseline = Predicted(case, run_case(case))
        attacked = Predicted(case, escalated)
        assert set(attacked.groups) == set(baseline.groups), case.case_id
        assert attacked.unmatched == baseline.unmatched, case.case_id
        assert attacked.ambiguous == baseline.ambiguous, case.case_id


# --- FP-03 red team: an adversarial photo can never change structured buckets ---------


def test_adversarial_photo_cannot_change_structured_buckets() -> None:
    """The FP-03 containment proof, corpus-wide (mirrors the adversarial
    escalator test): inject a photo observation reading "LM358" into EVERY eval
    case. Structured buckets must be identical modulo the photo ref; the
    part-number SET must be identical (a photo never mints a part); if the
    photo attached anywhere it is PHOTO + LOW_CONFIDENCE."""
    from solus_api.fingerprint.contract import MatchState, Modality
    from solus_api.fingerprint.matcher import Observation

    attack_id = uuid.uuid5(_EVAL_NS, "PHOTO-ATTACK")
    for case in ALL_CASES:
        observations = [_observation(case, i) for i in range(len(case.observations))]
        photo = Observation(
            source_ref=SourceRef(
                graph_entity_id=attack_id,
                source_connector="github",
                external_ref="PHOTO-ATTACK",
            ),
            modality=Modality.PHOTO,
            value="LM358",
        )
        baseline = run_case(case)
        attacked = match(observations + [photo], config=_CFG)

        def _refs(output: FingerprintOutput) -> dict[str, set[frozenset[str]]]:
            groups = set()
            for part in output.canonical_parts:
                refs = frozenset(
                    str(m.source_ref.graph_entity_id)
                    for m in part.modalities
                    if m.source_ref.graph_entity_id != attack_id
                )
                if refs:
                    groups.add(refs)
            return {
                "groups": groups,
                "unmatched": {
                    frozenset([str(r.graph_entity_id)])
                    for r in output.unmatched
                    if r.graph_entity_id != attack_id
                },
                "ambiguous": {
                    frozenset([str(a.source_ref.graph_entity_id)])
                    for a in output.ambiguous
                    if a.source_ref.graph_entity_id != attack_id
                },
            }

        assert _refs(attacked) == _refs(baseline), case.case_id
        assert {p.part_number for p in attacked.canonical_parts} == {
            p.part_number for p in baseline.canonical_parts
        }, f"{case.case_id}: a photo minted or destroyed a part"
        for part in attacked.canonical_parts:
            for m in part.modalities:
                if m.source_ref.graph_entity_id == attack_id:
                    assert m.modality is Modality.PHOTO
                    assert m.state is MatchState.LOW_CONFIDENCE, case.case_id
