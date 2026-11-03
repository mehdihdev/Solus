"""Read-only authenticated WebSocket snapshots over the existing telemetry buffer."""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.core.security import decode_token
from solus_api.deps import get_project_context
from solus_api.graph.read_scope import resolve_scope
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.sessions import SessionManager, SessionNotFoundError
from solus_api.models import GraphEntity, User

router = APIRouter()
INTERVAL = 0.1
REAUTHORIZE_SECONDS = 5.0
AUTH_TIMEOUT = 5.0
SEND_TIMEOUT = 1.0
HEARTBEAT_SECONDS = 5.0
MAX_FRAME_BYTES = 1024 * 1024


class Authenticate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["authenticate"]
    token: str = Field(min_length=1, max_length=8192, repr=False)
    project_id: uuid.UUID


class StreamClosedError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code


async def authorize(
    ws: WebSocket, auth: Authenticate, identity: uuid.UUID
) -> tuple[uuid.UUID, set[uuid.UUID], float]:
    state = ws.app.state
    try:
        claims = decode_token(auth.token, state.settings, state.jwks_client)
    except (APIError, ValueError, OverflowError, TypeError):
        raise StreamClosedError(4401) from None
    async with state.sessionmaker() as db:
        user = await db.scalar(select(User).where(User.supabase_user_id == claims.sub))
        if user is None:
            raise StreamClosedError(4401)
        try:
            await get_project_context(auth.project_id, user, db)
            session = state.bench_sessions.get(auth.project_id, identity)
            scope = await resolve_scope(db, auth.project_id, user.id)
        except (APIError, SessionNotFoundError):
            raise StreamClosedError(4404) from None
        visible = set(
            await db.scalars(
                select(GraphEntity.id).where(
                    scope.entity_predicate(),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.id.in_(
                        state.telemetry_plumbing.observed_entity_ids(
                            auth.project_id, session.device_ids
                        )
                    ),
                )
            )
        )
        user_id = user.id
    # Signature/expiry were verified centrally above; retain expiry for the fast loop.
    raw_expiry = jwt.decode(auth.token, options={"verify_signature": False}).get("exp")
    if (
        isinstance(raw_expiry, bool)
        or not isinstance(raw_expiry, (int, float))
        or not math.isfinite(raw_expiry)
    ):
        raise StreamClosedError(4401)
    expires = float(raw_expiry)
    return user_id, visible, expires


async def snapshot(
    plumbing: TelemetryPlumbing,
    manager: SessionManager,
    project: uuid.UUID,
    identity: uuid.UUID,
    visible: set[uuid.UUID],
) -> dict[str, Any]:
    session = manager.get(project, identity)
    if session.status == "ended":
        raise StreamClosedError(1000)
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=8)
    devices = []
    for device_id in session.device_ids[:64]:
        view = await plumbing.snapshot_device(project, device_id)
        if view.resolved_entity_id is not None and view.resolved_entity_id not in visible:
            continue
        view = view.model_copy(update={"signals": view.signals[:64]})
        device = view.model_dump(mode="json")
        roles = manager.channel_roles(project, device_id)
        for series, original in zip(device["signals"], view.signals, strict=True):
            points = [
                point.model_dump(mode="json")
                for point in original.points
                if cutoff <= point.timestamp <= now
            ]
            series["points"] = downsample(points, 128)
            if series["signal"] in roles:
                series["display_role"] = roles[series["signal"]]
        devices.append(device)
    return {
        "type": "telemetry",
        "project_id": str(project),
        "session_id": str(identity),
        "devices": devices,
    }


