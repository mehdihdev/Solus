"""The detection routes' orchestration as services (docs/api/hardware.md §4-5): a device's proposal,
its confirmation, and a decided link suggestion with the session an accepted device starts. The
routes and SOL's hardware tools both call these (SOLUSDEV-326 P2).

Each takes the project and the acting member explicitly and reads through the caller's bound read
scope, which is that member's (`ProjectCtx` for a route, the turn's scope for a tool). It flushes
and never commits; the caller emits the events, commits and publishes. New hardware is created in
the graph with no onboarder unless a Solus caller passes `in_graph`/`onboarded_by` — never a body.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import GraphReadScope
from solus_api.hardware.cad_suggestions import (
    accept_cad_suggestion,
    filter_visible_suggestions,
    is_cad_suggestion,
)
from solus_api.hardware.config import (
    BrainIdentity,
    ConfigDraft,
    FieldProvenance,
    LifecycleState,
    PartConfig,
    PortableTransportBinding,
    ProtocolBinding,
    ProvenanceRecord,
    TelemetryChannel,
)
from solus_api.hardware.connections import connection_state
from solus_api.hardware.detect import (
    ConfirmIn,
    ConfirmResult,
    ProposalOut,
    ProposeIn,
    bind_device,
    bound_repo_config_ids,
    confirm_proposal,
    detected_devices_wire,
    exclude_bound,
    propose_via_local,
    reconcile_device,
    validated_repo_root,
)
from solus_api.hardware.links import decide_suggestion, serialize_suggestion
from solus_api.hardware.local_runtime import plan_session, prepare_session
from solus_api.hardware.operations import HardwareEntityCreate, ReviewedHardwareOperations
from solus_api.hardware.proposal_cache import PROPOSALS
from solus_api.hardware.repo_evidence import read_repo_evidence
from solus_api.hardware.store import robot_root
from solus_api.models import GraphEntity, HardwareSuggestion

if TYPE_CHECKING:
    from solus_api.hardware.connections import HardwareConnections
    from solus_api.livebench.sessions import SessionManager

logger = logging.getLogger(__name__)
NO_RUNNER = "the local runner (livebench) is not installed on this server"


async def propose_detected(
    session: AsyncSession,
    local: Any,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    device_ref: str,
    options: ProposeIn,
) -> ProposalOut:
    """Interrogate the device within its budget, keep the proposal briefly for this member's
    confirm, and return it with the link suggestions this member may see (§1a)."""
    repo_root = validated_repo_root(options.repo_root)
    evidence = await read_repo_evidence(local, project_id, user_id, options.source_refs)
    fresh = await propose_via_local(
        local,
        device_ref,
        repo_root=repo_root,
        budget_s=options.budget_s,
        repo_sources=evidence.sources,
    )
    current = await read_repo_evidence(local, project_id, user_id, options.source_refs)
    if current.digest != evidence.digest:
        raise APIError(409, "source_changed", "The source changed during review. Propose again.")
    PROPOSALS.put(evidence.key(project_id, user_id, device_ref), fresh)
    proposal = exclude_bound(fresh, await bound_repo_config_ids(session, project_id))
    suggestions = await filter_visible_suggestions(
        session, project_id, user_id, await reconcile_device(session, project_id, proposal)
    )
    return proposal.model_copy(
        update={"suggestions": [serialize_suggestion(row) for row in suggestions]}
    )


@dataclass(frozen=True)
class Confirmation:
    """What a confirm wrote, and the connection attempt its caller schedules once committed."""

    result: ConfirmResult
    attempt_id: uuid.UUID | None
    proposal_reused: bool
    #: `perf_counter()` once the reviewed proposal was in hand (the caller's timing split).
    proposed_at: float


async def _enumerated(local: Any, device_ref: str) -> list[dict[str, Any]]:
    """The device as this machine lists it right now (opens no port)."""
    devices = detected_devices_wire(await asyncio.to_thread(local.detect_devices))
    return [device for device in devices if device["device_ref"] == device_ref]


async def _still_here(local: Any, device_ref: str) -> list[dict[str, Any]]:
    """The device as listed now, or 404 when it left since it was reviewed (opens no port)."""
    matching = await _enumerated(local, device_ref)
    if not matching:
        raise APIError(404, "device_not_found", "The device is no longer connected")
    return matching


def _same_connection(matching: list[dict[str, Any]], proposal: ProposalOut) -> None:
    """A connection-only confirm binds the device it reviewed, never a changed one."""
    expected = proposal.identity.model_dump(mode="json") if proposal.identity else None
    if (
        len(matching) != 1
        or matching[0].get("ambiguous")
        or expected is None
        or not isinstance(matching[0].get("identity"), dict)
        or any(
            matching[0]["identity"].get(key) != expected.get(key)
            for key in ("kind", "binding", "vid", "pid")
        )
    ):
        raise APIError(
            409, "device_changed", "Device identity changed; review the connection again"
        )


async def _reviewed_proposal(
    session: AsyncSession,
    local: Any,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    device_ref: str,
    body: ConfirmIn,
) -> tuple[ProposalOut, bool]:
    """The proposal a confirm accepts rows from, and whether it is this member's cached review:
    a cached one needs the device still here; otherwise the wire is asked again."""
    repo_root = validated_repo_root(body.repo_root)
    evidence = await read_repo_evidence(local, project_id, user_id, body.source_refs)
    # Source-backed confirmation must refer to this actor's still-current reviewed snapshot.
    cached = PROPOSALS.take(
        evidence.key(project_id, user_id, device_ref), [a.row_id for a in body.accepted]
    )
    if body.source_refs and cached is None:
        raise APIError(409, "proposal_changed", "Source review expired or changed. Propose again.")
    if cached is not None:
        await _still_here(local, device_ref)
    proposal = exclude_bound(
        cached
        if cached is not None
        else await propose_via_local(local, device_ref, repo_root=repo_root, budget_s=0.5),
        await bound_repo_config_ids(session, project_id),
    )
    return proposal, cached is not None


async def confirm_detected(
    session: AsyncSession,
    local: Any,
    connections: HardwareConnections,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    device_ref: str,
    body: ConfirmIn,
    in_graph: bool = True,
    onboarded_by: uuid.UUID | None = None,
) -> Confirmation:
    """Write the robot (new or existing), the accepted parts and the config the member reviewed.
    A session to start claims the local runtime first; the caller schedules the returned attempt
    after it commits."""
    proposal, reused = await _reviewed_proposal(
        session, local, project_id, user_id, device_ref, body
    )
    if body.connection_only:
        _same_connection(await _enumerated(local, device_ref), proposal)
    start_session = body.start_session and not body.connection_only
    runtime_id = await connections.ensure_owner() if start_session else None
    proposed_at = perf_counter()
    result = await confirm_proposal(
        session,
        project_id=project_id,
        proposal=proposal,
        body=body,
        created_by=user_id,
        in_graph=in_graph,
        onboarded_by=onboarded_by,
    )
    attempt_id = uuid.uuid4() if start_session else None
    if attempt_id is not None:
        result.robot.attrs = {
            **result.robot.attrs,
            "connection": connection_state(attempt_id, runtime_id=runtime_id),
        }
    return Confirmation(result, attempt_id, reused, proposed_at)


async def confirm_inspected(
    session: AsyncSession,
    local: Any,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: ProposalOut,
    body: ConfirmIn,
    in_graph: bool,
    onboarded_by: uuid.UUID | None,
) -> ConfirmResult:
    """SOL's add_parts and add_connection (SOLUSDEV-326 P2): the member's inspection, stamped on
    the card they approved, written as they saw it. The device must still be here — a bare
    connection the very one inspected — and nothing listens to it again; no session starts."""
    matching = await _still_here(local, proposal.device_ref)
    if body.connection_only:
        _same_connection(matching, proposal)
    return await confirm_proposal(
        session,
        project_id=project_id,
        proposal=proposal,
        body=body,
        created_by=user_id,
        in_graph=in_graph,
        onboarded_by=onboarded_by,
    )


async def add_inspected_board(
    session: AsyncSession,
    local: Any,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: ProposalOut,
    name: str,
    channels: list[str],
    key: uuid.UUID,
) -> tuple[dict[str, Any], bool]:
    """SOL's add_parts with no robot: a board streaming lines is ONE part, out of the graph for
    the member who inspected it, keyed by its device ref (`external_ref`), with one telemetry
    channel per column and how to reach it in its own config. The device must still be here;
    nothing listens to it again. Through the reviewed creator: the response, and whether it was
    a replay of `key`."""
    await _still_here(local, proposal.device_ref)
    identity = proposal.identity
    if identity is None or proposal.driver_id is None or proposal.stream is None:
        raise APIError(422, "validation_error", "Only a board that streams lines is added alone")
    detected = ProvenanceRecord(by=FieldProvenance.DETECTED)
    try:
        draft = ConfigDraft(
            component=PartConfig(
                telemetry=[TelemetryChannel(name=channel) for channel in channels],
                lifecycle=LifecycleState.LIVE,
            ),
            identity=[
                BrainIdentity(
                    binding=PortableTransportBinding(
                        kind=identity.kind,
                        binding=identity.binding,
                        vid=identity.vid,
                        pid=identity.pid,
                    ),
                    protocol=ProtocolBinding(driver_id=proposal.driver_id, params=proposal.params),
                )
            ],
            provenance={"component": detected, "identity": detected},
        )
    except ValidationError:
        raise APIError(422, "validation_error", "The board's channels cannot be stored") from None
    return await ReviewedHardwareOperations(session, project_id, user_id).create(
        key,
        HardwareEntityCreate(kind="part", name=name, config=draft),
        in_graph=False,
        onboarded_by=user_id,
        external_ref=proposal.device_ref,
    )


@dataclass(frozen=True)
class Decision:
    """A decided suggestion and what accepting it linked, for the caller's events and reply."""

    row: HardwareSuggestion
    #: `bound`, `robot_id`, `session_id`, `session_error`, `bind_error`, as the routes answer.
    binding: dict[str, Any]
    #: Parts an accepted CAD suggestion attached to its robot.
    attached_count: int = 0

    @property
    def device_bound(self) -> bool:
        return self.row.subject_kind == "device" and bool(self.binding["bound"])


