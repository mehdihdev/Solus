"""SOLUSDEV-321 P2-T2 — the body: what the part's mechanism and its own controller report.

- `body_lag`: the actuator reports it reached its target (its position within the tolerance of an
  unchanged command, and still, for `BODY_LAG_MIN_SECONDS`) while a motion sensor on its output
  link — a structure the part `mates_with` that `mounts` the sensor — still moves more than that
  tolerance. The sensor's position is read in the part's position unit; its spread is compared,
  not its value, so a calibration offset between the two does not count.
- `error_flag`: the device raises an error flag (a nonzero `overload_flag`, `voltage_flag` or
  `overheat_flag` sample): overload points at the command or the mechanism, voltage at the rail,
  overheat at heat. CRITICAL for overload or voltage, WARNING for overheat alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    COMMAND,
    MIN_ROWS,
    Cause,
    CauseKind,
    Needs,
    RuleHit,
    SignalRule,
    WindowContext,
    amount,
    blame,
    channel_for,
    entity_label,
    is_new,
    judged,
    linked,
    make_hit,
    paired,
    peer_readings,
    readings,
    shown,
    since,
    unmet,
    window_evidence,
)

if TYPE_CHECKING:
    from solus_api.graph.packet import RecentSample

#: The actuator must hold at its target this long before the link is judged against it.
BODY_LAG_MIN_SECONDS: Final = 0.5
#: (flag quantity, the flag's name), the most severe first.
FLAGS: Final = (
    ("overload_flag", "overload"),
    ("voltage_flag", "voltage"),
    ("overheat_flag", "overheat"),
)
#: flag -> what it points at: (cause kind, what that cause would be).
_FLAG_CAUSES: Final[dict[str, tuple[tuple[CauseKind, str], ...]]] = {
    "overload": (
        ("software_command", "a command into a stop, or too fast"),
        ("mechanical_load", "a load beyond the part's torque"),
    ),
    "voltage": (("electrical_supply", "the rail outside the part's range"),),
    "overheat": (
        ("mechanical_load", "a sustained load"),
        ("actuator", "cooling or duty cycle beyond its rating"),
    ),
}
#: flag -> (the quantity read beside it, its evidence key, how the reading is said).
_FLAG_READING: Final = {
    "overload": ("current", "current_a", "while drawing {}"),
    "voltage": ("voltage", "voltage", "at {} input"),
    "overheat": ("temperature", "temperature", "at {}"),
}

type RestRow = tuple[datetime, float, float]  # (time, position, command)


def _link_sensors(ctx: WindowContext) -> list[tuple[UUID, str, tuple[RecentSample, ...]]]:
    """(sensor, its position channel, its samples) for each peer mounted on a structure the part
    mates with — its output link — that streams a position."""
    part = ctx.part_id
    links = {
        *linked(ctx.graph, RelationType.MATES_WITH, part),
        *linked(ctx.graph, RelationType.MATES_WITH, part, into=False),
    }
    mounted = {
        s for link in links for s in linked(ctx.graph, RelationType.MOUNTS, link, into=False)
    }
    found: list[tuple[UUID, str, tuple[RecentSample, ...]]] = []
    for sensor in sorted(mounted - {part}, key=str):
        channel, samples = peer_readings(ctx, sensor, "position")
        if channel is not None:
            found.append((sensor, channel, samples))
    return found


def _at_rest(rows: Sequence[RestRow], tolerance: float) -> list[RestRow]:
    """The first run at the target: the position within `tolerance` of an unchanged command and
    of where the run began, `MIN_ROWS` or more over `BODY_LAG_MIN_SECONDS`."""
    run: list[RestRow] = []
    for row in rows:
        _, position, command = row
        if abs(command - position) > tolerance:
            run = []
            continue
        if run and max(abs(position - run[0][1]), abs(command - run[0][2])) > tolerance:
            run = []
        run.append(row)
        if len(run) >= MIN_ROWS and (row[0] - run[0][0]).total_seconds() >= BODY_LAG_MIN_SECONDS:
            return run
    return []


def _motion(samples: Sequence[RecentSample], start: datetime, end: datetime) -> float:
    """How far the samples between `start` and `end` spread (0 under two)."""
    values = [s.value for s in samples if start <= s.timestamp <= end]
    return max(values) - min(values) if len(values) > 1 else 0.0


class BodyLag:
    """The actuator says it is there; a motion sensor on its output link says the link moves."""

    rule_id = "body_lag"
    matrix_cell: MatrixCell | None = MatrixCell.MECHANICAL_MECHANICAL
    needs = Needs(
        channels=("position", COMMAND),
        relations=(RelationType.MATES_WITH.value, RelationType.MOUNTS.value),
    )

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        position_channel = channel_for(ctx.samples, "position")
        command_channel = channel_for(ctx.samples, COMMAND)
        sensors = _link_sensors(ctx)
        if unmet(self.needs, ctx) or not sensors or position_channel is None or not command_channel:
            return []
        rows: list[RestRow] = [(at, p, c) for at, p, c in paired(ctx, "position", COMMAND)]
        cut = judged(ctx, position_channel, command_channel)
        rest = _at_rest(since(rows, cut, BODY_LAG_MIN_SECONDS), ctx.tolerance)
        if not rest:
            return []
        moving = [
            (motion, sensor, channel)
            for sensor, channel, samples in sensors
            if (motion := _motion(samples, rest[0][0], rest[-1][0])) > ctx.tolerance
        ]
        if not moving:
            return []
        motion, sensor, channel = max(moving, key=lambda found: found[0])
        return [self._lagging(ctx, rest, sensor, channel, motion)]

    def _lagging(
        self, ctx: WindowContext, rest: Sequence[RestRow], sensor: UUID, channel: str, motion: float
    ) -> RuleHit:
        envelope = ctx.envelopes.get("position")
        unit = envelope.unit if envelope is not None else None
        evidence = {
            "sensor": str(sensor),
            "sensor_channel": shown(channel),
            "sensor_motion": motion,
            "position": rest[-1][1],
            "commanded": rest[-1][2],
            "tolerance": ctx.tolerance,
            "unit": unit,
            "samples": len(rest),
            **window_evidence(rest[0][0], rest[-1][0]),
        }
        name, mounted = entity_label(ctx.graph, ctx.part_id), entity_label(ctx.graph, sensor)
        headline = (
            f"{name} reports it reached {amount(rest[-1][2], unit)} but {mounted} on its output "
            f"link still moves {amount(motion, unit)}"
        )
        causes = (
            Cause(
                kind="mechanical_load",
                for_=(
                    f"{mounted} moves {amount(motion, unit)} while {name} holds within "
                    f"{amount(ctx.tolerance, unit)}: compliance or backlash between them",
                ),
            ),
            Cause(
                kind="actuator",
                for_=(f"{name} reads its own output, not the link, so its feedback says done",),
            ),
        )
        blamed, _ = blame(ctx, ctx.part_id)
        subjects = tuple(dict.fromkeys((*blamed, sensor)))
        return make_hit(
            self, ctx, headline=headline, evidence=evidence, causes=causes, subjects=subjects
        )


def _flag_causes(flags: Sequence[str], notes: Mapping[str, str]) -> tuple[Cause, ...]:
    """One cause per kind the raised flags point at, each saying which flag and what it read."""
    said: dict[CauseKind, list[str]] = {}
    for flag in flags:
        reading = f" {notes[flag]}" if flag in notes else ""
        for kind, means in _FLAG_CAUSES[flag]:
            said.setdefault(kind, []).append(f"the {flag} flag is up{reading}: {means}")
    return tuple(Cause(kind=kind, for_=tuple(texts)) for kind, texts in said.items())


class ErrorFlag:
    """The device's own error flags: overload, voltage, overheat."""

    rule_id = "error_flag"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs()  # any of the three flags; a part that reports none has nothing to judge

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        flags = evidence.get("flags") or ()
        return Severity.CRITICAL if "overload" in flags or "voltage" in flags else Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        raised: list[tuple[str, list[RecentSample]]] = []
        for quantity, flag in FLAGS:
            channel, samples = readings(ctx, quantity)
            cut = judged(ctx, channel) if channel is not None else None
            up = [s for s in samples if s.value != 0 and is_new(s.timestamp, cut)]
            if up:
                raised.append((flag, up))
        if unmet(self.needs, ctx) or not raised:
            return []
        flags = [flag for flag, _ in raised]
        up = sorted((s for _, samples in raised for s in samples), key=lambda s: s.timestamp)
        evidence: dict[str, Any] = {
            "flags": flags,
            "samples": len(up),
            **window_evidence(up[0].timestamp, up[-1].timestamp),
        }
        notes: dict[str, str] = {}
        for flag in flags:
            quantity, key, phrase = _FLAG_READING[flag]
            _, values = readings(ctx, quantity)
            if values:
                envelope = ctx.envelopes.get(quantity)
                value = abs(values[-1].value) if quantity == "current" else values[-1].value
                evidence[key] = value
                notes[flag] = phrase.format(amount(value, envelope.unit if envelope else None))
        plural = "s" if len(flags) > 1 else ""
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} raised its {' and '.join(flags)} error "
            f"flag{plural}"
        )
        causes = _flag_causes(flags, notes)
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


BODY_RULES: Final[tuple[SignalRule, ...]] = (BodyLag(), ErrorFlag())
