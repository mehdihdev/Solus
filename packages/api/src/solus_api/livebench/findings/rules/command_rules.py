"""SOLUSDEV-321 P2-T2 — commands against the part's limits.

- `command_exceeds_limit`: a commanded position (the goal channel, `commanded_position`) past the
  position envelope's limit by more than the position tolerance — the config's `position_min` /
  `position_max`, the definition's, or the joint the scene binds to the part.
- `command_rate_exceeds_limit`: a commanded velocity (`commanded_velocity`) faster than the
  velocity envelope's limit (`velocity_max`), in either direction.

The code that commands the part is the one candidate cause (`software_command`). Both are WARNING.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    COMMAND,
    Cause,
    Needs,
    RuleHit,
    SignalRule,
    WindowContext,
    amount,
    entity_label,
    fact_need,
    is_new,
    judged,
    limit_hi,
    make_hit,
    past,
    readings,
    unmet,
    window_evidence,
)

COMMANDED_VELOCITY: Final = "commanded_velocity"


class CommandExceedsLimit:
    """A commanded position past the part's position limit."""

    rule_id = "command_exceeds_limit"
    matrix_cell: MatrixCell | None = MatrixCell.SOFTWARE_MECHANICAL
    needs = Needs(channels=(COMMAND,), facts=(fact_need("position", "limit"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("position")
        channel, samples = readings(ctx, COMMAND)
        if unmet(self.needs, ctx) or envelope is None or envelope.limit is None or channel is None:
            return []
        found = past(samples, envelope.limit, ctx.tolerance, judged(ctx, channel))
        if not found:
            return []
        worst, edge, side = max(found, key=lambda item: abs(item[0].value - item[1]))
        unit, source = envelope.unit, envelope.bounds_source.get("limit")
        evidence = {
            "commanded": worst.value,
            "bound": edge,
            "side": side,
            "bounds_source": source,
            "tolerance": ctx.tolerance,
            "unit": unit,
            "samples": len(found),
            **window_evidence(found[0][0].timestamp, found[-1][0].timestamp),
        }
        said = f"commanded to {amount(worst.value, unit)}, past its {amount(edge, unit)} limit"
        cause = Cause(
            kind="software_command",
            for_=(
                f"the code asks for {amount(worst.value, unit)}; the {side} limit is "
                f"{amount(edge, unit)} (from {source})",
            ),
        )
        headline = f"{entity_label(ctx.graph, ctx.part_id)} {said}"
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=(cause,))]


class CommandRateExceedsLimit:
    """A commanded velocity over the part's velocity limit."""

    rule_id = "command_rate_exceeds_limit"
    matrix_cell: MatrixCell | None = MatrixCell.SOFTWARE_MECHANICAL
    needs = Needs(channels=(COMMANDED_VELOCITY,), facts=(fact_need("velocity", "limit"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("velocity")
        channel, samples = readings(ctx, COMMANDED_VELOCITY)
        top = limit_hi(envelope)
        if unmet(self.needs, ctx) or envelope is None or top is None or channel is None:
            return []
        cut = judged(ctx, channel)
        fast = [s for s in samples if abs(s.value) > top and is_new(s.timestamp, cut)]
        if not fast:
            return []
        worst = max(fast, key=lambda sample: abs(sample.value))
        unit, source = envelope.unit, envelope.bounds_source.get("limit")
        speed = abs(worst.value)
        evidence = {
            "commanded_velocity": worst.value,
            "speed": speed,
            "bound": top,
            "bounds_source": source,
            "unit": unit,
            "samples": len(fast),
            **window_evidence(fast[0].timestamp, fast[-1].timestamp),
        }
        said = f"commanded at {amount(speed, unit)}, over its {amount(top, unit)} velocity limit"
        cause = Cause(
            kind="software_command",
            for_=(
                f"the code asks for {amount(speed, unit)}; the limit is "
                f"{amount(top, unit)} (from {source})",
            ),
        )
        headline = f"{entity_label(ctx.graph, ctx.part_id)} {said}"
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=(cause,))]


COMMAND_RULES: Final[tuple[SignalRule, ...]] = (CommandExceedsLimit(), CommandRateExceedsLimit())