async def decide_and_link(
    session: AsyncSession,
    local: Any,
    manager: SessionManager,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    accept: bool,
    reason: str | None,
) -> Decision:
    """Accept or reject one link suggestion as `user_id`. Accepting a device binds it to the
    robot and starts the robot's session; accepting a CAD part attaches the part."""
    # SOLUSDEV-326: a suggestion naming a robot out of the graph is its onboarder's alone —
    # decided by no one else, refused before anything (a 409 would say it exists).
    pending = await session.get(HardwareSuggestion, suggestion_id)
    if pending is not None and pending.project_id == project_id:
        robot = await session.get(GraphEntity, pending.candidate_robot_id)
        if robot is not None and GraphReadScope(project_id, viewer_id=user_id).hides(robot.attrs):
            raise APIError(404, "not_found", "Suggestion not found")
    row = await decide_suggestion(
        session, project_id, suggestion_id, accept, user_id, reason=reason
    )
    binding: dict[str, Any] = {
        "bound": False,
        "robot_id": row.candidate_robot_id,
        "session_id": None,
        "session_error": None,
        "bind_error": None,
    }
    if accept and row.subject_kind == "device":
        binding.update(await _bind_device(session, local, manager, project_id, user_id, row))
    elif accept and is_cad_suggestion(row):
        outcome = await accept_cad_suggestion(session, project_id, row, user_id)
        attached = outcome.pop("attached_count", 0)
        return Decision(row, {**binding, **outcome}, attached)
    return Decision(row, binding)


