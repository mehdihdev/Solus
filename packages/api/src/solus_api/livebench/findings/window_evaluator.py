"""SOLUSDEV-321 P2-T3 — the window evaluator: a robot bench session's own ticker over what its
parts stream, raising what the live-signal rules (`rules.SIGNAL_RULES`) find as findings.

A telemetry window closes only when a later packet crosses it, so a silent robot closes none: a
stall that stops the stream, and the stream stopping, need the wall clock. `start` runs one task
per session that ticks every `tick_seconds`; a tick that raises is logged and the next one runs.
A tick, in ONE transaction:

1. reads each live part's new samples from the telemetry buffer by EVENT time: a channel's cursor
   is the newest event time read on it, and `recent(since=cursor)` keeps what is at or after it
   (the packet's own timestamp), so the sample at the cursor is dropped as seen — a wall-clock
   `since` would miss a replayed or clock-skewed device. A sample dated more than
   `MAX_FUTURE_SKEW_SECONDS` (5 s) past the tick's clock is dropped before it moves a cursor or
   reaches a rule. A first read starts where the session first saw the channel
   (`SessionView.parts`) or, when that first packet is itself dated past the skew, at the ring's
   start, so an earlier session's leftovers can be judged once. A sample in another unit than its
   envelope's is converted when `convert_unit` scales between the two (a simulated joint's rad
   against a real part's deg) and dropped otherwise. Each drop is logged once a channel;
2. loads the parts' envelopes — through the ONE `EnvelopeCache` the graph-changed fan-out drops,
   with the robot's baseline run for the learned bounds (M56) — and the graph around the parts
   through `to_graph_context`;
3. judges the new samples in `tick_seconds`-wide event-time windows, so a fast replay's minute is
   sixty windows, as real time would have had (a silent tick is one window, where only
   `stream_gap`, the one wall-clock rule, can fire). A part's `WindowContext` holds each channel's
   last `TREND_HORIZON_SECONDS` (every streamed or configured channel a key), the cursor before
   the window (`judged_through`), the session's other parts (`peers`) and its latest hit per rule
   (`prior_hits`). Rules run until the window has spent its CPU budget (`time.perf_counter`):
   `cpu_budget_ms` (20 ms) or, when more, `cpu_budget_ms_per_part` (10 ms) for each part the session
   streams. The rest are skipped and counted in one log line a tick, and the next tick starts at
   the first rule skipped, so while at least half the rules fit, every rule runs in any two
   consecutive ticks.
   A rule that raises is skipped, said once;
4. coalesces each window's hits per subject — a hit's first subject, what it is about — into the
   highest-precedence rule's (`PRECEDENCE`), the folded ids in `evidence.also`: a stall is one
   finding on its servo, while another subject or a later window raises its own;
5. raises each through `raise_finding` (`source="observer"`, `bucket=str(session_id)`: a session's
   re-raise bumps one node's `count`) and records on the robot what the rules could not judge for
   want of a channel, relation or fact (`attrs.missing_signals`: a part is assessed at its first
   window with samples and again when its channels grow; the list is written when it changes).

After the commit: a marker on the bench event ring for each channel of a finding's part at its
first raise this session, the finding id attached server-side; then `on_raised(robot_id,
finding_ids)`, the narration's hook, whose failure never stops observation. Shared code: no vendor,
connector or simulator name (the hygiene ratchets sweep this package).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from bisect import bisect_left, bisect_right
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from pydantic import ValidationError
from solus_contracts.relations import RelationType
from sqlalchemy import select

from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.graph.neighborhood import load_neighborhood, to_graph_context
from solus_api.livebench.bench_router import ObserverEventIn
from solus_api.livebench.findings.envelopes import (
    QUANTITIES,
    EnvelopeKey,
    build_envelope,
    canonical_unit,
    convert_unit,
    load_envelope_inputs,
)
from solus_api.livebench.findings.rules.rule_base import (
    TREND_HORIZON_SECONDS,
    RuleHit,
    WindowContext,
    entity_label,
    unmet,
)
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.analysis import _STILL_TOLERANCE
from solus_api.livebench.scene.part_bindings import channel_for_quantity
from solus_api.models import Domain, GraphEntity, utcnow
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.services.solus_graph import lock_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.graph.buffer import TelemetryBuffer
    from solus_api.graph.packet import RecentSample
    from solus_api.hardware.config import PartConfig
    from solus_api.livebench.bench_router import BenchEventRing
    from solus_api.livebench.findings.envelopes import Envelope, EnvelopeCache, EnvelopeInputs
    from solus_api.livebench.findings.rules.rule_base import SignalRule
    from solus_api.livebench.runs.models import RunManifest
    from solus_api.livebench.sessions import SessionView
    from solus_api.storage import ArtifactStore

logger = logging.getLogger("solus.livebench.findings.window_evaluator")

#: One subject's hits in a window are one finding: the first of these rules' (the mechanism before
#: the symptom; the plan's partial order kept inside), the others named in `evidence.also`. A rule
#: this does not list comes after all of them.
PRECEDENCE: Final = (
    "tracking_error_stall",
    "tracking_error_slip",
    "tracking_oscillation",
    "body_lag",
    "error_flag",
    "current_over_rating",
    "controller_reset_under_load",
    "rail_sag_correlated",
    "command_exceeds_limit",
    "command_rate_exceeds_limit",
    "temp_trend_to_limit",
    "time_to_limit",
    "noise_tracks_motor_activity",
    "sensor_frozen",
    "sensor_out_of_range",
    "rate_drift",
    "stream_gap",
)
#: The robot's `missing_signals` lists at most this many `<part>: <need>` lines.
MAX_MISSING_SIGNALS: Final = 64
#: A sample dated more than this past the evaluator's wall clock is a device's clock glitch: it is
#: dropped before it moves its channel's cursor, the frontier or any rule (said once a channel),
#: or one far-future timestamp would park the cursor there and blind the channel for the session.
MAX_FUTURE_SKEW_SECONDS: Final = 5.0
#: Samples a channel keeps between ticks: `TREND_HORIZON_SECONDS` of history up to ~273 Hz.
#: ponytail: an 8192-sample ceiling per channel; a faster channel keeps less than the horizon —
#: raise it (or decimate) when a rule needs the whole span of one.
MAX_HISTORY_SAMPLES: Final = 8192
#: What the rules walk, each within two hops of a part: blame (`drives`, `hardware_connected_to`,
#: `commands`), a rail's sharers (`powers`), an output link's sensors (`mates_with`, `mounts`), a
#: sensor's readers (`reads`). Nothing else (findings, containment) crowds the bounded read.
RELATIONS: Final[tuple[str, ...]] = (
    RelationType.DRIVES,
    RelationType.HARDWARE_CONNECTED_TO,
    RelationType.COMMANDS,
    RelationType.POWERS,
    RelationType.MATES_WITH,
    RelationType.MOUNTS,
    RelationType.READS,
)
_HORIZON: Final = timedelta(seconds=TREND_HORIZON_SECONDS)
_RANK: Final = {rule_id: rank for rank, rule_id in enumerate(PRECEDENCE)}
_ENVELOPES: Final = default_orchestration_config().envelopes

type Hit = tuple[UUID, RuleHit]  # a hit, with the part whose window showed it


@dataclass
class _Track:
    """One part between ticks, per channel: its history (oldest first), cursor (the newest event
    time read), last arrival (wall clock) and latest hit per rule id."""

    history: dict[str, list[RecentSample]] = field(default_factory=dict)
    cursor: dict[str, datetime] = field(default_factory=dict)
    arrived: dict[str, datetime] = field(default_factory=dict)
    prior: dict[str, RuleHit] = field(default_factory=dict)


@dataclass(frozen=True)
class _Tick:
    """One tick's reads: the session, the wall clock, the CPU budget of each of its windows, the
    graph around the parts (its entities by id), and per live part its envelopes by quantity, its
    channels and its position tolerance."""

    view: SessionView
    now: datetime
    budget_ms: float
    graph: GraphContext
    entities: dict[UUID, EntityRead]
    envelopes: dict[UUID, dict[str, Envelope]]
    channels: dict[UUID, tuple[str, ...]]
    tolerance: dict[UUID, float]


@dataclass(frozen=True)
class _Found:
    """A window's finding: the part whose window showed it, the winning hit, the rule ids folded
    into it, and the part's newest event time per channel in that window (where markers go)."""

    part_id: UUID
    hit: RuleHit
    also: tuple[str, ...]
    seen: dict[str, datetime]


