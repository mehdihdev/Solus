"""SOLUSDEV-321 P2-T2 — electrical: what the part draws and what its supply does about it.

- `current_over_rating`: the current's magnitude over the envelope's limit (the rating) for
  `OVER_RATING_MIN_SAMPLES` samples in a row. CRITICAL.
- `rail_sag_correlated`: while the part's current peaks over its nominal bound, its input voltage
  drops with it: over the last `RAIL_SAG_WINDOW_SECONDS` the Pearson correlation of current and
  voltage is at or below -`RAIL_SAG_MIN_CORRELATION`, and the voltage nearest the peak is
  `RAIL_SAG_MIN_DROP` of its median below that median. The parts sharing the part's `powers` rail
  (else the bus that `drives` it) are judged against the same peak: every one sags → the supply or
  the rail's wiring (`rail`); some → the wiring they share (`segment`); none → this part's cable
  (`cable`); no sharer streams a voltage → the part alone is named (`part`). WARNING.
- `controller_reset_under_load`: the part's `reset_count` steps up while its current, within the
  `RESET_LOAD_LOOKBACK_SECONDS` before, reached its nominal bound — a brownout. WARNING.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any, Final
from uuid import UUID

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    Cause,
    Needs,
    Point,
    RuleHit,
    SignalRule,
    WindowContext,
    aligned,
    amount,
    blame,
    entity_label,
    fact_need,
    is_new,
    judged,
    limit_hi,
    linked,
    make_hit,
    peer_readings,
    points,
    readings,
    runs,
    trailing,
    unit_of,
    unmet,
    window_evidence,
)

OVER_RATING_MIN_SAMPLES: Final = 3
RAIL_SAG_WINDOW_SECONDS: Final = 5.0
RAIL_SAG_MIN_SAMPLES: Final = 10
RAIL_SAG_MIN_CORRELATION: Final = 0.6
#: The share of its median a voltage drops at the peak before it is a sag.
RAIL_SAG_MIN_DROP: Final = 0.03
RESET_LOAD_LOOKBACK_SECONDS: Final = 1.0


class CurrentOverRating:
    """The current over the part's rating."""

    rule_id = "current_over_rating"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_ELECTRICAL
    needs = Needs(channels=("current",), facts=(fact_need("current", "limit"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.CRITICAL

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("current")
        top = limit_hi(envelope)
        channel, samples = readings(ctx, "current")
        if unmet(self.needs, ctx) or envelope is None or top is None or channel is None:
            return []
        cut = judged(ctx, channel)
        over = next(
            (
                run
                for run in runs(points(samples, magnitude=True), lambda point: point[1] > top)
                if len(run) >= OVER_RATING_MIN_SAMPLES and is_new(run[-1][0], cut)
            ),
            None,
        )
        if over is None:
            return []
        drawn, unit, source = max(point[1] for point in over), envelope.unit, envelope.bounds_source
        evidence = {
            "current_a": drawn,
            "bound": top,
            "limit": top,
            "bounds_source": source.get("limit"),
            "unit": unit,
            "samples": len(over),
            **window_evidence(over[0][0], over[-1][0]),
        }
        rating = f"the {amount(top, unit)} rating"
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} current {amount(drawn, unit)} over {rating}"
        )
        causes = (
            Cause(
                kind="mechanical_load",
                for_=(
                    f"drawing {amount(drawn, unit)} over {rating}: more load than it moves freely",
                ),
            ),
            Cause(kind="software_command", for_=("a command into a stop, or too fast, draws it",)),
            Cause(
                kind="actuator", for_=("a failing motor or driver draws more for the same work",)
            ),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


@dataclass(frozen=True)
class Sag:
    """How one voltage moved with the part's current: their correlation, the voltage nearest the
    peak, and how far that is under the window's median."""

    correlation: float
    at_peak: float
    drop: float


def _sag_of(current: Sequence[Point], voltage: Sequence[Point], peak: datetime) -> Sag | None:
    """The voltage's sag against the current over the window; None unless it sags (correlation
    at or below -`RAIL_SAG_MIN_CORRELATION`, down `RAIL_SAG_MIN_DROP` of its median at the peak)."""
    rows = aligned(current, voltage)
    if len(rows) < RAIL_SAG_MIN_SAMPLES:
        return None
    volts = [row[2] for row in rows]
    try:
        correlation = statistics.correlation([row[1] for row in rows], volts)
    except statistics.StatisticsError:  # a flat current or voltage moves with nothing
        return None
    nearest = min(rows, key=lambda row: abs((row[0] - peak).total_seconds()))[2]
    typical = statistics.median(volts)
    drop = typical - nearest
    if (
        correlation > -RAIL_SAG_MIN_CORRELATION
        or typical <= 0
        or drop < RAIL_SAG_MIN_DROP * typical
    ):
        return None
    return Sag(correlation, nearest, drop)


def _sharing(ctx: WindowContext) -> tuple[UUID | None, str | None, list[UUID]]:
    """(the rail, the relation it was found by, the other parts on it): the `powers` source the
    part has, else the bus that `drives` it; (None, None, []) with neither."""
    for relation in (RelationType.POWERS, RelationType.DRIVES):
        rails = linked(ctx.graph, relation, ctx.part_id)
        if rails:
            others = linked(ctx.graph, relation, rails[0], into=False)
            return rails[0], relation.value, [p for p in others if p != ctx.part_id]
    return None, None, []


def _voltage_of(ctx: WindowContext, peer: UUID) -> list[Point]:
    return points(peer_readings(ctx, peer, "voltage")[1])


def _sag_scope(sharers: int, sagging: int) -> str:
    """`rail`: every sharer sags with the part; `segment`: some; `cable`: none; `part`: no sharer
    streams a voltage to judge."""
    if not sharers:
        return "part"
    if sagging == sharers:
        return "rail"
    return "segment" if sagging else "cable"


class RailSagCorrelated:
    """The input voltage sags with the part's current; who else sags says where."""

    rule_id = "rail_sag_correlated"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_ELECTRICAL
    needs = Needs(channels=("current", "voltage"), facts=(fact_need("current", "nominal"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("current")
        nominal = envelope.nominal if envelope is not None else None
        channel, samples = readings(ctx, "current")
        if (
            unmet(self.needs, ctx)
            or not envelope
            or not nominal
            or nominal.hi is None
            or not channel
        ):
            return []
        current = trailing(points(samples, magnitude=True), RAIL_SAG_WINDOW_SECONDS)
        top = max(reversed(current), key=lambda point: point[1], default=None)  # the latest peak
        if top is None or top[1] < nominal.hi or not is_new(top[0], judged(ctx, channel)):
            return []
        own = _sag_of(current, points(readings(ctx, "voltage")[1]), top[0])
        if own is None:
            return []
        rail, via, shared = _sharing(ctx)
        measured = {peer: volts for peer in shared if (volts := _voltage_of(ctx, peer))}
        sagging = [peer for peer, volts in measured.items() if _sag_of(current, volts, top[0])]
        evidence = {
            "current_a": top[1],
            "bound": nominal.hi,
            "bounds_source": envelope.bounds_source.get("nominal"),
            "voltage": own.at_peak,
            "voltage_drop": own.drop,
            "correlation": own.correlation,
            "scope": _sag_scope(len(measured), len(sagging)),
            "via": via,
            "rail": str(rail) if rail is not None else None,
            "sharers": len(measured),
            "sagging": [str(peer) for peer in sagging],
            "current_unit": envelope.unit,
            "unit": unit_of(ctx, "voltage"),
            **window_evidence(current[0][0], current[-1][0]),
        }
        return [self._sagged(ctx, evidence, rail, sagging)]

    def _sagged(
        self,
        ctx: WindowContext,
        evidence: Mapping[str, Any],
        rail: UUID | None,
        sagging: list[UUID],
    ) -> RuleHit:
        name, scope = entity_label(ctx.graph, ctx.part_id), evidence["scope"]
        drawn = amount(evidence["current_a"], evidence["current_unit"])
        drop = amount(evidence["voltage_drop"], evidence["unit"])
        on = entity_label(ctx.graph, rail) if rail is not None else ""
        # counts are of the parts that stream a voltage (`evidence.sharers`), the part included
        sharers, together = evidence["sharers"], len(sagging) + 1
        others = f"{sharers} other measured part{'s' if sharers > 1 else ''}"
        said = {
            "rail": (
                f"{on} sags: all {together} measured parts on it drop when {name} draws {drawn}",
                f"all {together} measured parts on {on} drop together: the supply or the rail's "
                "wiring",
            ),
            "segment": (
                f"{together} of {sharers + 1} measured parts on {on} sag when {name} draws "
                f"{drawn}: the wiring they share",
                f"{together} of {sharers + 1} measured parts on {on} drop together: the wiring "
                "they share",
            ),
            "cable": (
                f"{name} input sags {drop} when it draws {drawn} while the {others} on {on} "
                f"hold{'' if sharers > 1 else 's'}: its cable",
                f"only {name}'s input drops ({drop}) while the {others} on {on} hold: its cable "
                "or connector",
            ),
            "part": (
                f"{name} input sags {drop} when it draws {drawn}",
                f"{name}'s input drops {drop} as it draws {drawn} "
                f"(r = {evidence['correlation']:.2f})",
            ),
        }
        headline, because = said[scope]
        blamed, _ = blame(ctx, ctx.part_id)
        subjects = {
            "rail": (rail, ctx.part_id, *sagging),
            "segment": (rail, ctx.part_id, *sagging),
            "cable": (ctx.part_id, rail),
        }.get(scope, blamed)
        return make_hit(
            self,
            ctx,
            headline=headline,
            evidence=evidence,
            causes=(Cause(kind="electrical_supply", for_=(because,)),),
            subjects=tuple(dict.fromkeys(s for s in subjects if s is not None)),
        )


def _load_before(current: Sequence[Point], at: datetime) -> float:
    """The most current drawn in the `RESET_LOAD_LOOKBACK_SECONDS` up to `at` (0 with none)."""
    return max(
        (
            value
            for timestamp, value in current
            if 0 <= (at - timestamp).total_seconds() <= RESET_LOAD_LOOKBACK_SECONDS
        ),
        default=0.0,
    )


class ControllerResetUnderLoad:
    """The part's controller restarts while it draws over its nominal current."""

    rule_id = "controller_reset_under_load"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs(channels=("reset_count", "current"), facts=(fact_need("current", "nominal"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("current")
        nominal = envelope.nominal if envelope is not None else None
        counter, counts = readings(ctx, "reset_count")
        if (
            unmet(self.needs, ctx)
            or not envelope
            or not nominal
            or nominal.hi is None
            or not counter
        ):
            return []
        current = points(readings(ctx, "current")[1], magnitude=True)
        cut = judged(ctx, counter)
        loaded = [
            (after.timestamp, load)
            for before, after in pairwise(counts)
            if after.value > before.value
            and is_new(after.timestamp, cut)
            and (load := _load_before(current, after.timestamp)) >= nominal.hi
        ]
        if not loaded:
            return []
        drawn, unit = max(load for _, load in loaded), envelope.unit
        evidence = {
            "resets": len(loaded),
            "current_a": drawn,
            "bound": nominal.hi,
            "bounds_source": envelope.bounds_source.get("nominal"),
            "unit": unit,
            **window_evidence(loaded[0][0], loaded[-1][0]),
        }
        times = f"{len(loaded)} time{'s' if len(loaded) > 1 else ''}"
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} controller restarted {times} while drawing "
            f"{amount(drawn, unit)} (nominal {amount(nominal.hi, unit)})"
        )
        under = f"while drawing {amount(drawn, unit)}, over the {amount(nominal.hi, unit)} nominal"
        causes = (
            Cause(kind="electrical_supply", for_=(f"it restarted {under}: a brownout",)),
            Cause(
                kind="software_command",
                for_=("a firmware watchdog or fault handler restarts a controller too",),
                against=(f"it restarted {under}",),
            ),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


ELECTRICAL_RULES: Final[tuple[SignalRule, ...]] = (
    CurrentOverRating(),
    RailSagCorrelated(),
    ControllerResetUnderLoad(),
)
