"""Publish-after-commit for live change hints (ADR-037 §3, SOLUSDEV-312).

    ORM flush -> frames queued on the session -> COMMIT -> hub.publish_to() per frame

**Why listeners instead of publish calls in routes.** Team state changes in dozens of
places (routes, services, the ARQ worker, account deletion). A hand-written
`hub.publish(...)` per call site is exactly the one somebody forgets. The flush listener
derives each frame from the ROW that changed, so a new write path is covered for free.

**Publish only after commit.** A frame published before commit tells a teammate to refetch
state that does not exist yet (or never will). Frames wait in `session.info` and leave in
`after_commit`; any rollback discards them. A publish failure is logged and swallowed: it
can never fail the request or the sync that caused it.

**Savepoints.** `after_commit` also fires when a SAVEPOINT is released, so it only
publishes at the OUTERMOST commit. Each queued frame remembers the savepoints it was queued
under, so rolling one back drops exactly its own frames; rolling back the outer transaction
drops everything. When one transaction produces the same frame twice, they coalesce and the
survivor keeps only the savepoints BOTH shared — a frame the outer transaction also
produced is never lost to an inner rollback (at worst a hint is slightly over-published,
and hints are cheap by design).

**Bulk statements bypass ORM events.** `delete(Model).where(...)` / `update(Model)` emit no
flush events, so code that uses them (account deletion) calls `queue_frame` explicitly.

**Frames are built through the contract models** (`solus_contracts.live_events`), so a
wrong shape fails here, in tests, instead of on a client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from solus_contracts.live_events import (
    AccessRevoked,
    JobUpdated,
    LayoutChanged,
    MembershipChanged,
    NotificationCreated,
    ProjectUpdated,
    SourcesChanged,
    TeamActivity,
    TeamInvitesChanged,
    TeamMembersChanged,
    TeamProjectsChanged,
    TeamUpdated,
)
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from solus_api.graph.live import HUB_INFO_KEY, Channel
from solus_api.models import (
    Activity,
    Invite,
    Job,
    JobStatus,
    Membership,
    Notification,
    Project,
    ProjectMembership,
    Source,
    Team,
    WorkspaceLayout,
)

logger = logging.getLogger("solus.graph.live_publisher")

_QUEUE_KEY = "solus.live_queue"

#: One transaction can touch thousands of rows; frames are coalesced, but distinct scopes
#: (a cascade over many projects) could still add up. Past this the extras are dropped —
#: a hint, so the next frame the client does get triggers the same refetch.
_MAX_QUEUED_FRAMES = 1_000

#: Frame fields that describe the LATEST state rather than which thing changed; two frames
#: differing only in these coalesce, the later one winning.
_STATE_FIELDS = frozenset({"at", "status", "version"})

_pending: set[asyncio.Task[None]] = set()
_installed = False


@dataclass(slots=True)
class _Queued:
    target: Channel
    frame: dict[str, Any]
    #: Savepoints open when queued, outermost first.
    savepoints: tuple[SessionTransaction, ...]


_Kind = str  # "new" | "dirty" | "deleted"
_Derived = Iterable[tuple[Channel, BaseModel]]


# --------------------------------------------------------------- change detection


def _changed(obj: Any, *columns: str) -> bool:
    state = inspect(obj)
    return any(state.attrs[name].history.has_changes() for name in columns)


def _soft_deleted(obj: Any) -> bool:
    return any(v is not None for v in inspect(obj).attrs.deleted_at.history.added)


def _restored(obj: Any) -> bool:
    history = inspect(obj).attrs.deleted_at.history
    return obj.deleted_at is None and any(v is not None for v in history.deleted)


def _live_on_insert(obj: Any, kind: _Kind) -> bool:
    return kind == "new" and obj.deleted_at is None


# ------------------------------------------------------------------- derivations
#
# One function per model: (row, kind, at) -> [(channel, frame)]. Channels come from the
# row's own scope columns — never from a request.


def _activity(row: Activity, kind: _Kind, at: str) -> _Derived:
    if kind == "new":
        yield (
            Channel.team(row.team_id),
            TeamActivity(
                team_id=row.team_id, project_id=row.project_id, actor_id=row.actor_id, at=at
            ),
        )


def _notification(row: Notification, kind: _Kind, at: str) -> _Derived:
    if kind == "new":
        yield Channel.user(row.user_id), NotificationCreated(user_id=row.user_id, at=at)


def _team(row: Team, kind: _Kind, at: str) -> _Derived:
    revoked = kind == "deleted" or (kind == "dirty" and _soft_deleted(row))
    updated = kind == "dirty" and _changed(row, "name", "slug", "settings", "plan_status")
    if revoked or updated:
        yield Channel.team(row.id), TeamUpdated(team_id=row.id, at=at)
    if revoked:
        yield (
            Channel.team(row.id),
            AccessRevoked(user_id=None, team_id=row.id, project_id=None, at=at),
        )


def _membership(row: Membership, kind: _Kind, at: str) -> _Derived:
    gone = kind == "deleted" or (kind == "dirty" and _soft_deleted(row))
    joined = _live_on_insert(row, kind) or (
        kind == "dirty" and (_restored(row) or _changed(row, "role", "status"))
    )
    if not (gone or joined):
        return
    yield Channel.team(row.team_id), TeamMembersChanged(team_id=row.team_id, at=at)
    if gone:
        yield (
            Channel.user(row.user_id),
            AccessRevoked(user_id=row.user_id, team_id=row.team_id, project_id=None, at=at),
        )
    else:
        yield (
            Channel.user(row.user_id),
            MembershipChanged(user_id=row.user_id, team_id=row.team_id, project_id=None, at=at),
        )


def _project_membership(row: ProjectMembership, kind: _Kind, at: str) -> _Derived:
    if kind == "deleted" or (kind == "dirty" and _soft_deleted(row)):
        yield (
            Channel.user(row.user_id),
            AccessRevoked(user_id=row.user_id, team_id=None, project_id=row.project_id, at=at),
        )
    elif _live_on_insert(row, kind) or (kind == "dirty" and _restored(row)):
        yield (
            Channel.user(row.user_id),
            MembershipChanged(user_id=row.user_id, team_id=None, project_id=row.project_id, at=at),
        )


def _invite(row: Invite, kind: _Kind, at: str) -> _Derived:
    if kind == "new" or (kind == "dirty" and _changed(row, "status")):
        yield Channel.team(row.team_id), TeamInvitesChanged(team_id=row.team_id, at=at)


def _project(row: Project, kind: _Kind, at: str) -> _Derived:
    gone = kind == "deleted" or (kind == "dirty" and _soft_deleted(row))
    edited = kind == "dirty" and _changed(row, "name", "description", "archived_at")
    if _live_on_insert(row, kind) or gone or edited:
        yield (
            Channel.team(row.team_id),
            TeamProjectsChanged(team_id=row.team_id, project_id=row.id, at=at),
        )
    if gone or edited:
        yield (
            Channel.project(row.id),
            ProjectUpdated(project_id=row.id, team_id=row.team_id, at=at),
        )
    if gone:
        yield (
            Channel.project(row.id),
            AccessRevoked(user_id=None, team_id=None, project_id=row.id, at=at),
        )


def _source(row: Source, kind: _Kind, at: str) -> _Derived:
    # `cursor` and `config` move on every sync tick and carry nothing a client shows.
    if kind != "dirty" or _changed(row, "status", "name", "last_synced_at", "last_error"):
        yield (
            Channel.project(row.project_id),
            SourcesChanged(project_id=row.project_id, source_id=row.id, at=at),
        )


def _layout(row: WorkspaceLayout, kind: _Kind, at: str) -> _Derived:
    if kind == "new" or (kind == "dirty" and _changed(row, "version")):
        yield (
            Channel.project(row.project_id),
            LayoutChanged(project_id=row.project_id, version=row.version, at=at),
        )


def _job(row: Job, kind: _Kind, at: str) -> _Derived:
    # Progress ticks are chatty and show nowhere a hint would help: status only.
    if kind == "new" or (kind == "dirty" and _changed(row, "status")):
        yield (
            Channel.project(row.project_id),
            JobUpdated.model_validate(  # validates the status against the contract's names
                {
                    "project_id": row.project_id,
                    "job_id": row.id,
                    "status": JobStatus(row.status).value,
                    "at": at,
                }
            ),
        )


_DERIVERS: dict[type, Callable[[Any, _Kind, str], _Derived]] = {
    Activity: _activity,
    Notification: _notification,
    Team: _team,
    Membership: _membership,
    ProjectMembership: _project_membership,
    Invite: _invite,
    Project: _project,
    Source: _source,
    WorkspaceLayout: _layout,
    Job: _job,
}


# ------------------------------------------------------------------------ queueing


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _savepoints(session: Session) -> tuple[SessionTransaction, ...]:
    chain: list[SessionTransaction] = []
    tx = session.get_nested_transaction()
    while tx is not None and tx.nested:
        chain.append(tx)
        tx = tx.parent
    return tuple(reversed(chain))


def _common_prefix(
    a: tuple[SessionTransaction, ...], b: tuple[SessionTransaction, ...]
) -> tuple[SessionTransaction, ...]:
    shared: list[SessionTransaction] = []
    for left, right in zip(a, b, strict=False):
        if left is not right:
            break
        shared.append(left)
    return tuple(shared)


def _enqueue(session: Session, target: Channel, frame: BaseModel) -> None:
    payload = frame.model_dump(mode="json")
    identity = (
        target,
        json.dumps({k: v for k, v in payload.items() if k not in _STATE_FIELDS}, sort_keys=True),
    )
    queue: dict[tuple[Channel, str], _Queued] = session.info.setdefault(_QUEUE_KEY, {})
    savepoints = _savepoints(session)
    existing = queue.get(identity)
    if existing is not None:
        existing.frame = payload
        existing.savepoints = _common_prefix(existing.savepoints, savepoints)
        return
    if len(queue) >= _MAX_QUEUED_FRAMES:
        logger.warning("live frame queue full for this transaction; dropping %s", payload["type"])
        return
    queue[identity] = _Queued(target, payload, savepoints)


def queue_frame(session: AsyncSession | Session, target: Channel, frame: BaseModel) -> None:
    """Queue one frame for publication after this session commits.

    For writes that bypass ORM events (bulk `delete()` / `update()`). Without a hub on the
    session (a script, a test session) it is a no-op.
    """
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    if HUB_INFO_KEY not in sync.info:
        return
    _enqueue(sync, target, frame)


# ------------------------------------------------- explicit frames for bulk statements
#
# `delete(Model).where(...)` skips ORM events, so the account/team/project teardown in
# routers/users.py queues these by hand. They mirror what the listeners derive for the same
# change made row by row.


def queue_source_removed(
    session: AsyncSession, *, project_id: uuid.UUID, source_id: uuid.UUID | None
) -> None:
    queue_frame(
        session,
        Channel.project(project_id),
        SourcesChanged(project_id=project_id, source_id=source_id, at=_now()),
    )


def queue_project_removed(
    session: AsyncSession, *, team_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    at = _now()
    queue_frame(
        session,
        Channel.team(team_id),
        TeamProjectsChanged(team_id=team_id, project_id=project_id, at=at),
    )
    queue_frame(
        session,
        Channel.project(project_id),
        ProjectUpdated(project_id=project_id, team_id=team_id, at=at),
    )
    queue_frame(
        session,
        Channel.project(project_id),
        AccessRevoked(user_id=None, team_id=None, project_id=project_id, at=at),
    )


def queue_member_removed(session: AsyncSession, *, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    at = _now()
    queue_frame(session, Channel.team(team_id), TeamMembersChanged(team_id=team_id, at=at))
    queue_frame(
        session,
        Channel.user(user_id),
        AccessRevoked(user_id=user_id, team_id=team_id, project_id=None, at=at),
    )


def queue_team_removed(session: AsyncSession, *, team_id: uuid.UUID) -> None:
    at = _now()
    queue_frame(session, Channel.team(team_id), TeamUpdated(team_id=team_id, at=at))
    queue_frame(session, Channel.team(team_id), TeamInvitesChanged(team_id=team_id, at=at))
    queue_frame(
        session,
        Channel.team(team_id),
        AccessRevoked(user_id=None, team_id=team_id, project_id=None, at=at),
    )


def queue_account_removed(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    queue_frame(
        session,
        Channel.user(user_id),
        AccessRevoked(user_id=user_id, team_id=None, project_id=None, at=_now()),
    )


def _on_after_flush(session: Session, _flush_context: Any) -> None:
    if HUB_INFO_KEY not in session.info:
        return
    at = _now()
    groups: tuple[tuple[_Kind, Iterable[Any]], ...] = (
        ("new", session.new),
        ("dirty", session.dirty),
        ("deleted", session.deleted),
    )
    for kind, rows in groups:
        for row in list(rows):
            deriver = _DERIVERS.get(type(row))
            if deriver is None:
                continue
            try:
                for target, frame in deriver(row, kind, at):
                    _enqueue(session, target, frame)
            except Exception:  # noqa: BLE001 — a bad hint must never fail the write
                logger.exception("live frame derivation failed model=%s", type(row).__name__)


def _on_after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint release is not a commit; the outer commit publishes
    queue: dict[tuple[Channel, str], _Queued] | None = session.info.pop(_QUEUE_KEY, None)
    if not queue:
        return
    hub = session.info.get(HUB_INFO_KEY)
    if hub is None:
        logger.debug("no live hub on this session; dropping %d frame(s)", len(queue))
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("no running loop; dropping %d live frame(s)", len(queue))
        return
    task = loop.create_task(_publish_all(hub, list(queue.values())))
    _pending.add(task)  # a strong reference: an unreferenced task can be garbage collected
    task.add_done_callback(_pending.discard)


def _on_soft_rollback(session: Session, previous: SessionTransaction) -> None:
    queue: dict[tuple[Channel, str], _Queued] | None = session.info.get(_QUEUE_KEY)
    if not queue:
        return
    if not previous.nested:
        queue.clear()
        return
    for identity in [i for i, q in queue.items() if previous in q.savepoints]:
        del queue[identity]


def _on_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    # The ROOT transaction ended (commit already published; close/rollback discards), so a
    # reused session can never publish a previous transaction's frames.
    if transaction.parent is None:
        session.info.pop(_QUEUE_KEY, None)


async def _publish_all(hub: Any, items: list[_Queued]) -> None:
    for item in items:
        try:
            await hub.publish_to(item.target, item.frame)
        except Exception:  # noqa: BLE001 — never fail (or even notice) in the request
            logger.warning(
                "live publish failed channel=%s type=%s",
                item.target.name,
                item.frame.get("type"),
                exc_info=True,
            )


async def drain_pending_publishes() -> None:
    """Wait for in-flight publishes. For tests and orderly shutdown."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def install() -> None:
    """Register the session listeners ONCE per process (idempotent)."""
    global _installed
    if _installed:
        return
    event.listen(Session, "after_flush", _on_after_flush)
    event.listen(Session, "after_commit", _on_after_commit)
    event.listen(Session, "after_soft_rollback", _on_soft_rollback)
    event.listen(Session, "after_transaction_end", _on_transaction_end)
    _installed = True