def coalesce(hits: Iterable[Hit]) -> list[tuple[UUID, RuleHit, tuple[str, ...]]]:
    """One window's hits, one per subject (a hit's first subject, what it is about): the
    highest-precedence rule's, with the other rules' ids in precedence order."""
    by_subject: dict[UUID, list[Hit]] = {}
    for part, hit in hits:
        by_subject.setdefault(hit.subjects[0] if hit.subjects else part, []).append((part, hit))
    folded: list[tuple[UUID, RuleHit, tuple[str, ...]]] = []
    for group in by_subject.values():
        ranked = sorted(group, key=lambda item: _RANK.get(item[1].rule_id, len(_RANK)))
        (part, best), rest = ranked[0], ranked[1:]
        also = tuple(dict.fromkeys(hit.rule_id for _, hit in rest if hit.rule_id != best.rule_id))
        folded.append((part, best, also))
    return folded


def window_ends(base: datetime, fresh: Sequence[datetime], width: float) -> list[datetime]:
    """Where the event-time windows holding the new samples (`fresh`) end: `base` (the newest time
    judged before, else the oldest of them) to the newest, cut into about `width` seconds each,
    only those holding a sample — one far-off timestamp is one more window, never a million."""
    newest = max(fresh)
    span = (newest - base).total_seconds()
    count = max(1, round(span / width))
    step = span / count
    indices = {
        min(count, max(1, math.ceil((at - base).total_seconds() / step))) if step > 0 else count
        for at in fresh
    }
    return [newest if k == count else base + timedelta(seconds=step * k) for k in sorted(indices)]