def downsample(points: list[Any], limit: int) -> list[Any]:
    if len(points) <= limit:
        return points
    if limit == 1:
        return points[-1:]
    return [points[index * (len(points) - 1) // (limit - 1)] for index in range(limit)]


def encode_snapshot(frame: dict[str, Any]) -> str:
    """Bound outbound work without dropping any channel's newest point."""
    for limit in (128, 32, 8, 1):
        for device in frame["devices"]:
            for series in device["signals"]:
                series["points"] = downsample(series["points"], limit)
        encoded = json.dumps(frame, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) <= MAX_FRAME_BYTES:
            return encoded
    raise StreamClosedError(4413)


async def send_snapshots(
    ws: WebSocket, auth: Authenticate, identity: uuid.UUID, visible: set[uuid.UUID], expires: float
) -> None:
    state = ws.app.state
    previous = None
    last_sent = time.monotonic()
    observed = state.telemetry_plumbing.observed_entity_ids(
        auth.project_id, state.bench_sessions.get(auth.project_id, identity).device_ids
    )
    next_auth = time.monotonic() + REAUTHORIZE_SECONDS
    while True:
        if time.time() >= expires:
            raise StreamClosedError(4401)
        current = state.telemetry_plumbing.observed_entity_ids(
            auth.project_id, state.bench_sessions.get(auth.project_id, identity).device_ids
        )
        if time.monotonic() >= next_auth or current != observed:
            try:
                _, visible, expires = await authorize(ws, auth, identity)
            except StreamClosedError as error:
                raise StreamClosedError(4401 if error.code == 4401 else 4403) from None
            observed = current
            next_auth = time.monotonic() + REAUTHORIZE_SECONDS
        frame = await snapshot(
            state.telemetry_plumbing, state.bench_sessions, auth.project_id, identity, visible
        )
        encoded = encode_snapshot(frame)
        payload = encoded if encoded != previous else None
        if payload is None and time.monotonic() - last_sent >= HEARTBEAT_SECONDS:
            payload = json.dumps(
                {
                    "type": "heartbeat",
                    "project_id": str(auth.project_id),
                    "session_id": str(identity),
                }
            )
        if payload is not None:
            try:
                await asyncio.wait_for(ws.send_text(payload), SEND_TIMEOUT)
            except TimeoutError:
                raise StreamClosedError(1013) from None
            previous = encoded
            last_sent = time.monotonic()
        await asyncio.sleep(INTERVAL)


async def reject_input(ws: WebSocket) -> None:
    await ws.receive_text()
    raise StreamClosedError(4400)


async def connected(ws: WebSocket, identity: uuid.UUID) -> None:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT)
        if len(raw.encode()) > 9216:
            raise StreamClosedError(4413)
        auth = Authenticate.model_validate_json(raw)
    except (TimeoutError, ValidationError, KeyError):
        raise StreamClosedError(4400) from None
    user, visible, expires = await authorize(ws, auth, identity)
    counts = ws.app.state.bench_stream_users
    if counts.get(user, 0) >= 8:
        raise StreamClosedError(4429)
    counts[user] = counts.get(user, 0) + 1
    tasks = [
        asyncio.create_task(send_snapshots(ws, auth, identity, visible, expires)),
        asyncio.create_task(reject_input(ws)),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            counts[user] -= 1
            if not counts[user]:
                del counts[user]


@router.websocket("/ws/v1/bench/sessions/{session_id}")
async def bench_stream(ws: WebSocket, session_id: uuid.UUID) -> None:
    state = ws.app.state
    if not hasattr(state, "bench_stream_count"):
        state.bench_stream_count = 0
        state.bench_stream_users = {}
    if not hasattr(state, "bench_stream_ip_limiter"):
        state.bench_stream_ip_limiter = ConnectRateLimiter(60)
    client_host = ws.client.host if ws.client is not None else "unknown"
    if not state.bench_stream_ip_limiter.allow(client_host):
        await ws.close(4429)
        return
    if state.bench_stream_count >= 64:
        await ws.close(4429)
        return
    state.bench_stream_count += 1
    try:
        await ws.accept()
        await connected(ws, session_id)
    except StreamClosedError as error:
        await ws.close(error.code)
    except SessionNotFoundError:
        await ws.close(4404)
    except KeyError:
        await ws.close(4400)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        state.bench_stream_count -= 1
