"""SOL bench view operations: read (with live values), display edits, derived upsert/delete
(SOLUSDEV-319). docs/api/bench-view.md §6; `BenchViewService` is the only writer.

Live values (`bench_view.read` include_values) are evaluated off the event loop under a total
work budget (samples fed × (1 + filters), summed over every derived signal) and a deadline. An
entry that would exceed either gets `latest: null` and `latest_reason` (`budget` | `deadline`).
Direct writes share the REST PATCH route's per-user limiter (`app.state.bench_view_limiter`).
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.bench_tools_common import (
    BenchScope,
    Caller,
    api_tool_error,
    as_uuid,
    cell,
    invalid,
    rate_limited,
    row,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.livebench.view.expression import (
    ParsedExpression,
    SignalRef,
    evaluate,
    parse_expression,
)
from solus_api.livebench.view.router import PATCHES_PER_MINUTE
from solus_api.livebench.view.schemas import SetDisplay, parse_ops
from solus_api.livebench.view.service import BenchViewService, OpModel

#: The newest samples read per device for `bench_view.read` values (the evaluator's window cap).
VALUE_SAMPLES: Final = 2000
#: Total evaluation work per read: Σ over derived of (samples fed × (1 + filter count)).
#: ~0.8 s of CPU for the worst-case expression shape; the rest report `budget`.
WORK_BUDGET: Final = 400_000
#: Wall-clock bound on one read's evaluation; entries not started by then report `deadline`.
DEADLINE_SECONDS: Final = 2.0

#: Per device: signal → the buffer's recent samples (RecentSample-like: timestamp, value).
Points = Sequence[Any]


@dataclass(frozen=True)
class _Job:
    parsed: ParsedExpression
    points: dict[SignalRef, Points]
    cost: int


def utc_iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def _summary_display(ops: Sequence[SetDisplay]) -> str:
    verbs = {
        "pinned": ("Pinned", "Unpinned"),
        "hidden": ("Hid", "Showed"),
        "order": ("Reordered", "Reordered"),
        "unit": ("Changed the unit of", "Reset the unit of"),
        "limits": ("Set limits on", "Reset limits on"),
        "plot_group": ("Grouped", "Ungrouped"),
    }
    counts: dict[str, int] = {}
    for op in ops:
        for name in op.patch.model_fields_set:
            value = getattr(op.patch, name)
            verb = verbs[name][0 if value not in (None, False) else 1]
            counts[verb] = counts.get(verb, 0) + 1
    return "; ".join(f"{verb} {n} signal{'s' if n != 1 else ''}" for verb, n in counts.items())


def _latest(job: _Job) -> dict[str, Any]:
    series = {
        ref: [(p.timestamp.timestamp(), p.value) for p in points]
        for ref, points in job.points.items()
    }
    samples = evaluate(job.parsed, series)
    if not samples:
        return {"value": None, "at": None}
    at, value = samples[-1]
    return {"value": value if math.isfinite(value) else None, "at": utc_iso(at)}


def _evaluate_all(
    jobs: list[_Job | None], budget: int, deadline: float
) -> list[tuple[dict[str, Any] | None, str | None]]:
    """Runs in a worker thread: (latest, reason) per job, in order, within budget/deadline."""
    out: list[tuple[dict[str, Any] | None, str | None]] = []
    spent = 0
    for job in jobs:
        if job is None:
            out.append(({"value": None, "at": None}, None))
        elif time.monotonic() >= deadline:
            out.append((None, "deadline"))
        elif spent + job.cost > budget:
            out.append((None, "budget"))
        else:
            spent += job.cost
            out.append((_latest(job), None))
    return out


class BenchViewOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = Caller(session, scope)
        self.service = BenchViewService(session)

    async def read(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_role()  # project scope + live membership; any role reads
        view = (await self.service.get(self.scope.project_id)).model_dump(mode="json")
        if args.get("include_values", True):
            await self._add_latest(view["derived"])
        return view

    async def _add_latest(self, derived: list[dict[str, Any]]) -> None:
        plumbing = getattr(self.state, "telemetry_plumbing", None)
        if plumbing is None:
            for entry in derived:
                entry["latest"] = {"value": None, "at": None}
            return
        cache: dict[str, dict[str, Points]] = {}
        jobs: list[_Job | None] = []
        for entry in derived:
            parsed = parse_expression(entry["expression"])
            points = {ref: await self._points(plumbing, cache, ref) for ref in parsed.refs}
            fed = max(1, sum(len(p) for p in points.values()))
            jobs.append(_Job(parsed, points, fed * (1 + parsed.filter_count)))
        deadline = time.monotonic() + DEADLINE_SECONDS
        results = await asyncio.to_thread(_evaluate_all, jobs, WORK_BUDGET, deadline)
        for entry, (latest, reason) in zip(derived, results, strict=True):
            entry["latest"] = latest
            if reason is not None:
                entry["latest_reason"] = reason

    async def _points(
        self, plumbing: Any, cache: dict[str, dict[str, Points]], ref: SignalRef
    ) -> Points:
        """The buffer's samples for `ref`, unconverted (conversion runs in the worker)."""
        if ref.device_id not in cache:
            view = await plumbing.get_device_recent(
                self.scope.project_id, ref.device_id, limit=VALUE_SAMPLES
            )
            cache[ref.device_id] = {s.signal: s.points for s in view.signals}
        return cache[ref.device_id].get(ref.signal, ())

    def _limiter(self) -> ConnectRateLimiter | None:
        """The REST PATCH route's per-user limiter (livebench/view/router.py), shared."""
        if self.state is None:
            return None
        limiter: ConnectRateLimiter | None = getattr(self.state, "bench_view_limiter", None)
        if limiter is None:
            limiter = self.state.bench_view_limiter = ConnectRateLimiter(PATCHES_PER_MINUTE)
        return limiter

    async def _apply(self, ops: Sequence[OpModel]) -> Any:
        role = await self.caller.require_member()
        limiter = self._limiter()
        if limiter is not None:
            rate_limited(limiter, str(self.scope.user_id), "too many bench view edits; slow down")
        try:
            result = await self.service.apply(
                project_id=self.scope.project_id,
                team_id=self.scope.team_id,
                user=await self.caller.user(),
                role=role,
                ops=ops,
                expected_version=None,
                actor="sol",
            )
        except APIError as exc:
            raise api_tool_error(exc) from None
        await self.session.commit()
        return result

    @staticmethod
    def _ops(raw: list[dict[str, Any]]) -> list[OpModel]:
        try:
            return parse_ops(raw)
        except ValidationError as exc:
            raise invalid(exc) from None
        except APIError as exc:
            raise api_tool_error(exc) from None

    async def update_display(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        ops = self._ops(list(args["ops"]))
        result = await self._apply(ops)
        return {
            "version": result.version,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
            "summary": _summary_display([op for op in ops if isinstance(op, SetDisplay)]),
        }

    async def upsert_derived(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        (op,) = self._ops([{**args, "kind": "upsert_derived"}])
        result = await self._apply([op])
        derived_id = result.inverse_ops[0].id
        entry = next(d for d in result.view.derived if d.id == derived_id)
        verb = "Created" if result.inverse_ops[0].kind == "delete_derived" else "Updated"
        return {
            "version": result.version,
            "id": str(derived_id),
            "node_count": entry.node_count,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
            "summary": f"{verb} derived signal ‹{cell(entry.name, 64)}›",
        }

    async def delete_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        await self.caller.require_member()
        view = await self.service.get(self.scope.project_id)
        derived_id = as_uuid(args["id"])
        entry = next((d for d in view.derived if d.id == derived_id), None)
        if entry is None:
            raise ToolException("Derived signal not found.", code=ToolErrorCode.NOT_FOUND)
        shown = sum(1 for e in view.display if getattr(e.target, "id", None) == derived_id)
        return [
            row("Derived signal", None, cell(entry.name, 64)),
            row("Expression", None, cell(entry.expression)),
            row("Shown in", "removed", f"{shown} display settings"),
        ]

    async def delete_derived(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        ops = self._ops([{"kind": "delete_derived", "id": args["id"]}])
        result = await self._apply(ops)
        return {
            "version": result.version,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
        }