def _stamp(sample: RecentSample) -> datetime:
    return sample.timestamp


def _where(view: SessionView) -> str:
    return f"project={view.project_id} session={view.session_id}"


def _visible(rows: Sequence[RecentSample], end: datetime | None) -> tuple[RecentSample, ...]:
    """A channel as the window ending at `end` shows it (`None`: all of it): the samples up to
    `end`, the last `TREND_HORIZON_SECONDS` before the newest of them."""
    stop = len(rows) if end is None else bisect_right(rows, end, key=_stamp)
    if not stop:
        return ()
    return tuple(rows[bisect_left(rows, rows[stop - 1].timestamp - _HORIZON, key=_stamp) : stop])


def _in_unit(sample: RecentSample, unit: str | None) -> RecentSample | None:
    """`sample` in `unit`: as it is when either states no unit or they agree, converted when the
    scale table knows the pair, None when it does not (a sample nothing can compare)."""
    if not (unit and sample.unit):
        return sample
    source = canonical_unit(sample.unit)
    if source == unit:
        return sample
    converted = convert_unit(sample.value, source, unit)
    if converted is None:
        return None
    return sample.model_copy(update={"value": converted, "unit": unit})


def _newest(samples: Mapping[str, Sequence[RecentSample]]) -> dict[str, datetime]:
    return {channel: rows[-1].timestamp for channel, rows in samples.items() if rows}


def _all_channels(streamed: Mapping[str, datetime], config: PartConfig | None) -> tuple[str, ...]:
    declared = [channel.name for channel in config.telemetry] if config is not None else []
    return tuple(dict.fromkeys([*streamed, *declared]))


def _tolerance(envelopes: Mapping[str, Envelope], config: PartConfig | None) -> float:
    """The part's position tolerance in its position unit — the run analysis's still thresholds
    (rad 0.01, deg 0.5, m 0.001); 0.0 for a unit they do not name (positions compare exactly)."""
    position = envelopes.get("position")
    if position is not None:
        unit = position.unit
    else:
        channel = channel_for_quantity(config.telemetry, "position") if config else None
        unit = canonical_unit(channel.unit) if channel is not None else None
    return _STILL_TOLERANCE.get(unit or "", 0.0)


