"""BenchViewService — the only writer of the team-shared bench view
(docs/api/bench-view.md §3, docs/architecture/bench-view.md §3).

Callers: the REST router and the SOL bench-view tools. The service never commits: the
caller commits, and the live publisher's ORM listener publishes `bench.view_changed`
only after that commit.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.livebench.view.expression import ExpressionError, parse_expression
from solus_api.livebench.view.schemas import (
    DISPLAY_FIELDS,
    BenchViewData,
    BenchViewResult,
    DeleteDerived,
    DerivedEntry,
    DerivedTarget,
    DisplayEntry,
    DisplayPatch,
    SetDisplay,
    SignalRefOut,
    UpsertDerived,
    target_key,
)
from solus_api.models import ROLE_RANK, BenchView, Project, Role, User, utcnow
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.livebench.view")

MAX_DERIVED: Final = 32
MAX_ENTRIES: Final = 512
MAX_GROUPS: Final = 16
MAX_PER_GROUP: Final = 8
MAX_INVERSE_OPS: Final = 64
MAX_BODY_BYTES: Final = 1024 * 1024

Actor = Literal["user", "sol"]
OpModel = SetDisplay | UpsertDerived | DeleteDerived


@dataclass(frozen=True, slots=True)
class _ViewState:
    display: tuple[DisplayEntry, ...] = ()
    derived: tuple[DerivedEntry, ...] = ()


@dataclass(slots=True)
class _Applied:
    state: _ViewState
    inverse_groups: list[list[OpModel]] = field(default_factory=list)
    #: (event suffix, node_count) per derived op, in order.
    derived_events: list[tuple[str, int]] = field(default_factory=list)


def _view_error(status: int, code: str, message: str, details: list[Any] | None = None) -> APIError:
    return APIError(status, code, message, details)


# ------------------------------------------------------------------ pure op logic


def _sorted_display(entries: Sequence[DisplayEntry]) -> tuple[DisplayEntry, ...]:
    return tuple(sorted(entries, key=lambda e: target_key(e.target)))


def _restore_patch(entry: DisplayEntry) -> DisplayPatch:
    """A patch that recreates `entry` from defaults (its non-default fields only)."""
    present = {name: getattr(entry, name) for name in DISPLAY_FIELDS if getattr(entry, name)}
    if entry.order is not None:
        present["order"] = entry.order
    return DisplayPatch(**present)


def _set_display_op(state: _ViewState, op: SetDisplay, applied: _Applied) -> _ViewState:
    if isinstance(op.target, DerivedTarget) and op.target.id not in {d.id for d in state.derived}:
        raise _view_error(404, "not_found", "Derived signal not found")
    key = target_key(op.target)
    defaults = DisplayEntry(target=op.target)
    current = next((e for e in state.display if target_key(e.target) == key), defaults)
    changes = {name: getattr(op.patch, name) for name in op.patch.model_fields_set}
    prior = {
        name: None if getattr(current, name) == getattr(defaults, name) else getattr(current, name)
        for name in changes
    }
    updated = current.model_copy(
        update={
            name: getattr(defaults, name) if value is None else value
            for name, value in changes.items()
        }
    )
    applied.inverse_groups.append(
        [SetDisplay(kind="set_display", target=op.target, patch=DisplayPatch(**prior))]
    )
    others = [e for e in state.display if target_key(e.target) != key]
    entries = others if updated.is_default() else [*others, updated]
    return _ViewState(_sorted_display(entries), state.derived)


def _parsed_entry(
    op: UpsertDerived, derived_id: uuid.UUID, created_at: datetime, now: datetime
) -> DerivedEntry:
    parsed = parse_expression(op.expression)  # pre-validated by _check_expressions
    return DerivedEntry(
        id=derived_id,
        name=op.name,
        expression=op.expression,
        unit=op.unit,
        node_count=parsed.node_count,
        refs=[SignalRefOut(device_id=r.device_id, signal=r.signal) for r in parsed.refs],
        created_at=created_at,
        updated_at=now,
    )


def _restore_derived(entry: DerivedEntry) -> UpsertDerived:
    return UpsertDerived(
        kind="upsert_derived",
        id=entry.id,
        name=entry.name,
        expression=entry.expression,
        unit=entry.unit,
    )


def _upsert_op(
    state: _ViewState, op: UpsertDerived, applied: _Applied, now: datetime
) -> _ViewState:
    existing = next((d for d in state.derived if op.id is not None and d.id == op.id), None)
    if existing is None:
        entry = _parsed_entry(op, op.id or uuid.uuid4(), now, now)
        applied.inverse_groups.append([DeleteDerived(kind="delete_derived", id=entry.id)])
        applied.derived_events.append(("created", entry.node_count))
        return _ViewState(state.display, (*state.derived, entry))
    entry = _parsed_entry(op, existing.id, existing.created_at, now)
    applied.inverse_groups.append([_restore_derived(existing)])
    applied.derived_events.append(("updated", entry.node_count))
    derived = tuple(entry if d.id == existing.id else d for d in state.derived)
    return _ViewState(state.display, derived)


def _delete_op(state: _ViewState, op: DeleteDerived, applied: _Applied) -> _ViewState:
    existing = next((d for d in state.derived if d.id == op.id), None)
    if existing is None:
        raise _view_error(404, "not_found", "Derived signal not found")
    target = DerivedTarget(kind="derived", id=op.id)
    removed = [e for e in state.display if e.target == target]
    restore_display = [
        SetDisplay(kind="set_display", target=target, patch=_restore_patch(e)) for e in removed
    ]
    applied.inverse_groups.append([_restore_derived(existing), *restore_display])
    applied.derived_events.append(("deleted", 0))
    return _ViewState(
        tuple(e for e in state.display if e.target != target),
        tuple(d for d in state.derived if d.id != op.id),
    )


def _check_expressions(ops: Sequence[OpModel]) -> None:
    for index, op in enumerate(ops):
        if not isinstance(op, UpsertDerived):
            continue
        try:
            parse_expression(op.expression)
        except ExpressionError as exc:
            raise _view_error(
                422,
                "expression_error",
                "A derived signal expression is invalid",
                [{"op_index": index, **exc.as_detail()}],
            ) from None


def _check_bounds(state: _ViewState) -> None:
    if len(state.derived) > MAX_DERIVED:
        raise _view_error(422, "too_many_derived", f"At most {MAX_DERIVED} derived signals")
    if len(state.display) > MAX_ENTRIES:
        raise _view_error(422, "too_many_entries", f"At most {MAX_ENTRIES} display settings")
    groups: dict[str, int] = {}
    for entry in state.display:
        if entry.plot_group is not None:
            groups[entry.plot_group] = groups.get(entry.plot_group, 0) + 1
    if len(groups) > MAX_GROUPS or any(n > MAX_PER_GROUP for n in groups.values()):
        raise _view_error(
            422,
            "too_many_groups",
            f"At most {MAX_GROUPS} plot groups of {MAX_PER_GROUP} signals each",
        )
    names = [d.name.casefold() for d in state.derived]
    if len(names) != len(set(names)):
        raise _view_error(422, "duplicate_name", "Two derived signals would share a name")


def _apply_view_ops(state: _ViewState, ops: Sequence[OpModel], now: datetime) -> _Applied:
    """Apply ops in order to an immutable state; raises APIError on the first failure.
    Expressions are checked first (expression_error precedes not_found, route doc §3.3)."""
    _check_expressions(ops)
    applied = _Applied(state)
    for op in ops:
        if isinstance(op, SetDisplay):
            applied.state = _set_display_op(applied.state, op, applied)
        elif isinstance(op, UpsertDerived):
            applied.state = _upsert_op(applied.state, op, applied, now)
        else:
            applied.state = _delete_op(applied.state, op, applied)
    _check_bounds(applied.state)
    return applied


def _inverse_ops(applied: _Applied) -> list[OpModel]:
    inverse = [op for group in reversed(applied.inverse_groups) for op in group]
    if len(inverse) > MAX_INVERSE_OPS:
        raise _view_error(422, "too_many_ops", f"Undo would need more than {MAX_INVERSE_OPS} ops")
    return inverse


# ------------------------------------------------------------------------ service


def _load_state(row: BenchView | None, project_id: uuid.UUID) -> _ViewState:
    if row is None:
        return _ViewState()
    try:
        return _ViewState(
            _sorted_display([DisplayEntry.model_validate(e) for e in row.display]),
            tuple(DerivedEntry.model_validate(d) for d in row.derived),
        )
    except (ValidationError, TypeError):
        logger.error("bench view row failed re-validation; serving empty project=%s", project_id)
        return _ViewState()


def _view_data(version: int, state: _ViewState, updated_at: datetime | None) -> BenchViewData:
    return BenchViewData(
        version=version,
        display=list(state.display),
        derived=list(state.derived),
        updated_at=updated_at,
    )


class BenchViewService:
    """Read and versioned write of one project's bench view.

    Team scoping is the caller's: pass a project the requesting user already resolved
    through the centralized project context. `apply` never commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> BenchViewData:
        row = await self.session.get(BenchView, project_id)
        if row is None:
            return BenchViewData(version=0, display=[], derived=[], updated_at=None)
        return _view_data(row.version, _load_state(row, project_id), row.updated_at)

    async def apply(
        self,
        *,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        user: User,
        role: Role | None,
        ops: Sequence[OpModel],
        expected_version: int | None,
        undo: bool = False,
        actor: Actor = "user",
    ) -> BenchViewResult:
        """Apply `ops` atomically. `expected_version=None` applies onto the current version
        (SOL direct writes). Raises APIError: 403 forbidden (role below MEMBER), 404
        not_found, 409 conflict (details [{current_version}]), 422 expression_error /
        too_many_* / duplicate_name / too_many_ops / validation_error (1 MiB backstop)."""
        if role is None or ROLE_RANK[role] < ROLE_RANK[Role.MEMBER]:
            raise _view_error(403, "forbidden", "Requires member role on this team")
        await self._lock_live_project(project_id)
        row = await self.session.get(BenchView, project_id, populate_existing=True)
        current = row.version if row is not None else 0
        if expected_version is not None and expected_version != current:
            raise _view_error(
                409,
                "conflict",
                "Bench view changed; reload it before saving",
                [{"current_version": current}],
            )
        now = utcnow()
        applied = _apply_view_ops(_load_state(row, project_id), ops, now)
        inverse = _inverse_ops(applied)
        display = [e.model_dump(mode="json") for e in applied.state.display]
        derived = [d.model_dump(mode="json") for d in applied.state.derived]
        if len(json.dumps([display, derived]).encode()) > MAX_BODY_BYTES:
            raise _view_error(422, "validation_error", "Bench view would exceed 1 MiB")
        if row is None:
            row = BenchView(project_id=project_id)
            self.session.add(row)
        row.version = current + 1
        row.display = display
        row.derived = derived
        row.updated_by = user.id
        await self.session.flush()
        self._emit_events(project_id, team_id, user, ops, applied, row.version, undo, actor)
        return BenchViewResult(
            version=row.version,
            view=_view_data(row.version, applied.state, now),
            inverse_ops=inverse,
        )

    async def _lock_live_project(self, project_id: uuid.UUID) -> None:
        # Lock the stable parent before reading the optional view row, so two first
        # writes cannot both insert (as save_workspace_layout).
        found = await self.session.scalar(
            select(Project.id)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
        )
        if found is None:
            raise _view_error(404, "not_found", "Project not found")

    def _emit_events(
        self,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        user: User,
        ops: Sequence[OpModel],
        applied: _Applied,
        version: int,
        undo: bool,
        actor: Actor,
    ) -> None:
        """Payloads carry counts and kinds only — never names, expressions or values."""

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            emit_event(
                self.session,
                user=user,
                event_type=event_type,
                team_id=team_id,
                project_id=project_id,
                payload=payload,
            )

        count = len(applied.state.derived)
        for suffix, node_count in applied.derived_events:
            emit(f"bench.derived_signal_{suffix}", {"count": count, "node_count": node_count})
        if undo:
            emit("bench.view_undo", {"version": version})
        else:
            kinds = sorted({op.kind for op in ops})
            emit("bench.view_updated", {"actor": actor, "op_kinds": kinds, "version": version})
