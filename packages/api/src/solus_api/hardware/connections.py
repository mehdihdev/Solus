"""App-owned local connection attempts; graph metadata records their portable outcomes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.errors import APIError
from solus_api.deps import get_project_context, require_role
from solus_api.graph.live import LiveHub, graph_changed_frame
from solus_api.hardware.config import HardwareConfig
from solus_api.hardware.local_runtime import open_local_hardware, prepare_local_hardware
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.runtime_owner import RuntimeOwner, RuntimeOwnershipError
from solus_api.hardware.store import configuration_entries, read_entity_config
from solus_api.livebench.sessions import SessionManager, SessionNotFoundError, drain_task
from solus_api.models import GraphEntity, Role, User, utcnow
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_graph import lock_project

logger = logging.getLogger(__name__)


def _portable_error(error: Exception) -> str:
    messages = {
        "source_changed": "The calibration source changed; relink it before connecting.",
        "relink_required": "Relink the calibration source before connecting.",
        "config_upgrade_required": "Review and upgrade the saved configuration before connecting.",
        "config_conflict": "The saved configuration changed; review it before connecting.",
        "device_not_found": "The device is no longer connected.",
        "device_busy": "The device is already in use.",
        "device_ambiguous": "The device identity is ambiguous; select the physical device.",
        "device_permission_denied": "Device access was denied; check operating-system permissions.",
    }
    return messages.get(
        error.code if isinstance(error, APIError) else "",
        "The local connection could not be started.",
    )


def connection_state(
    attempt_id: uuid.UUID,
    status: str = "connecting",
    *,
    session_id: uuid.UUID | None = None,
    error: str | None = None,
    runtime_id: str | None = None,
) -> dict[str, Any]:
    return {
        "managed_by": "local_runtime",
        "attempt_id": str(attempt_id),
        "status": status,
        "session_id": str(session_id) if session_id else None,
        "error": error,
        **({"runtime_id": runtime_id} if runtime_id else {}),
    }


@dataclass(frozen=True)
class _Attempt:
    project: uuid.UUID
    account: uuid.UUID
    robot: uuid.UUID
    identity: uuid.UUID
    window: float


class HardwareConnections:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        manager: SessionManager,
        local: Any,
        hub: LiveHub,
        owner: RuntimeOwner | None = None,
    ) -> None:
        self.sessions, self.manager, self.local, self.hub = sessions, manager, local, hub
        self.owner = owner or RuntimeOwner()
        self._owner_lock = asyncio.Lock()
        self._tasks: dict[tuple[uuid.UUID, uuid.UUID], asyncio.Task[None]] = {}
        self._active: dict[tuple[uuid.UUID, uuid.UUID], tuple[_Attempt, uuid.UUID]] = {}
        self._closing = False
        self._cancelling: dict[tuple[uuid.UUID, uuid.UUID], asyncio.Task[None]] = {}
        self.manager.on_ended = self._session_ended

    async def startup(self) -> None:
        """Only our recognized ephemeral metadata is reconciled after restart."""
        if self.local is None:
            return
        try:
            runtime_id = await self.ensure_owner()
        except APIError:
            return
        projects: set[uuid.UUID] = set()
        async with self.sessions() as session:
            rows = await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.kind == "physical_robot",
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.attrs["connection"]["managed_by"].astext == "local_runtime",
                    GraphEntity.attrs["connection"]["runtime_id"].astext == runtime_id,
                    GraphEntity.attrs["connection"]["status"].astext.in_(
                        ["connecting", "connected"]
                    ),
                )
            )
            for robot in rows:
                previous = robot.attrs.get("connection", {})
                try:
                    attempt = uuid.UUID(previous["attempt_id"])
                except (KeyError, ValueError, TypeError):
                    continue
                robot.attrs = {
                    **robot.attrs,
                    "connection": connection_state(attempt, "disconnected", runtime_id=runtime_id),
                }
                projects.add(robot.project_id)
            await session.commit()
        for project in projects:
            await self._publish(project)

    async def ensure_owner(self) -> str:
        async with self._owner_lock:
            if self.local is None or self._closing:
                raise APIError(503, "source_unavailable", "Local runtime is unavailable")
            acquiring = asyncio.create_task(asyncio.to_thread(self.owner.acquire))
            try:
                return await asyncio.shield(acquiring)
            except asyncio.CancelledError:
                try:
                    await drain_task(acquiring)
                except Exception as exc:
                    logger.debug("cancelled ownership acquisition failed: %s", type(exc).__name__)
                raise
            except RuntimeOwnershipError:
                raise APIError(
                    503, "source_unavailable", "Local runtime ownership is unavailable"
                ) from None

    def schedule(
        self,
        project_id: uuid.UUID,
        account_id: uuid.UUID,
        robot_id: uuid.UUID,
        attempt_id: uuid.UUID,
        window_seconds: float,
    ) -> None:
        if self._closing or self.owner.identity is None:
            raise APIError(503, "source_unavailable", "Local runtime is shutting down")
        key = (project_id, robot_id)
        previous = self._tasks.get(key)
        if previous is not None:
            previous.cancel()
        attempt = _Attempt(project_id, account_id, robot_id, attempt_id, window_seconds)
        task = asyncio.create_task(self._run(attempt, previous))
        self._tasks[key] = task

        def completed(done: asyncio.Task[None]) -> None:
            if self._tasks.get(key) is done:
                self._tasks.pop(key, None)

        task.add_done_callback(completed)

    async def drain(self) -> None:
        """Wait for currently scheduled work (also a deterministic test seam)."""
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def cancel_robot(self, project_id: uuid.UUID, robot_id: uuid.UUID) -> None:
        key = (project_id, robot_id)
        closing = self._cancelling.get(key)
        if closing is None:
            closing = asyncio.create_task(self._cancel_robot(project_id, robot_id))
            self._cancelling[key] = closing
        try:
            await drain_task(closing)
        finally:
            if closing.done() and self._cancelling.get(key) is closing:
                self._cancelling.pop(key, None)

    async def _cancel_robot(self, project_id: uuid.UUID, robot_id: uuid.UUID) -> None:
        key = (project_id, robot_id)
        pending = self._tasks.get(key)
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        active = self._active.pop(key, None)
        if active is not None:
            attempt, session_id = active
            await self._stop(project_id, session_id)
            await self._finish(attempt, "disconnected")

    async def _session_ended(self, project_id: uuid.UUID, session_id: uuid.UUID) -> None:
        for key, active in list(self._active.items()):
            if key[0] == project_id and active[1] == session_id:
                self._active.pop(key, None)
                await self._finish(active[0], "disconnected")

    def assert_deletable(self, metadata: Any) -> None:
        if (
            isinstance(metadata, dict)
            and metadata.get("managed_by") == "local_runtime"
            and metadata.get("status") in {"connecting", "connected"}
            and (self.owner.identity is None or metadata.get("runtime_id") != self.owner.identity)
        ):
            raise APIError(
                409,
                "conflict",
                "Stop the connection in its owning local runtime before deleting",
            )

    async def aclose(self) -> None:
        self._closing = True
        try:
            for key in set(self._tasks) | set(self._active) | set(self._cancelling):
                await self.cancel_robot(*key)
        finally:
            async with self._owner_lock:
                self.owner.close()

    async def _robot(
        self, session: AsyncSession, attempt: _Attempt, *, authorize: bool = True
    ) -> GraphEntity:
        await lock_project(session, attempt.project)
        if authorize:
            user = await session.get(User, attempt.account)
            if user is None or user.deleted_at is not None:
                raise APIError(403, "forbidden", "Account is unavailable")
            ctx = await get_project_context(attempt.project, user, session)
            require_role(ctx, Role.MEMBER)
        robot = await session.scalar(
            select(GraphEntity)
            .where(
                GraphEntity.id == attempt.robot,
                GraphEntity.project_id == attempt.project,
                GraphEntity.kind == "physical_robot",
                GraphEntity.origin == "manual",
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if robot is None or robot.attrs.get("connection", {}).get("attempt_id") != str(
            attempt.identity
        ):
            raise APIError(409, "config_conflict", "Connection attempt is no longer current")
        if robot.attrs.get("connection", {}).get("runtime_id") != self.owner.identity:
            raise APIError(409, "config_conflict", "Connection belongs to another runtime")
        return robot

    async def _config(
        self, session: AsyncSession, attempt: _Attempt
    ) -> tuple[HardwareConfig, str, Any, Any]:
        config = await resolve_runtime_config(session, attempt.project, attempt.robot)
        entry, owner = await read_entity_config(session, attempt.project, attempt.robot)
        if entry is None or owner is None or config.identity is None or config.protocol is None:
            raise APIError(422, "validation_error", "Transport identity and protocol are required")
        entries = await configuration_entries(
            session, attempt.project, [attempt.robot, *(uuid.UUID(part) for part in config.parts)]
        )
        stamp = hashlib.sha256(
            json.dumps(
                {
                    "config": config.model_dump(mode="json"),
                    "owner": owner.model_dump(mode="json"),
                    "versions": sorted((str(item.id), item.config_version) for item in entries),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return config, stamp, entry.id, owner

    async def _run(self, attempt: _Attempt, previous: asyncio.Task[None] | None) -> None:
        session_id: uuid.UUID | None = None
        try:
            if previous is not None:
                await asyncio.gather(previous, return_exceptions=True)
            active = self._active.pop((attempt.project, attempt.robot), None)
            if active is not None:
                await self._stop(attempt.project, active[1])
            async with self.sessions() as session:
                robot = await self._robot(session, attempt)
                config, stamp, entry_id, owner = await self._config(session, attempt)
                label = robot.name
            document = await asyncio.to_thread(
                prepare_local_hardware,
                self.local,
                config,
                attempt.project,
                attempt.account,
                entry_id,
                owner_config=owner,
            )
            async with self.sessions() as session:
                await self._robot(session, attempt)
                if (await self._config(session, attempt))[1] != stamp or self._closing:
                    raise APIError(
                        409, "config_conflict", "Configuration changed before connection"
                    )

            async def open_robot() -> Any:
                return await open_local_hardware(self.local, document, attempt.project)

            record = await self.manager.start(
                attempt.project,
                mode="real",
                provider="robot",
                label=f"Robot {label}",
                open_conn=open_robot,
                window_seconds=attempt.window,
                device={"device_ref": config.identity.device_ref if config.identity else None},
            )
            session_id = record.id
            if await self._finish(attempt, "connected", session_id=session_id, stamp=stamp):
                self._active[(attempt.project, attempt.robot)] = (attempt, session_id)
                # Stop may have completed while the graph commit was in flight,
                # before this session became visible to the ended listener.
                if self._session_has_ended(attempt.project, session_id):
                    await self._stop(attempt.project, session_id)
                    await self._session_ended(attempt.project, session_id)
                session_id = None
        except asyncio.CancelledError:
            await self._finish(attempt, "disconnected")
        except Exception as exc:
            logger.warning(
                "hardware connection failed project=%s robot=%s error=%s",
                attempt.project,
                attempt.robot,
                type(exc).__name__,
            )
            await self._finish(attempt, "failed", error=_portable_error(exc))
        finally:
            if session_id is not None:
                await self._stop(attempt.project, session_id)

    def _session_has_ended(self, project: uuid.UUID, session_id: uuid.UUID) -> bool:
        try:
            return self.manager.get(project, session_id).status == "ended"
        except SessionNotFoundError:
            return True

    async def _stop(self, project: uuid.UUID, session_id: uuid.UUID) -> None:
        try:
            await self.manager.stop(project, session_id)
        except SessionNotFoundError:
            pass  # Already ended and evicted from the bounded session history.

    async def _finish(
        self,
        attempt: _Attempt,
        status: str,
        *,
        session_id: uuid.UUID | None = None,
        stamp: str | None = None,
        error: str | None = None,
    ) -> bool:
        try:
            async with self.sessions() as session:
                robot = await self._robot(session, attempt, authorize=stamp is not None)
                if stamp is not None and (
                    (await self._config(session, attempt))[1] != stamp or self._closing
                ):
                    status, session_id, error = (
                        "failed",
                        None,
                        "Configuration changed during connection.",
                    )
                robot.attrs = {
                    **robot.attrs,
                    "connection": connection_state(
                        attempt.identity,
                        status,
                        session_id=session_id,
                        error=error,
                        runtime_id=self.owner.identity,
                    ),
                }
                await session.commit()
            await self._publish(attempt.project)
            return status == "connected"
        except Exception as exc:
            if stamp is not None:
                await self._finish(
                    attempt, "failed", error="Connection authorization or configuration changed."
                )
            logger.warning(
                "connection completion discarded project=%s robot=%s error=%s",
                attempt.project,
                attempt.robot,
                type(exc).__name__,
            )
            return False

    async def _publish(self, project: uuid.UUID) -> None:
        try:
            await self.hub.publish(
                project,
                graph_changed_frame(
                    project_id=project,
                    source_id=None,
                    sync_id=None,
                    counts=GraphChangeCounts(entities_updated=1),
                    at=utcnow().isoformat(),
                ),
            )
        except Exception as exc:
            logger.warning(
                "connection event unavailable project=%s error=%s", project, type(exc).__name__
            )