def _finding_evidence(
    view: SessionView, item: _Found, sources: Mapping[str, str | None]
) -> dict[str, Any]:
    """A hit's evidence as its finding carries it: its causes, the code site's source (from the
    code entity's row), the folded rule ids, and the session's robot and id — set last, so no
    rule's key stands in for them."""
    evidence: dict[str, Any] = {
        **item.hit.evidence,
        "causes": [cause.model_dump(mode="json") for cause in item.hit.causes],
    }
    site = evidence.get("code_site")
    if isinstance(site, dict):
        evidence["code_site"] = {**site, "source_id": sources.get(str(site.get("entity_id")))}
    if item.also:
        evidence["also"] = list(item.also)
    if view.sim:  # SOLUSDEV-322 P5-T3: a simulated session's finding says so
        evidence["sim"] = True
    return {**evidence, "robot_id": str(view.robot_entity_id), "session_id": str(view.session_id)}


async def _code_sources(
    db: AsyncSession, project_id: UUID, found: Iterable[_Found]
) -> dict[str, str | None]:
    """The connected source of each code entity a found code site names, from the entity's own row
    in this project (the rules leave the site's `source_id` empty)."""
    ids = {
        UUID(str(site["entity_id"]))
        for item in found
        if isinstance(site := item.hit.evidence.get("code_site"), dict)
    }
    if not ids:
        return {}
    rows = await db.execute(
        select(GraphEntity.id, GraphEntity.source_id).where(
            GraphEntity.project_id == project_id,
            GraphEntity.id.in_(ids),
            GraphEntity.deleted_at.is_(None),
        )
    )
    return {
        str(entity): None if source is None else str(source) for entity, source in rows.tuples()
    }