async def _bind_device(
    session: AsyncSession,
    local: Any,
    manager: SessionManager,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    row: HardwareSuggestion,
) -> dict[str, Any]:
    """An accepted device suggestion binds the wire to that robot: re-propose (the wire is the
    truth), write identity/protocol/bus map, key the parts, open the session. A refused bind
    writes nothing: its savepoint is undone and the caller commits only the decision."""
    if local is None:
        return {"bind_error": NO_RUNNER}
    try:
        async with session.begin_nested():
            proposal = exclude_bound(
                await propose_via_local(local, row.subject_ref, repo_root=None, budget_s=0.5),
                await bound_repo_config_ids(session, project_id),
            )
            robot = await robot_root(session, project_id, row.candidate_robot_id)
            await bind_device(session, project_id, robot, proposal, created_by=user_id)
    except APIError as exc:
        return {"bind_error": exc.message}
    session_id, session_error = await start_robot_session(
        manager, local, project_id, robot, 1.0, session=session, account_id=user_id
    )
    return {"bound": True, "session_id": session_id, "session_error": session_error}


async def start_robot_session(
    manager: SessionManager,
    local: Any,
    project_id: uuid.UUID,
    robot: GraphEntity,
    window_seconds: float,
    *,
    session: AsyncSession,
    account_id: uuid.UUID,
) -> tuple[uuid.UUID | None, str | None]:
    """Open the robot's session through the one shared opener (SOLUSDEV-326); the robot exists
    either way, so a session that does not start is reported, never raised."""
    try:
        plan = await plan_session(local, session, project_id, robot)
        opener = await prepare_session(local, plan, account_id)
        record = await manager.start(
            project_id,
            mode="real",
            provider="robot",
            label=opener.label,
            open_conn=opener.open,
            window_seconds=window_seconds,
            device=opener.device,
            # SOLUSDEV-321 P2-T3: the robot's session runs its window evaluator as this member
            robot_entity_id=robot.id,
            owner_user_id=account_id,
        )
    except APIError as exc:
        return None, exc.message
    except Exception as exc:
        logger.warning("session after binding failed: %s", type(exc).__name__)
        return None, f"{type(exc).__name__}: the session did not start"
    return record.id, None
