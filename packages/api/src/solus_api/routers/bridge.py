"""The bridge WebSocket route — companion dial-in (SOLUSDEV-154 / BRG-02-impl).

Route per docs/api/API-implementation.md §Bridge:
`WS /api/v1/projects/{project_id}/bridge`, project-scoped per CLAUDE.md §7.

Auth is hand-rolled: HTTP deps/middleware never run on WS scope. The bearer is
read from the upgrade request's Authorization header ONLY — a `?token=` query
parameter is never consulted, so a token can never land in access logs. Every
failure maps to an app close code (contract §4): 4400 protocol, 4401 auth,
4403 revoked, 4404 non-member (no existence leak), 4409 superseded, 4413
oversize, 4429 rate. Log lines here carry ids/codes/sizes — never args,
values, tokens, or raw frames (§6).
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.shapes import ToolResult
from solus_api.bridge.allowlist import validate_inventory
from solus_api.bridge.frames import (
    CLOSE_NOT_FOUND,
    CLOSE_OVERSIZE,
    CLOSE_RATE_EXCEEDED,
    CLOSE_REVOKED,
    CLOSE_UNAUTHENTICATED,
    CLOSE_UNSUPPORTED_VERSION,
    PROTOCOL_VERSION,
    ArtifactChunkData,
    CredentialSubmitData,
    FrameViolation,
    HelloData,
    InboundFrame,
    StatusData,
    UnknownFrame,
    credential_ack_frame,
    error_frame,
    hello_ack_frame,
    parse_frame,
    pong_frame,
)
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import (
    TokenBucket,
    fail_artifact_fetches,
    fail_inflight,
    ingest_artifact_chunk,
    ingest_result,
    supersede,
)
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.core.security import decode_token
from solus_api.deps import (
    BridgeSessionsDep,
    ProjectCtx,
    SecretStoreDep,
    SessionDep,
    get_project_context,
)
from solus_api.models import User
from solus_api.services.events import emit_event
from solus_api.services.limits import user_has_byo_entitlement

logger = logging.getLogger("solus.bridge.ws")

router = APIRouter()

# Repeated dropped-frame violations (malformed, rate-dropped, misplaced hello)
# before the socket is closed — the §6 "repeated failures → close" bound.
MAX_VIOLATIONS = 20


class _CloseError(Exception):
    def __init__(self, code: int, error: str | None = None, message: str = "") -> None:
        self.code = code
        self.error = error
        self.message = message


def _token_exp(token: str) -> datetime:
    """The already-VERIFIED token's exp — decode_token checked signature+exp but
    TokenClaims does not carry it (flagged deviation: unverified re-decode of a
    verified string, avoids widening core/security.py)."""
    payload = pyjwt.decode(token, options={"verify_signature": False})
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):  # pragma: no cover — Supabase always sets exp
        raise _CloseError(CLOSE_UNAUTHENTICATED)
    return datetime.fromtimestamp(exp, tz=UTC)


@dataclass(frozen=True)
class _ConnectAuth:
    user: User
    team_id: uuid.UUID
    token_exp: datetime


async def _admit(ws: WebSocket, project_id: uuid.UUID, settings: Settings) -> _ConnectAuth:
    """Connection admission: pre-auth per-IP throttle (SEC-M1 — an
    unauthenticated flood must not buy unbounded signature verifications),
    then auth, then the per-user connect rate and the early team-cap check
    (re-checked synchronously at bind for the race, CR-M1). The contract names
    the caps but no close code; 4429 fits their family (flagged)."""
    state = ws.app.state
    client_host = ws.client.host if ws.client is not None else "unknown"
    if not state.bridge_ip_connect_limiter.allow(f"ip:{client_host}"):
        raise _CloseError(CLOSE_RATE_EXCEEDED)
    async with state.sessionmaker() as db:
        auth = await _authenticate(ws, project_id, settings, db)
    if not state.bridge_connect_limiter.allow(str(auth.user.id)):
        raise _CloseError(CLOSE_RATE_EXCEEDED)
    if state.bridge_sessions.count_for_team(auth.team_id) >= settings.bridge_max_team_sessions:
        raise _CloseError(CLOSE_RATE_EXCEEDED)
    return auth


async def _authenticate(
    ws: WebSocket, project_id: uuid.UUID, settings: Settings, session: AsyncSession
) -> _ConnectAuth:
    """Header bearer → decode_token → server-derived scope (contract §2/§3)."""
    header = ws.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _CloseError(CLOSE_UNAUTHENTICATED)
    try:
        claims = decode_token(token, settings, ws.app.state.jwks_client)
    except APIError as exc:
        raise _CloseError(CLOSE_UNAUTHENTICATED) from exc
    user = await session.scalar(select(User).where(User.supabase_user_id == claims.sub))
    if user is None:
        # The bridge never provisions accounts — the app does that on first
        # HTTP request. An unknown-but-valid token is unauthenticated here.
        raise _CloseError(CLOSE_UNAUTHENTICATED)
    try:
        ctx = await get_project_context(project_id, user, session)
    except APIError as exc:
        raise _CloseError(CLOSE_NOT_FOUND) from exc
    return _ConnectAuth(user=user, team_id=ctx.team.id, token_exp=_token_exp(token))


async def _await_hello(ws: WebSocket, settings: Settings) -> HelloData:
    """First frame must be a valid hello at a supported version (§2/§4)."""
    try:
        raw = await asyncio.wait_for(
            ws.receive_text(), timeout=settings.bridge_hello_timeout_seconds
        )
    except TimeoutError as exc:
        raise _CloseError(CLOSE_UNSUPPORTED_VERSION, "hello_timeout", "expected hello") from exc
    frame = parse_frame(
        raw,
        control_cap=settings.bridge_control_frame_max_bytes,
        tool_result_cap=settings.bridge_tool_result_max_bytes,
    )
    if not (isinstance(frame, InboundFrame) and isinstance(frame.payload, HelloData)):
        raise _CloseError(CLOSE_UNSUPPORTED_VERSION, "expected_hello", "first frame must be hello")
    if frame.payload.protocol_version != PROTOCOL_VERSION:
        raise _CloseError(
            CLOSE_UNSUPPORTED_VERSION,
            "unsupported_protocol_version",
            f"supported protocol_version: {PROTOCOL_VERSION}",
        )
    return frame.payload


async def _recheck_scope(ws: WebSocket, project_id: uuid.UUID, user: User) -> None:
    """Revocation poll (§3): membership gone mid-session → close 4403."""
    sessionmaker = ws.app.state.sessionmaker
    async with sessionmaker() as session:
        try:
            await get_project_context(project_id, user, session)
        except APIError as exc:
            raise _CloseError(CLOSE_REVOKED) from exc


def _store_status(
    session: BridgeSession, snapshot: StatusData, known_servers: frozenset[str]
) -> None:
    """Cache the snapshot (BRG-03). Server names are untrusted — entries outside
    the Solus-owned allowlist are dropped + logged; the cache is advisory
    (UI-facing) and dispatch never gates on it: the companion is authoritative
    at call time."""
    kept = tuple(s for s in snapshot.servers if s.name in known_servers)
    for dropped in snapshot.servers:
        if dropped.name not in known_servers:
            logger.warning(
                "bridge session %s status for unknown server %.64r dropped",
                session.session_id,
                dropped.name,
            )
    session.last_status = StatusData(servers=kept)
    session.status_updated_at = datetime.now(UTC)


async def _store_license_values(
    state: Any, team_id: uuid.UUID, server: str, secrets: dict[str, str]
) -> bool:
    """Write each license value under its tenant-scoped ref; returns whether an
    already-configured value was replaced. Unchanged values are not re-written
    (each put is a quota-bearing Secrets Manager call). Values are never
    logged; callers turn any raised failure into an error ack."""
    from solus_api.agent.tools.mcp_servers import license_secret_ref

    overwrote = False
    for key, value in secrets.items():
        ref = license_secret_ref(team_id, server, key)
        try:
            existing: str | None = await state.secret_store.get(ref)
        except SecretNotFoundError:
            existing = None
        if existing == value:
            continue  # unchanged — no quota-bearing re-write
        overwrote = overwrote or existing is not None
        await state.secret_store.put(ref, value)
    return overwrote


async def _handle_credential_submit(
    state: Any,
    session: BridgeSession,
    data: CredentialSubmitData,
    submit_bucket: TokenBucket | None = None,
) -> str:
    """MCP-05 BYO-license capture. The team scope comes from the SERVER-bound
    session, never from the frame; unknown servers/keys are rejected wholesale
    (no partial writes); re-submits overwrite (put semantics). Hardened per the
    Phase-4 security review: rate-bucketed (each write is a quota-bearing
    Secrets Manager call), entitlement-gated (a non-entitled member cannot
    plant or clobber the team's license), unchanged values are not re-written,
    and a storage failure becomes an error ack, never a socket crash. This
    function NEVER logs the frame, the secrets dict, or any value — the ack
    and the data-collection event carry key NAMES only (§6)."""
    # Function-local like BridgeTool in runtime: the WS router keeps only a soft
    # dependency on the MCP catalog module.
    from solus_api.agent.tools.mcp_servers import MCP_SERVER_CATALOG
    from solus_api.agent.tools.mcp_tool import LicenseTier

    def _reject(reason: str) -> str:
        # Our own static reason string — never the frame, never a value.
        logger.warning(
            "bridge session %s credential_submit rejected (%s)", session.session_id, reason
        )
        return credential_ack_frame(data.server, ok=False, stored=[], error=reason)

    if submit_bucket is not None and not submit_bucket.allow():
        return _reject("credential submissions rate-limited; retry shortly")
    spec = MCP_SERVER_CATALOG.get(data.server)
    if spec is None:
        return _reject("unknown server")
    if spec.license_tier is not LicenseTier.BYO_PAID:
        return _reject("not a bring-your-own-license tool")
    async with state.sessionmaker() as db:
        entitled = await user_has_byo_entitlement(db, session.user_id)
    if not entitled:
        return _reject("bring-your-own-license tools require an upgraded plan")
    unknown = sorted(key for key in data.secrets if key not in spec.license_secrets)
    if unknown:
        # Key NAMES may travel back to the same-tenant companion; values never.
        return credential_ack_frame(
            data.server, ok=False, stored=[], error=f"unknown keys: {', '.join(unknown)}"
        )
    try:
        overwrote = await _store_license_values(state, session.team_id, data.server, data.secrets)
    except Exception as exc:
        # Static reason + exception TYPE only — never the frame, never a value.
        # ponytail: a multi-key spec could partial-write here; every current
        # byo_paid spec has exactly one license key.
        logger.warning(
            "bridge session %s credential storage failed (%s)",
            session.session_id,
            type(exc).__name__,
        )
        return credential_ack_frame(
            data.server, ok=False, stored=[], error="credential storage failed; retry shortly"
        )
    async with state.sessionmaker() as db:
        actor = await db.get(User, session.user_id)
        if actor is not None:
            emit_event(
                db,
                user=actor,
                event_type="bridge.license_credentials_submitted",
                team_id=session.team_id,
                project_id=session.project_id,
                # `overwrote` is the tripwire for a member replacing an already-
                # configured team license (review M1) — names and flags only.
                payload={
                    "server": data.server,
                    "keys": sorted(data.secrets),
                    "overwrote": overwrote,
                },
            )
            await db.commit()
    return credential_ack_frame(data.server, ok=True, stored=sorted(data.secrets), error=None)


async def _handle_parsed(
    state: Any,
    session: BridgeSession,
    frame: InboundFrame | FrameViolation | UnknownFrame,
    known_servers: frozenset[str] = frozenset(),
    submit_bucket: TokenBucket | None = None,
) -> tuple[str | None, bool]:
    """→ (reply frame, counts-as-violation). Oversize raises 4413."""
    if isinstance(frame, FrameViolation):
        if frame.kind == "oversize":
            raise _CloseError(CLOSE_OVERSIZE)
        logger.warning("bridge session %s dropped frame: %s", session.session_id, frame.reason)
        return None, True
    if isinstance(frame, UnknownFrame):
        logger.info(
            "bridge session %s ignored unknown frame type %.64r", session.session_id, frame.type
        )
        return None, False
    if frame.type == "ping":
        return pong_frame(), False
    if frame.type == "tool_result":
        assert isinstance(frame.payload, ToolResult)
        ingest_result(session, frame.payload)
        return None, False
    if frame.type == "hello":
        logger.warning("bridge session %s sent hello twice", session.session_id)
        return None, True
    if frame.type == "status":
        assert isinstance(frame.payload, StatusData)
        _store_status(session, frame.payload, known_servers)
        return None, False
    if frame.type == "artifact_chunk":
        assert isinstance(frame.payload, ArtifactChunkData)
        # SOLUS-CAD-00c: bulk bytes for a pull this cloud started. Routed by
        # fetch_id; an unknown one is dropped inside, never an error frame.
        ingest_artifact_chunk(session, frame.payload)
        return None, False
    if frame.type == "credential_submit":
        assert isinstance(frame.payload, CredentialSubmitData)
        return await _handle_credential_submit(state, session, frame.payload, submit_bucket), False
    # error frames: observe only.
    logger.info("bridge session %s received %s frame", session.session_id, frame.type)
    return None, False


def _tick_timeout(
    session: BridgeSession, settings: Settings, last_frame: float, next_member_check: float
) -> float:
    """Deadline arithmetic for one receive wait; raises on lapsed deadlines."""
    now = time.monotonic()
    exp_remaining = (session.token_exp - datetime.now(UTC)).total_seconds()
    if exp_remaining <= 0:
        raise _CloseError(CLOSE_UNAUTHENTICATED)  # token lapsed mid-session (§2)
    idle_remaining = (last_frame + settings.bridge_idle_timeout_seconds) - now
    if idle_remaining <= 0:
        raise _CloseError(1000)  # dead NAT mapping — free the registry slot (§5)
    return max(0.05, min(idle_remaining, next_member_check - now, exp_remaining))


async def _frame_loop(
    ws: WebSocket, session: BridgeSession, user: User, settings: Settings
) -> None:
    known_servers = frozenset(ws.app.state.bridge_allowlist.servers)
    bucket = TokenBucket(rate=settings.bridge_msg_rate_per_second, burst=settings.bridge_msg_burst)
    submit_bucket = TokenBucket(
        rate=settings.bridge_credential_submit_rate_per_minute / 60.0,
        burst=settings.bridge_credential_submit_burst,
    )
    violations = 0

    def _bump() -> None:
        nonlocal violations
        violations += 1
        if violations >= MAX_VIOLATIONS:
            raise _CloseError(CLOSE_RATE_EXCEEDED)

    last_frame = time.monotonic()
    next_member_check = time.monotonic() + settings.bridge_revocation_poll_seconds
    while True:
        timeout = _tick_timeout(session, settings, last_frame, next_member_check)
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
        except TimeoutError:
            if time.monotonic() >= next_member_check:
                await _recheck_scope(ws, session.project_id, user)
                next_member_check = time.monotonic() + settings.bridge_revocation_poll_seconds
            continue
        last_frame = time.monotonic()
        if not bucket.allow():
            _bump()
            continue  # excess dropped (§7)
        frame = parse_frame(
            raw,
            control_cap=settings.bridge_control_frame_max_bytes,
            tool_result_cap=settings.bridge_tool_result_max_bytes,
        )
        reply, is_violation = await _handle_parsed(
            ws.app.state, session, frame, known_servers, submit_bucket
        )
        if is_violation:
            _bump()
        if reply is not None:
            await ws.send_text(reply)


@router.websocket("/api/v1/projects/{project_id}/bridge")
async def bridge_ws(ws: WebSocket, project_id: uuid.UUID) -> None:
    state = ws.app.state
    settings: Settings = state.settings
    await ws.accept()  # required before an app close code can be delivered
    session: BridgeSession | None = None
    try:
        auth = await _admit(ws, project_id, settings)
        hello = await _await_hello(ws, settings)
        inventory = validate_inventory(hello, state.bridge_allowlist)
        session = BridgeSession(
            session_id=uuid.uuid4().hex,
            user_id=auth.user.id,
            team_id=auth.team_id,
            project_id=project_id,
            companion_instance_id=hello.companion_instance_id,
            companion_version=hello.companion_version,
            protocol_version=hello.protocol_version,
            connected_at=datetime.now(UTC),
            token_exp=auth.token_exp,
            inventory=inventory,
            send=ws.send_text,
            close=ws.close,
            max_inflight=settings.bridge_max_inflight,
        )
        # CR-M1: re-check the team cap synchronously with bind — the earlier
        # check raced across the hello await; no await sits between here and
        # bind, so the cap cannot be overshot by concurrent connects.
        if (
            state.bridge_sessions.get(auth.user.id, auth.team_id, project_id) is None
            and state.bridge_sessions.count_for_team(auth.team_id)
            >= settings.bridge_max_team_sessions
        ):
            raise _CloseError(CLOSE_RATE_EXCEEDED)
        superseded = state.bridge_sessions.bind(session)
        if superseded is not None:
            await supersede(superseded, session, state.sessionmaker)
        logger.info(
            "bridge session %s bound: user=%s team=%s project=%s instance=%.64s tools=%d",
            session.session_id,
            auth.user.id,
            auth.team_id,
            project_id,
            hello.companion_instance_id,
            len(inventory),
        )
        await ws.send_text(hello_ack_frame())
        await _frame_loop(ws, session, auth.user, settings)
    except _CloseError as close:
        if close.error is not None:
            try:
                await ws.send_text(error_frame(close.error, close.message))
            except Exception:  # socket may already be gone
                logger.debug("bridge error frame send failed")
        try:
            await ws.close(close.code)
        except Exception:
            logger.debug("bridge close after %d failed", close.code)
    except WebSocketDisconnect:
        pass  # companion went away — cleanup below marks the bridge offline
    finally:
        if session is not None:
            state.bridge_sessions.remove(session)  # only-if-current
            fail_inflight(session, "bridge disconnected")
            fail_artifact_fetches(session)
            logger.info("bridge session %s closed", session.session_id)


async def _license_states(
    db: AsyncSession, user: User, team_id: uuid.UUID, secret_store: SecretStore, names: list[str]
) -> dict[str, str]:
    """MCP-05 graceful license surface, per server name: `ready` (free tier,
    uncataloged, or byo_paid fully licensed) · `bring_your_license` (byo_paid,
    entitled, keys missing) · `upgrade_required` (byo_paid, not entitled). One
    NON-LOCKING entitlement read per request — this is a poll surface with no
    insert to serialize; the FOR UPDATE helper would pin the subscription row
    across the secret-store probes below (Phase-4 review). Secret VALUES are
    only presence-probed, never surfaced."""
    from solus_api.agent.tools.mcp_servers import MCP_SERVER_CATALOG, license_secret_ref
    from solus_api.agent.tools.mcp_tool import LicenseTier

    states: dict[str, str] = {}
    entitled: bool | None = None  # lazy: one subscription read per request
    for name in names:
        spec = MCP_SERVER_CATALOG.get(name)
        if spec is None or spec.license_tier is not LicenseTier.BYO_PAID:
            states[name] = "ready"
            continue
        if entitled is None:
            entitled = await user_has_byo_entitlement(db, user.id)
        if not entitled:
            states[name] = "upgrade_required"
            continue
        missing = False
        for key in spec.license_secrets:
            try:
                await secret_store.get(license_secret_ref(team_id, name, key))
            except SecretNotFoundError:
                missing = True
                break
        states[name] = "bring_your_license" if missing else "ready"
    return states


@router.get("/api/v1/projects/{project_id}/bridge")
async def bridge_status(
    ctx: ProjectCtx, sessions: BridgeSessionsDep, db: SessionDep, secret_store: SecretStoreDep
) -> dict[str, Any]:
    """The requesting user's bridge state for this project (BRG-03 + MCP-05
    license_state). PER-USER semantics: the registry is keyed (user, team,
    project) — you see YOUR companion, not a teammate's. Read-only: no DB
    writes beyond the entitlement read; liveness is ephemeral."""
    session = sessions.get(ctx.user.id, ctx.team.id, ctx.project.id)
    if session is None:
        return envelope({"connected": False, "companion_version": None, "servers": []})
    status = session.last_status
    servers = list(status.servers) if status else []
    states = await _license_states(
        db, ctx.user, ctx.team.id, secret_store, [server.name for server in servers]
    )
    return envelope(
        {
            "connected": True,
            "companion_version": session.companion_version,
            "connected_at": session.connected_at.isoformat(),
            "status_updated_at": (
                session.status_updated_at.isoformat() if session.status_updated_at else None
            ),
            "servers": [
                {**server.model_dump(mode="json"), "license_state": states[server.name]}
                for server in servers
            ],
        }
    )