class WindowEvaluator:
    """One robot session's evaluator (the module docstring): `start` runs its ticker, `tick` is one
    tick. Its state is the session's, so the session manager's factory builds one per session."""

    def __init__(
        self,
        buffer: TelemetryBuffer,
        sessionmaker: async_sessionmaker[AsyncSession],
        envelopes: EnvelopeCache,
        rules: Sequence[SignalRule],
        event_ring: BenchEventRing,
        *,
        on_raised: Callable[[UUID, list[UUID]], Awaitable[None]] | None = None,
        cpu_budget_ms: float = 20,
        cpu_budget_ms_per_part: float = 10,
        tick_seconds: float = 1.0,
        artifacts: ArtifactStore | None = None,
        artifact_ttl_seconds: int = 3600,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._buffer = buffer
        self._sessionmaker = sessionmaker
        self._cache = envelopes
        self._rules = tuple(rules)
        self._by_id = {rule.rule_id: rule for rule in self._rules}
        self._ring = event_ring
        self._on_raised = on_raised
        self._budget_ms = cpu_budget_ms  # the floor of a window's budget
        self._budget_per_part_ms = cpu_budget_ms_per_part
        self._tick_seconds = tick_seconds
        self._artifacts = artifacts
        self._artifact_ttl = artifact_ttl_seconds
        self._now = now
        self._sleep = sleep
        self._tracks: dict[UUID, _Track] = {}
        self._baseline: tuple[UUID, RunManifest | None] | None = None
        #: part → (the channels it was assessed with, its `<part>: <need>` lines)
        self._assessed: dict[UUID, tuple[frozenset[str], tuple[str, ...]]] = {}
        self._missing_listed: list[str] | None = None
        self._marked: set[UUID] = set()
        self._broken: set[str] = set()
        self._off_unit: set[tuple[UUID, str]] = set()
        self._future: set[tuple[UUID, str]] = set()
        self._turn = 0  # the rule a tick's windows start with, moved past the rules that ran whole

    def start(self, view: SessionView) -> asyncio.Task[None]:
        """The session's ticker: a tick every `tick_seconds` until it is cancelled."""
        return asyncio.create_task(self._ticks(view), name=f"window-evaluator:{view.session_id}")

    async def _ticks(self, view: SessionView) -> None:
        # ponytail: a full period after each tick, so the cadence drifts by a tick's own few
        # milliseconds; a deadline schedule if anything ever counts on exact seconds.
        while True:
            await self._sleep(self._tick_seconds)
            try:
                await self.tick(view)
            except Exception:
                logger.exception("window evaluator tick failed %s", _where(view))

    async def tick(self, view: SessionView) -> list[UUID]:
        """One tick; the ids of the findings it raised, each once. Never two at a time (the
        session's ticker runs them in turn)."""
        streamed = {part: dict(channels) for part, channels in view.parts.items()}
        if not streamed:
            return []
        async with self._sessionmaker() as db:
            reads = await self._load(db, view, streamed)
            if reads is None:
                return []
            before, fresh = await self._read(reads, streamed)
            found = await self._judge(reads, before, fresh)
            self._prune(reads.envelopes)
            raised = await self._raise(db, reads, found)
            listed = self._missing_list()
            wrote = listed is not None and await self._write_missing(db, view, listed)
            if raised or wrote:
                await db.commit()
        if listed is not None:
            self._missing_listed = listed
        self._mark(reads, raised)
        ids = list(dict.fromkeys(finding_id for finding_id, _ in raised))
        await self._tell(view, ids)
        return ids

    # ------------------------------------------------------------------------ reads

    async def _load(
        self, db: AsyncSession, view: SessionView, streamed: Mapping[UUID, Mapping[str, datetime]]
    ) -> _Tick | None:
        """Step 2; None when nothing streamed is a live part of the project (a robot's own channels,
        a deleted part, another project's)."""
        inputs = await load_envelope_inputs(db, view.project_id, streamed)
        if not inputs:
            return None
        manifest, run_id = await self._baseline_run(db, view)
        envelopes = {
            part: await self._envelopes(db, view.project_id, part, one, manifest, run_id)
            for part, one in inputs.items()
        }
        hood = await load_neighborhood(
            db, view.project_id, roots=list(inputs), depth=2, relation_types=RELATIONS
        )
        graph = to_graph_context(hood)
        return _Tick(
            view=view,
            now=self._now(),
            budget_ms=max(self._budget_ms, self._budget_per_part_ms * len(view.parts)),
            graph=graph,
            entities={entity.id: entity for entity in graph.entities},
            envelopes=envelopes,
            channels={
                part: _all_channels(streamed[part], one.config) for part, one in inputs.items()
            },
            tolerance={
                part: _tolerance(envelopes[part], one.config) for part, one in inputs.items()
            },
        )

    async def _baseline_run(
        self, db: AsyncSession, view: SessionView
    ) -> tuple[RunManifest | None, UUID | None]:
        """The robot's baseline run — manifest and id (M56) — loaded once a baseline, as the
        session's owner; none without an artifact store or an owner, or when it does not load."""
        run = await run_store.baseline_for(db, view.project_id, view.robot_entity_id)
        if run is None or self._artifacts is None or view.owner_user_id is None:
            return None, None
        if self._baseline is None or self._baseline[0] != run.id:
            self._baseline = (run.id, None)
            try:
                record = await run_store.record(db, view.project_id, run.id)
                manifest = await run_store.load(
                    db, self._artifacts, record, view.owner_user_id, self._artifact_ttl
                )
                self._baseline = (run.id, manifest)
            except Exception as exc:  # an optional source: without it, no learned bounds
                logger.warning(
                    "window evaluator: baseline run %s unreadable (%s), no learned bounds %s",
                    run.id,
                    type(exc).__name__,
                    _where(view),
                )
        loaded = self._baseline[1]
        return loaded, run.id if loaded is not None else None

    async def _envelopes(
        self,
        db: AsyncSession,
        project_id: UUID,
        part_id: UUID,
        inputs: EnvelopeInputs,
        manifest: RunManifest | None,
        run_id: UUID | None,
    ) -> dict[str, Envelope]:
        """The part's envelopes by quantity, through the shared cache: built and put on a miss."""
        found: dict[str, Envelope] = {}
        for quantity in QUANTITIES:
            key = EnvelopeKey(
                project_id, part_id, quantity, inputs.config_version, inputs.definition_id, run_id
            )
            envelope = await self._cache.get(key)
            if envelope is None:
                envelope = await build_envelope(
                    db,
                    project_id,
                    part_id,
                    quantity,
                    config=inputs.config,
                    definition=inputs.definition,
                    scene_joint=inputs.scene_joint,
                    expected=inputs.expected,
                    baseline_run=manifest,
                    envelopes=_ENVELOPES,
                )
                if envelope is not None:
                    await self._cache.put(key, envelope)
            if envelope is not None:
                found[quantity] = envelope
        return found

    async def _read(
        self, tick: _Tick, streamed: Mapping[UUID, Mapping[str, datetime]]
    ) -> tuple[dict[UUID, dict[str, datetime]], list[datetime]]:
        """Step 1, into each part's history; the cursors as they stood (the first window's
        `judged_through`) and every new sample's event time. A sample dated in the future moves
        nothing (`MAX_FUTURE_SKEW_SECONDS`)."""
        before: dict[UUID, dict[str, datetime]] = {}
        fresh: list[datetime] = []
        ahead = tick.now + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
        for part in tick.envelopes:
            track = self._tracks.setdefault(part, _Track())
            before[part] = dict(track.cursor)
            for channel, began in streamed[part].items():
                cursor = track.cursor.get(channel)
                # a first packet dated in the future must not hide the real ones behind it
                since = cursor if cursor is not None else began if began <= ahead else None
                rows = await self._buffer.recent(tick.view.project_id, part, channel, since=since)
                new = self._dated(tick, part, channel, rows, cursor, ahead)
                if new:
                    track.cursor[channel], track.arrived[channel] = new[-1].timestamp, tick.now
                    fresh.extend(sample.timestamp for sample in new)
                    kept = self._unit_kept(tick, part, channel, new)
                    track.history.setdefault(channel, []).extend(kept)
        return before, fresh

    def _dated(
        self,
        tick: _Tick,
        part: UUID,
        channel: str,
        rows: Iterable[RecentSample],
        cursor: datetime | None,
        ahead: datetime,
    ) -> list[RecentSample]:
        """The rows after the cursor, oldest first, without those dated past `ahead`."""
        new = sorted((s for s in rows if cursor is None or s.timestamp > cursor), key=_stamp)
        dated = [sample for sample in new if sample.timestamp <= ahead]
        if len(dated) < len(new):
            self._said_once(self._future, "dated in the future", tick, part, channel)
        return dated

    def _unit_kept(
        self, tick: _Tick, part: UUID, channel: str, samples: Sequence[RecentSample]
    ) -> list[RecentSample]:
        """The samples in the unit of the envelope their channel is read against — its quantity's,
        a command's target's (`commanded_position` is a position); either stating none keeps a
        sample as it is. A sample in another unit is converted when `convert_unit` scales between
        the two (a simulated joint's rad against a real part's deg) and dropped when it does not."""
        quantity = channel.rsplit(".", 1)[-1].removeprefix("commanded_")
        envelope = tick.envelopes[part].get(quantity)
        unit = envelope.unit if envelope is not None else None
        kept = [s for s in (_in_unit(sample, unit) for sample in samples) if s is not None]
        if len(kept) < len(samples):
            self._said_once(self._off_unit, "not in their envelope's unit", tick, part, channel)
        return kept

    def _said_once(
        self, said: set[tuple[UUID, str]], why: str, tick: _Tick, part: UUID, channel: str
    ) -> None:
        """One warning a session per (part, channel) for each reason its samples are dropped."""
        if (part, channel) not in said:
            said.add((part, channel))
            logger.warning(
                "window evaluator drops samples %s part=%s channel=%r %s",
                why,
                part,
                channel[:64],
                _where(tick.view),
            )

    def _prune(self, parts: Iterable[UUID]) -> None:
        """Each channel keeps its last `TREND_HORIZON_SECONDS`, `MAX_HISTORY_SAMPLES` at most."""
        for part in parts:
            for rows in self._tracks[part].history.values():
                if rows:
                    start = bisect_left(rows, rows[-1].timestamp - _HORIZON, key=_stamp)
                    del rows[: max(start, len(rows) - MAX_HISTORY_SAMPLES)]

    # ------------------------------------------------------------------------ judging

    async def _judge(
        self,
        tick: _Tick,
        before: Mapping[UUID, Mapping[str, datetime]],
        fresh: Sequence[datetime],
    ) -> list[_Found]:
        """Steps 3 and 4: every window's coalesced findings, the oldest window first."""
        judged = {part: dict(cursors) for part, cursors in before.items()}
        frontier = max((at for cursors in before.values() for at in cursors.values()), default=None)
        base = frontier if frontier is not None else min(fresh, default=None)
        ends: Sequence[datetime | None] = (
            window_ends(base, fresh, self._tick_seconds) if base and fresh else [None]
        )
        found: list[_Found] = []
        skipped, ran = 0, len(self._rules)
        for end in ends:
            contexts = self._contexts(tick, judged, end)
            self._assess(tick, contexts)
            hits, missed, whole = self._evaluate(tick, contexts)
            skipped += missed
            ran = min(ran, whole)
            for part, hit in hits:
                self._tracks[part].prior[hit.rule_id] = hit
            found.extend(
                _Found(part, hit, also, _newest(contexts[part].samples))
                for part, hit, also in coalesce(hits)
            )
            for part, context in contexts.items():
                judged[part].update(_newest(context.samples))
            await asyncio.sleep(0)  # a replay's many windows let the rest of the server run
        # ponytail: the next tick starts at the first rule skipped. A rule costlier than the whole
        # budget runs for the parts that fit when its turn comes, the turn steps past it (never by
        # 0) and the tick is logged; no priorities, no per-rule cost accounting.
        self._turn += max(ran, 1) if skipped else 1
        if skipped:
            logger.warning(
                "window evaluator over its cpu budget of %g ms: skipped %d rule runs %s",
                tick.budget_ms,
                skipped,
                _where(tick.view),
            )
        return found

    def _contexts(
        self, tick: _Tick, judged: Mapping[UUID, Mapping[str, datetime]], end: datetime | None
    ) -> dict[UUID, WindowContext]:
        """Each live part's window ending at `end`."""
        shown = {
            part: {
                channel: _visible(self._tracks[part].history.get(channel, ()), end)
                for channel in channels
            }
            for part, channels in tick.channels.items()
        }
        return {
            part: WindowContext(
                part_id=part,
                robot_id=tick.view.robot_entity_id,
                session_id=tick.view.session_id,
                now=tick.now,
                samples=samples,
                envelopes=tick.envelopes[part],
                graph=tick.graph,
                last_sample_at=dict(self._tracks[part].arrived),
                prior_hits=tuple(self._tracks[part].prior.values()),
                tolerance=tick.tolerance[part],
                judged_through=dict(judged[part]),
                peers={other: streams for other, streams in shown.items() if other != part},
            )
            for part, samples in shown.items()
        }

    def _assess(self, tick: _Tick, contexts: Mapping[UUID, WindowContext]) -> None:
        """Note, for each part that streams, what each rule could not judge it for
        (`rule_base.unmet`) as `<part>: <need>` — the robot's `missing_signals` — and again
        whenever the part's channels grow, a later packet bringing one a rule needed."""
        for part, context in contexts.items():
            channels, assessed = frozenset(context.samples), self._assessed.get(part)
            if not any(context.samples.values()) or (assessed and channels <= assessed[0]):
                continue
            label = entity_label(tick.graph, part)
            lines = (
                f"{label}: {need}" for rule in self._rules for need in unmet(rule.needs, context)
            )
            self._assessed[part] = (channels, tuple(lines))

    def _evaluate(
        self, tick: _Tick, contexts: Mapping[UUID, WindowContext]
    ) -> tuple[list[Hit], int, int]:
        """Each rule over each part's window, rule by rule from this tick's turn, until the window
        has spent its CPU budget; the rest are counted as skipped. Also how many rules ran for
        every part (all of them when nothing was skipped): where the next tick resumes. A rule
        that raises judges nothing, said once."""
        started = time.perf_counter()
        hits: list[Hit] = []
        skipped = ran = 0
        turn = self._turn % len(self._rules) if self._rules else 0
        for rule in self._rules[turn:] + self._rules[:turn]:
            before = skipped
            for part, context in contexts.items():
                if (time.perf_counter() - started) * 1000 > tick.budget_ms:
                    skipped += 1
                    continue
                try:
                    hits.extend((part, hit) for hit in rule.evaluate(context))
                except Exception:
                    if rule.rule_id not in self._broken:
                        self._broken.add(rule.rule_id)
                        logger.exception(
                            "window evaluator rule failed rule=%s %s",
                            rule.rule_id,
                            _where(tick.view),
                        )
            if skipped == before:  # none of its parts was cut: it ran whole
                ran += 1
        return hits, skipped, ran

    # ------------------------------------------------------------------------ writes

    async def _raise(
        self, db: AsyncSession, tick: _Tick, found: Sequence[_Found]
    ) -> list[tuple[UUID, _Found]]:
        """Step 5: every finding the tick found, window by window, in the tick's transaction —
        (finding id, what it was raised from)."""
        if not found:
            return []
        sources = await _code_sources(db, tick.view.project_id, found)
        raised: list[tuple[UUID, _Found]] = []
        for item in found:
            hit, rule = item.hit, self._by_id.get(item.hit.rule_id)
            subjects = list(hit.subjects) or [item.part_id]
            about = tick.entities.get(subjects[0])
            spec = FindingSpec(
                rule_id=hit.rule_id,
                severity=hit.severity,
                source="observer",
                headline=hit.headline,
                subjects=subjects,
                evidence=_finding_evidence(tick.view, item, sources),
                matrix_cell=rule.matrix_cell if rule is not None else None,
                domain=Domain(about.domain) if about is not None else Domain.PROJECT,
                bucket=str(tick.view.session_id),
            )
            raised.append(((await raise_finding(db, tick.view.project_id, spec)).id, item))
        return raised

    def _missing_list(self) -> list[str] | None:
        """What the robot's `missing_signals` should now say, from the parts' current
        assessments (a list that may shrink); None before the session's first assessment and
        while it says so already."""
        if not self._assessed:
            return None
        lines = {line for _, part_lines in self._assessed.values() for line in part_lines}
        listed = sorted(lines)[:MAX_MISSING_SIGNALS]
        return None if listed == self._missing_listed else listed

    async def _write_missing(self, db: AsyncSession, view: SessionView, listed: list[str]) -> bool:
        """`listed` as the robot's `attrs.missing_signals` (attrs reassigned, the version bumped),
        under the project lock like every robot-attrs writer — re-entrant, so free once a finding
        was raised — and read after it; False when it says so already or the robot is gone."""
        await lock_project(db, view.project_id)
        robot = await db.get(GraphEntity, view.robot_entity_id, populate_existing=True)
        if robot is None or robot.project_id != view.project_id or robot.deleted_at is not None:
            return False
        if robot.attrs.get("missing_signals") == listed:
            return False
        robot.attrs = {**robot.attrs, "missing_signals": listed}
        robot.version += 1
        return True

    def _mark(self, tick: _Tick, raised: Sequence[tuple[UUID, _Found]]) -> None:
        """At a finding's first raise this session, a marker on each channel its part streamed in
        that window — on the part's device, at the channel's newest event time — its id attached
        to the ring's own record. A channel the wire event cannot carry is not marked."""
        for finding_id, item in raised:
            part = tick.entities.get(item.part_id)
            device = part.external_ref if part is not None else None
            if finding_id in self._marked or not device:
                continue
            self._marked.add(finding_id)
            kind: Literal["stream_gap", "threshold_breach"] = (
                "stream_gap" if item.hit.rule_id == "stream_gap" else "threshold_breach"
            )
            for channel, at in item.seen.items():
                try:
                    marker = ObserverEventIn(
                        kind=kind,
                        device_id=device,
                        signal=channel,
                        at=at,
                        detail={"rule_id": item.hit.rule_id},
                    )
                except ValidationError:
                    continue
                self._ring.append(tick.view.project_id, marker, finding_id=finding_id)

    async def _tell(self, view: SessionView, ids: list[UUID]) -> None:
        """`on_raised(robot_id, finding_ids)` after the commit; a failure is logged and swallowed:
        narration never stops observation."""
        if not ids or self._on_raised is None:
            return
        try:
            await self._on_raised(view.robot_entity_id, ids)
        except Exception:
            logger.exception("window evaluator on_raised failed %s", _where(view))
