"""Checker eval on seeded-bug fixtures (SOLUS-CHK-01, SOLUSDEV-115).

The ticket's final acceptance criterion: run the rules over seeded-bug fixtures and report a
CATCH RATE (seeded bugs the rules flag) and a FALSE-POSITIVE RATE (warnings on clean graphs).
This module is that eval — it asserts every seeded bug is caught by its rule and every clean
control (including deliberately incomplete/unrelated graphs) stays silent, and prints the report.
"""

from dataclasses import dataclass

from fixtures.checker_graphs import CheckerCase, clean_cases, seeded_bug_cases
from solus_api.checkers.core import run_all
from solus_api.checkers.interface import Warning
from solus_api.fingerprint.contract import FingerprintOutput


def _parts() -> FingerprintOutput:
    return FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])


def _run(case: CheckerCase) -> list[Warning]:
    return run_all(case.graph, _parts())


@dataclass(frozen=True)
class EvalReport:
    """The catch/false-positive summary the acceptance criteria call for."""

    caught: int
    total_bugs: int
    clean_flagged: int
    total_clean: int
    spurious_warnings: int

    @property
    def catch_rate(self) -> float:
        return self.caught / self.total_bugs if self.total_bugs else 1.0

    @property
    def false_positive_rate(self) -> float:
        return self.clean_flagged / self.total_clean if self.total_clean else 0.0


def build_eval_report() -> tuple[EvalReport, list[str]]:
    """Run every fixture and return the report plus a human-readable per-case log."""
    bugs = seeded_bug_cases()
    cleans = clean_cases()
    lines: list[str] = ["", "=== SOLUS-CHK-01 checker eval ==="]

    caught = 0
    for case in bugs:
        found = _run(case)
        fired = {w.checker_id for w in found}
        hit = bool(fired & case.expected_checker_ids)
        caught += hit
        lines.append(
            f"[bug ] {case.name:<24} expected={sorted(case.expected_checker_ids)} "
            f"fired={sorted(fired)} -> {'CAUGHT' if hit else 'MISSED'}"
        )

    clean_flagged = 0
    spurious = 0
    for case in cleans:
        found = _run(case)
        if found:
            clean_flagged += 1
            spurious += len(found)
        lines.append(
            f"[clean] {case.name:<24} warnings={len(found)} "
            f"-> {'FALSE POSITIVE' if found else 'ok'}"
        )

    report = EvalReport(
        caught=caught,
        total_bugs=len(bugs),
        clean_flagged=clean_flagged,
        total_clean=len(cleans),
        spurious_warnings=spurious,
    )
    lines.append(
        f"catch_rate={report.catch_rate:.0%} ({report.caught}/{report.total_bugs})  "
        f"false_positive_rate={report.false_positive_rate:.0%} "
        f"({report.clean_flagged}/{report.total_clean}, {report.spurious_warnings} spurious)"
    )
    return report, lines


def test_every_seeded_bug_is_caught_by_its_rule() -> None:
    for case in seeded_bug_cases():
        fired = {w.checker_id for w in _run(case)}
        assert case.expected_checker_ids & fired, f"{case.name} not caught (fired={fired})"


def test_no_false_positives_on_clean_controls() -> None:
    for case in clean_cases():
        found = _run(case)
        assert found == [], f"{case.name} produced false positives: {[w.message for w in found]}"


def test_eval_report_is_perfect() -> None:
    report, lines = build_eval_report()
    print("\n".join(lines))
    assert report.catch_rate == 1.0
    assert report.false_positive_rate == 0.0
    assert report.spurious_warnings == 0
