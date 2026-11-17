"""Detection routes' service half (R2, docs/api/hardware.md §4).

The local runtime (livebench, loaded through `load_local`) enumerates, interrogates and
proposes; this module re-validates what crosses that duck-typed boundary and turns the user's
confirmation into graph and config writes: a Physical Robot (new or existing), one `part`
entity per accepted row keyed by `<device ref>/<address>`, and a HardwareConfig whose layers
record what came from the wire (`detected`) and what came from the repo (`repo`). Nothing is
accepted that the body did not name; two matching repo configs are a question, never a guess.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.graph.read_scope import current_scope
from solus_api.hardware.bindings import bound_elsewhere
from solus_api.hardware.config import (
    BusMapEntry,
    CalibrationMode,
    ConfigLayer,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    TransportBinding,
    merge_layers,
    part_ref,
    pin_rows,
    unit_for_mode,
)
from solus_api.hardware.links import (
    LinkSuggestion,
    LinkTier,
    PartObservation,
    RobotCandidate,
    list_suggestions,
    persist_suggestions,
    suggest_links,
)
from solus_api.hardware.repo_evidence import SourceRefs
from solus_api.hardware.runtime import bound_refs, brains_of, resolve_runtime_config
from solus_api.hardware.store import (
    PART_KIND,
    attach_part,
    ensure_config,
    put_config,
    robot_root,
)
from solus_api.livebench.sessions import DeviceBusyError
from solus_api.models import (
    GraphEntity,
    HardwareSuggestion,
    SolusEntry,
    SolusEntryKind,
    SuggestionStatus,
)
from solus_api.services.physical_robots import PhysicalRobotService, RobotName
from solus_api.services.solus_graph import lock_project

MAX_ACCEPTED_ROWS = 256
MAX_REPO_ROOT_CHARS = 4096
MAX_STREAM_CHANNELS = 64
PROPOSE_TIMEOUT_S: Final = 30.0
IdentityBasis = Literal["serial", "port_position", "none"]
Tone = Literal["looks_like", "probably", "something"]


class _Wire(BaseModel):
    """What the local runtime hands over is data, re-validated here (extra keys refused)."""

    model_config = ConfigDict(extra="forbid")


class DetectedDeviceOut(_Wire):
    transport: str
    device_ref: str | None
    identity: TransportBinding | None
    level: Literal["transport", "board", "protocol", "platform"]
    board: str | None
    board_class: str | None
    mcu_known: bool
    confidence: float = Field(ge=0, le=1)
    evidence: list[ModalityMatch]
    ambiguous: bool
    last_seen_path: str | None
    vid: int | None = None
    pid: int | None = None
    headline: str = Field(default="", max_length=128)
    identity_basis: IdentityBasis = "serial"
    #: SOLUSDEV-326 — filled API-side for each reader (`hardware/device_memory.annotate`), never
    #: by the local runtime: the robot or part whose config or ref binds the device (when the
    #: reader may see it), whether the reader said "Not now" to it, and when this machine last
    #: saw it (its owner's alone).
    bound_to: uuid.UUID | None = None
    dismissed: bool = False
    last_seen: str | None = None


class StreamOut(_Wire):
    """A line stream's shape, with the columns named when the user's repo agrees."""

    framing: str = Field(max_length=32)
    channel_count: int = Field(ge=0, le=MAX_STREAM_CHANNELS)
    update_hz: float = Field(ge=0)
    channel_names: list[Annotated[str, StringConstraints(max_length=128)]] | None = Field(
        default=None, max_length=MAX_STREAM_CHANNELS
    )
    declared_hz: float | None = None


class RepoPartOut(_Wire):
    name: str = Field(max_length=128)
    address: str = Field(max_length=64)
    model: str | None = None
    calibration_mode: CalibrationMode | None = None
    calibration: dict[str, float | int] | None = None
    calibration_source: str | None = Field(default=None, max_length=1024)


class RepoMatchOut(_Wire):
    config_id: str = Field(max_length=256)
    parser_id: str
    label: str = Field(max_length=256)
    source: str = Field(max_length=1024)
    protocol_hint: str | None = None
    parts: list[RepoPartOut] = Field(default_factory=list, max_length=MAX_ACCEPTED_ROWS)
    port_hint: str | None = None
    calibration_source: str | None = Field(default=None, max_length=1024)
    params: dict[str, Any] = Field(default_factory=dict)


class ProposalRowOut(_Wire):
    id: str = Field(max_length=600)
    subject: str
    address: str = Field(max_length=64)
    model: str | None
    proposed_function: str | None
    confidence: float | None
    evidence: list[ModalityMatch]
    provenance: Literal["bus", "repo"]


class DisambiguationOut(_Wire):
    question: str
    options: list[str]
    favoured: list[str] = Field(default_factory=list)  # wire evidence, never an answer


class PortRepair(_Wire):
    """The repo binds a port path that is not where the device is now. Solus does not edit
    the repo (a write through the confirmation gate is a later SOL action); it says so."""

    kind: Literal["file", "command"]
    configured: str | None
    actual: str
    source: str | None
    note: str


class ProposalOut(_Wire):
    device_ref: str
    identity: TransportBinding | None = None
    level: Literal["transport", "board", "protocol", "platform"]
    summary: str = Field(max_length=1024)
    driver_id: str | None
    params: dict[str, Any]
    rows: list[ProposalRowOut] = Field(max_length=MAX_ACCEPTED_ROWS)
    repo_matches: list[RepoMatchOut] = Field(default_factory=list)
    disambiguation: DisambiguationOut | None
    confidence: float = Field(ge=0, le=1)
    evidence: list[ModalityMatch] = Field(default_factory=list)
    calibration_source: str | None = Field(default=None, max_length=1024)
    headline: str = Field(default="", max_length=128)
    tone: Tone = "something"  # confidence shown as tone (SOLUSDEV-250)
    stream: StreamOut | None = None
    identity_basis: IdentityBasis = "serial"
    # API-side additions (the local runtime never sends these):
    bound_repo_configs: list[str] = Field(default_factory=list)
    port_repair: PortRepair | None = None
    #: Pending link suggestions for this device (a library-imported robot it may BE).
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class ProposeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_refs: SourceRefs = Field(default_factory=list)
    repo_root: str | None = Field(default=None, min_length=1, max_length=MAX_REPO_ROOT_CHARS)
    budget_s: float = Field(default=0.5, ge=0.05, le=5.0)


class AcceptedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: str = Field(min_length=1, max_length=600)
    function_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
        | None
    ) = None


class NewRobotTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["new"]
    name: RobotName | None = None


class ExistingRobotTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["existing"]
    robot_id: uuid.UUID


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Annotated[NewRobotTarget | ExistingRobotTarget, Field(discriminator="kind")]
    accepted: list[AcceptedRow] = Field(max_length=MAX_ACCEPTED_ROWS)
    connection_only: StrictBool = False
    repo_config_id: str | None = Field(default=None, max_length=256)
    source_refs: SourceRefs = Field(default_factory=list)
    repo_root: str | None = Field(default=None, min_length=1, max_length=MAX_REPO_ROOT_CHARS)
    start_session: bool = True
    window_seconds: float = Field(default=1.0, gt=0, le=86400)

    @model_validator(mode="after")
    def validate_acceptance(self) -> ConfirmIn:
        if self.connection_only:
            if self.accepted or self.repo_config_id is not None:
                raise ValueError(
                    "Connection-only acceptance cannot include parts or repo configuration"
                )
        elif not self.accepted:
            raise ValueError("Accept at least one proposed part")
        return self


def validated_repo_root(raw: str | None) -> str | None:
    """A request path is not picker authorization, even on a local API host."""
    if raw is None:
        return None
    raise APIError(
        422,
        "validation_error",
        "A directory path cannot authorize local files. Relink sources using the file picker.",
    )


def detected_devices_wire(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the local enumeration shared by HTTP and device events."""
    return [DetectedDeviceOut.model_validate(item).model_dump(mode="json") for item in raw]


async def propose_via_local(
    local: Any,
    device_ref: str,
    *,
    repo_root: str | None,
    budget_s: float,
    repo_sources: list[dict[str, Any]] | None = None,
    listener: tuple[uuid.UUID, uuid.UUID] | None = None,
) -> ProposalOut:
    """Run the local runtime's interrogation off-loop and re-validate its proposal. `listener`
    is the (project, member) it interrogates for (SOLUSDEV-326): that member's own session there
    is listened to; without it the interrogation is nobody's and every holder is only busy."""
    options: dict[str, Any] = {"repo_root": repo_root, "budget_s": budget_s}
    if repo_sources:
        options["repo_sources"] = repo_sources
    if listener is not None:
        options["scope"], options["member"] = str(listener[0]), str(listener[1])
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(local.propose_device, device_ref, **options),
            PROPOSE_TIMEOUT_S,
        )
    except ValueError as exc:
        raise APIError(
            422, "invalid_source", "The selected source could not be parsed. Review its contents."
        ) from exc
    except DeviceBusyError as exc:  # SOLUSDEV-326: busy was read as "no protocol recognised"
        raise APIError(409, "device_busy", str(exc), details=exc.details()) from exc
    except TimeoutError as exc:
        # The worker thread cannot be cancelled and finishes on its own; the request just
        # stops waiting for it.
        raise APIError(
            503, "source_unavailable", "the local runner did not answer in time"
        ) from exc
    if raw is None:
        raise APIError(404, "device_not_found", f"{device_ref} is not connected to this machine")
    try:
        return ProposalOut.model_validate(raw)
    except ValueError as exc:
        raise APIError(
            503, "source_unavailable", "the local runner returned an unreadable proposal"
        ) from exc


async def bound_repo_config_ids(session: AsyncSession, project_id: uuid.UUID) -> set[str]:
    """Repo configs already bound to a robot in this project (the repo layer's source)."""
    entries = await session.scalars(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
        )
    )
    bound: set[str] = set()
    for entry in entries:
        for record in ((entry.payload or {}).get("provenance") or {}).values():
            if record.get("by") == FieldProvenance.REPO.value and record.get("source"):
                bound.add(str(record["source"]))
    return bound


def _repair(identity: TransportBinding | None, match: RepoMatchOut | None) -> PortRepair | None:
    if identity is None or match is None or not identity.last_seen_path:
        return None
    actual = identity.last_seen_path
    if match.port_hint is None:
        return PortRepair(
            kind="command",
            configured=None,
            actual=actual,
            source=match.source,
            note=(
                f"{match.label} binds no port file — pass {actual} wherever your tooling "
                "takes the port (a port path is never Solus's identity for this device)"
            ),
        )
    if match.port_hint == actual:
        return None
    return PortRepair(
        kind="file",
        configured=match.port_hint,
        actual=actual,
        source=match.source,
        note=(
            f"{match.label} says {match.port_hint} but this device is on {actual}. Solus does "
            "not edit your repo yet — update it there, or bind by the by-id path"
        ),
    )


def exclude_bound(proposal: ProposalOut, bound: set[str]) -> ProposalOut:
    """Drop repo configs already bound to another device; when one config remains, name the
    rows from it (the second arm is offered the one remaining config, never a question)."""
    remaining = [m for m in proposal.repo_matches if m.config_id not in bound]
    excluded = sorted(m.config_id for m in proposal.repo_matches if m.config_id in bound)
    rows = proposal.rows
    if len(remaining) == 1:
        names = {p.address: p.name for p in remaining[0].parts}
        rows = [
            row.model_copy(
                update={"proposed_function": names.get(row.address), "provenance": "repo"}
            )
            if row.proposed_function is None and row.address in names
            else row
            for row in proposal.rows
        ]
    remaining_ids = {m.config_id for m in remaining}
    disambiguation = (
        proposal.disambiguation.model_copy(
            update={
                "options": [c for c in proposal.disambiguation.options if c in remaining_ids],
                "favoured": [c for c in proposal.disambiguation.favoured if c in remaining_ids],
            }
        )
        if proposal.disambiguation is not None and len(remaining) > 1
        else None
    )
    return proposal.model_copy(
        update={
            "repo_matches": remaining,
            "rows": rows,
            "disambiguation": disambiguation,
            "bound_repo_configs": excluded,
            "port_repair": _repair(
                proposal.identity, remaining[0] if len(remaining) == 1 else None
            ),
            "calibration_source": (
                remaining[0].calibration_source if len(remaining) == 1 else None
            ),
        }
    )


def _chosen_repo_config(proposal: ProposalOut, repo_config_id: str | None) -> RepoMatchOut | None:
    matches = {m.config_id: m for m in proposal.repo_matches}
    if repo_config_id is not None:
        if repo_config_id not in matches:
            raise APIError(422, "validation_error", "repo_config_id is not one of the matches")
        return matches[repo_config_id]
    if len(matches) > 1:
        assert proposal.disambiguation is not None
        raise APIError(422, "validation_error", proposal.disambiguation.question)
    return next(iter(matches.values()), None)


async def _named_holder(
    session: AsyncSession, project_id: uuid.UUID, robot_id: object, *held: GraphEntity
) -> str:
    """The robot a refusal says holds a device or row: `robot <id>` only when the bound reader
    may see it and what it holds, else other hardware — a refusal never names hardware its
    reader cannot see (§1a)."""
    try:
        robot = await session.get(GraphEntity, uuid.UUID(str(robot_id)))
    except ValueError:  # held by no robot (a lone part names none)
        robot = None
    scope = current_scope(project_id)
    if (
        robot is None
        or robot.project_id != project_id
        or any(scope.hides(entity.attrs) for entity in (robot, *held))
    ):
        return "other hardware in this project"
    return f"robot {robot.id}"


async def _already_confirmed(
    session: AsyncSession, project_id: uuid.UUID, row_ids: list[str]
) -> None:
    owned = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == PART_KIND,
            GraphEntity.external_ref.in_(row_ids),
            GraphEntity.deleted_at.is_(None),
        )
    )
    if owned is not None:
        holder = await _named_holder(session, project_id, owned.attrs.get("robot_id"), owned)
        raise APIError(
            409,
            "conflict",
            f"{owned.external_ref} is already part of {holder} — "
            "reconnecting a known machine needs no second robot",
        )


async def robot_candidates(session: AsyncSession, project_id: uuid.UUID) -> list[RobotCandidate]:
    """Every live manual robot in the project that has a config (the link engine's input)."""
    config_node = aliased(GraphEntity)
    robots = await session.scalars(
        select(GraphEntity)
        .join(SolusEntry, SolusEntry.configured_entity_id == GraphEntity.id)
        .join(config_node, config_node.id == SolusEntry.entity_id)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            GraphEntity.project_id == project_id,
            GraphEntity.kind == "physical_robot",
            GraphEntity.origin == "manual",
            GraphEntity.source_id.is_(None),
            GraphEntity.deleted_at.is_(None),
            config_node.project_id == project_id,
            config_node.kind == "hardware_config",
            config_node.deleted_at.is_(None),
        )
    )
    candidates: list[RobotCandidate] = []
    for robot in robots:
        config = await resolve_runtime_config(session, project_id, robot.id)
        candidates.append(RobotCandidate(robot_entity_id=robot.id, name=robot.name, config=config))
    return candidates


async def _refuse_bound_elsewhere(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID, device_ref: str
) -> None:
    """One config per device project-wide, checked before anything is written: another robot's
    stored brains (a backfilled config has no binding edge yet) or another subject's current
    binding (a lone part's board) already holding the device refuse the bind."""
    await lock_project(session, project_id)
    robots = await robot_candidates(session, project_id)
    held = any(c.robot_entity_id != robot_id and device_ref in bound_refs(c.config) for c in robots)
    if held or await bound_elsewhere(session, project_id, robot_id, {device_ref}):
        raise APIError(
            409,
            "binding_conflict",
            f"{device_ref} is already bound to other hardware in this project; "
            "review its existing binding",
        )


async def _retained_owner(
    session: AsyncSession,
    project_id: uuid.UUID,
    proposal: ProposalOut,
    candidates: list[RobotCandidate],
) -> tuple[bool, list[LinkSuggestion]]:
    """Exact accepted part identity survives removing the robot's USB binding.

    A shared/corrupt ownership claim fails closed rather than falling back to model overlap.
    """
    if proposal.identity is None or proposal.identity.device_ref != proposal.device_ref:
        return False, []
    if not any(match.modality is Modality.BUS_ENUMERATION for match in proposal.evidence):
        return False, []
    fresh = {row.id: row for row in proposal.rows}
    parts = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == PART_KIND,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.external_ref.in_(fresh),
            )
        )
    )
    if not parts:
        return False, []
    eligible = {str(candidate.robot_entity_id): candidate for candidate in candidates}
    owners: set[str] = set()
    evidence: list[ModalityMatch] = []
    for part in parts:
        if part.external_ref is None:
            return True, []
        row = fresh[part.external_ref]
        if row.id != part_ref(proposal.device_ref, row.address):
            return True, []
        owner = part.attrs.get("robot_id")
        if not isinstance(owner, str):
            return True, []
        candidate = eligible.get(owner)
        if (
            candidate is None
            or bound_refs(candidate.config)
            or part.attrs.get("device_ref") != proposal.device_ref
            or part.attrs.get("address") != row.address
            or str(part.id) not in candidate.config.parts
            or not any(
                entry.part_entity_id == part.id
                and entry.address == row.address
                and entry.protocol == proposal.driver_id
                for entry in candidate.config.bus_map
            )
        ):
            return True, []
        owners.add(owner)
        evidence.append(
            ModalityMatch(
                modality=Modality.BUS_ENUMERATION,
                source_ref=SourceRef(graph_entity_id=part.id, external_ref=part.external_ref),
                confidence=0.8,
                state=MatchState.MATCHED,
                evidence={
                    "matched_on": "retained_part_binding",
                    "device_ref": proposal.device_ref,
                    "address": row.address,
                },
            )
        )
    if len(owners) != 1:
        return True, []
    return True, [
        LinkSuggestion(
            subject_ref=proposal.device_ref,
            subject_kind="device",
            candidate_robot_id=uuid.UUID(next(iter(owners))),
            confidence=0.8,
            tier=LinkTier.HIGH,
            evidence=evidence,
            reason="Previously accepted part identities match this device and one saved robot",
        )
    ]


async def reconcile_device(
    session: AsyncSession, project_id: uuid.UUID, proposal: ProposalOut
) -> list[HardwareSuggestion]:
    """Run the link engine for a detected device against every configured robot and keep
    the suggestions (precision over recall: nothing links until the user accepts)."""
    if proposal.driver_id is None or not proposal.rows:
        return []
    await lock_project(session, project_id)
    observation = PartObservation(
        subject_ref=proposal.device_ref,
        subject_kind="device",
        device_ref=proposal.device_ref,
        driver_id=proposal.driver_id,
        evidence=list(proposal.evidence),
        bus_map=[
            BusMapEntry(protocol=proposal.driver_id, address=row.address, model=row.model)
            for row in proposal.rows
        ],
    )
    # A robot with a brain already bound to THIS device is not a candidate — nothing to link.
    candidates = [
        c
        for c in await robot_candidates(session, project_id)
        if proposal.device_ref not in bound_refs(c.config)
    ]
    retained, suggestions = await _retained_owner(session, project_id, proposal, candidates)
    if not retained:
        suggestions = suggest_links(observation, candidates)
    await persist_suggestions(session, project_id, suggestions)
    pending = await list_suggestions(session, project_id, status=SuggestionStatus.PENDING)
    return [row for row in pending if row.subject_ref == proposal.device_ref]


def _landing(saved: HardwareConfig, device_ref: str) -> HardwareConfig | None:
    """The saved brain a device lands on: its own, else the first still waiting for a
    device; None when the device joins the robot as a new brain."""
    brains = brains_of(saved)
    own = [b for b in brains if b.identity is not None and b.identity.device_ref == device_ref]
    waiting = [b for b in brains if b.identity is None]
    return next(iter(own or waiting), None)


def aimed_at(config: HardwareConfig, device_ref: str) -> HardwareConfig:
    """`config` as the v1 document of the brain `device_ref` lands on, which is the brain
    `put_config` merges it into: rows that sat implicitly on the document's brain name it
    first, and identity and protocol (with their records) become the landing brain's — none
    for a new brain, whose identity the caller sets."""
    brain = _landing(config, device_ref)
    current = config.identity.device_ref if config.identity else None
    if brain is not None and (brain.identity.device_ref if brain.identity else None) == current:
        return config
    document = config.model_dump(mode="json")
    if current is not None:
        pin_rows(document, current)
    heads = ("identity", "protocol")
    document["provenance"] = {
        path: record
        for path, record in document["provenance"].items()
        if path.split(".")[0] not in heads
    }
    document["identity"] = document["protocol"] = None
    if brain is not None:
        document.update(brain.model_dump(mode="json", include=set(heads)))
        document["provenance"].update(
            {
                path: record.model_dump(mode="json")
                for path, record in brain.provenance.items()
                if path.split(".")[0] in heads
            }
        )
    return HardwareConfig.model_validate(document)


def _rows_on(document: dict[str, Any], device_ref: str) -> list[int]:
    """Rows of an aimed v1 document that sit on its brain: implicit, or naming it."""
    return [
        index
        for index, row in enumerate(document["bus_map"])
        if row.get("brain") in (None, device_ref)
    ]


def _mark_live(document: dict[str, Any], answered: set[str], rows: list[int]) -> None:
    """A bound part that answered at its bus-map address is live — by detection."""
    for index in rows:
        entry = document["bus_map"][index]
        part_id = entry.get("part_entity_id")
        if part_id in document["parts"] and entry["address"] in answered:
            document["parts"][part_id]["lifecycle"] = LifecycleState.LIVE.value
            document["provenance"][f"parts.{part_id}.lifecycle"] = {
                "by": FieldProvenance.DETECTED.value,
                "source": None,
            }


def _detected_rows(
    document: dict[str, Any], proposal: ProposalOut, driver_id: str, rows: list[int]
) -> None:
    """The wire's rows on this brain: a saved row keeps its part, a new address joins."""
    by_address = {document["bus_map"][index]["address"]: index for index in rows}
    for row in proposal.rows:
        index = by_address.get(row.address)
        if index is None:
            document["bus_map"].append(
                {
                    "protocol": driver_id,
                    "address": row.address,
                    "part_entity_id": None,
                    "model": row.model,
                }
            )
            rows.append(len(document["bus_map"]) - 1)
        else:
            entry = document["bus_map"][index]
            entry["protocol"] = driver_id
            entry["model"] = entry.get("model") or row.model


async def bind_device(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    proposal: ProposalOut,
    *,
    created_by: uuid.UUID,
) -> HardwareConfig:
    """Bind a detected device to an existing robot (an accepted suggestion): the wire's
    identity, driver and parameters enter the config as `detected` on the brain this device
    is — a device new to the robot joins as another brain; one another config in the project
    binds is refused before anything is written — that brain's bus map keeps the robot's
    parts, and each of its parts' external_ref becomes `<device ref>/<address>` so its
    telemetry resolves."""
    if proposal.identity is None or proposal.driver_id is None:
        raise APIError(422, "validation_error", "this device has no protocol to bind yet")
    await _refuse_bound_elsewhere(session, project_id, robot.id, proposal.identity.device_ref)
    _, config = await ensure_config(session, project_id, robot, created_by=created_by)
    document = aimed_at(config, proposal.device_ref).model_dump(mode="json")
    document["identity"] = proposal.identity.model_dump(mode="json")
    document["protocol"] = {"driver_id": proposal.driver_id, "params": dict(proposal.params)}
    rows = _rows_on(document, proposal.device_ref)
    _detected_rows(document, proposal, proposal.driver_id, rows)
    detected = {"by": FieldProvenance.DETECTED.value, "source": None}
    stale = ("identity", "protocol", *(f"bus_map.{index}" for index in rows))
    document["provenance"] = {
        path: record
        for path, record in document["provenance"].items()
        if not any(path == head or path.startswith(f"{head}.") for head in stale)
    }
    document["provenance"].update({head: detected for head in stale})
    _mark_live(document, {row.address for row in proposal.rows}, rows)
    bound = HardwareConfig.model_validate(document)
    await put_config(session, project_id, robot, bound, created_by=created_by)
    for entry in (bound.bus_map[index] for index in rows):
        if entry.part_entity_id is None:
            continue
        part = await session.get(GraphEntity, entry.part_entity_id)
        if part is None or part.project_id != project_id or part.deleted_at is not None:
            continue
        ref = part_ref(proposal.device_ref, entry.address)
        await _already_confirmed(session, project_id, [ref]) if part.external_ref != ref else None
        part.external_ref = ref
        part.attrs = {**part.attrs, "device_ref": proposal.device_ref, "address": entry.address}
    await session.flush()
    return bound


class ConfirmResult(BaseModel):
    robot: GraphEntity
    part_ids: list[uuid.UUID]
    config: HardwareConfig
    document: dict[str, Any]
    created_robot: bool

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _merge_confirmation(saved: HardwareConfig, additions: HardwareConfig) -> HardwareConfig:
    """Append reviewed new parts without replacing the owner's saved decisions; the merge is
    on the brain the device lands on (a device new to the robot joins as another brain)."""
    _check_saved_connection(saved, additions)
    if additions.identity is not None:
        saved = aimed_at(saved, additions.identity.device_ref)
    document = saved.model_dump(mode="json")
    provenance = {
        path: saved.provenance_of(path).model_dump(mode="json") for path in saved.leaf_paths()
    }
    incoming = additions.model_dump(mode="json")
    _fill_brain(document, provenance, additions)
    document["parts"].update(incoming["parts"])
    for path in additions.leaf_paths():
        if path.startswith("parts."):
            provenance[path] = additions.provenance_of(path).model_dump(mode="json")
    offset = len(document["bus_map"])
    document["bus_map"].extend(incoming["bus_map"])
    for index, row in enumerate(incoming["bus_map"]):
        for key, value in row.items():
            if value is not None:
                provenance[f"bus_map.{offset + index}.{key}"] = additions.provenance_of(
                    f"bus_map.{index}.{key}"
                ).model_dump(mode="json")
    document["provenance"] = provenance
    return HardwareConfig.model_validate(document)


def _fill_brain(
    document: dict[str, Any], provenance: dict[str, Any], additions: HardwareConfig
) -> None:
    """What the landing brain does not say yet (identity, driver, disambiguation) comes from
    the review, with its records."""
    incoming = additions.model_dump(mode="json")
    for field in ("identity", "protocol", "disambiguated_by"):
        if document[field] is None:
            document[field] = incoming[field]
            for path in additions.leaf_paths():
                if path == field or path.startswith(f"{field}."):
                    provenance[path] = additions.provenance_of(path).model_dump(mode="json")


def _check_saved_connection(saved: HardwareConfig, additions: HardwareConfig) -> None:
    """A review for adding parts cannot authorize replacing the connection of the brain the
    device lands on (compared per brain; a device new to the robot replaces nothing)."""
    brain = _landing(saved, additions.identity.device_ref) if additions.identity else saved
    if brain is None:
        return
    if brain.protocol is not None and brain.protocol != additions.protocol:
        raise APIError(409, "proposal_changed", "Saved protocol differs; review configuration")
    endpoints = {(row.protocol, row.address) for row in brain.bus_map}
    if any((row.protocol, row.address) in endpoints for row in additions.bus_map):
        raise APIError(
            409, "proposal_changed", "A proposed bus address already has a saved binding"
        )


def _connection_lands(saved: HardwareConfig, identity: TransportBinding) -> None:
    """A bare connection may bind a brain still waiting for its device, or join as a new
    brain — never take over a brain that has a driver or bus rows."""
    brain = _landing(saved, identity.device_ref)
    if brain is None:
        return
    if brain.identity is not None and (
        brain.identity.vid != identity.vid or brain.identity.pid != identity.pid
    ):
        raise APIError(409, "proposal_changed", "Saved USB identity differs; review configuration")
    if brain.protocol is not None or brain.bus_map:
        raise APIError(
            409, "conflict", "Connection-only acceptance cannot replace configured hardware"
        )


def accepted_part_name(
    robot_name: str,
    address: str,
    accepted: str | None,
    proposed: str | None,
    repo: str | None,
    *,
    streamed: bool,
) -> str:
    """Preserve evidence names; an unnamed row is a motor at its stable bus address, or on a
    line stream (`streamed`) the reading at that column (SOLUSDEV-326: no body says which)."""
    return (
        accepted
        or proposed
        or repo
        or (f"address {address}" if streamed else f"{robot_name}-Motor-{address}")
    )


async def _confirm_connection(
    session: AsyncSession,
    project_id: uuid.UUID,
    proposal: ProposalOut,
    body: ConfirmIn,
    created_by: uuid.UUID,
    *,
    in_graph: bool,
    onboarded_by: uuid.UUID | None,
) -> ConfirmResult:
    identity = proposal.identity
    if (
        identity is None
        or identity.kind.value != "usb_serial"
        or identity.device_ref != proposal.device_ref
        or proposal.driver_id is not None
        or proposal.rows
        or proposal.params
        or proposal.stream is not None
    ):
        raise APIError(422, "validation_error", "Only an unidentified USB connection is eligible")
    await lock_project(session, project_id)
    candidates = await robot_candidates(session, project_id)
    owner = next((c for c in candidates if identity.device_ref in bound_refs(c.config)), None)
    if owner is not None:
        if body.target.kind == "existing" and body.target.robot_id != owner.robot_entity_id:
            holder = await _named_holder(session, project_id, owner.robot_entity_id)
            raise APIError(409, "conflict", f"Connection already belongs to {holder}")
        robot = await robot_root(session, project_id, owner.robot_entity_id)
        saved = owner.config
        created = False
    elif body.target.kind == "existing":
        robot = await robot_root(session, project_id, body.target.robot_id)
        saved = await resolve_runtime_config(session, project_id, robot.id)
        created = False
    else:
        robot = await PhysicalRobotService(session).create(
            project_id, body.target.name, in_graph=in_graph, onboarded_by=onboarded_by
        )
        saved = None
        created = True
    config = merge_layers(
        robot.id,
        [
            ConfigLayer(
                by=FieldProvenance.DETECTED, document={"identity": identity.model_dump(mode="json")}
            )
        ],
    )
    if saved is not None:
        _connection_lands(saved, identity)
        config = _merge_confirmation(saved, config)
    entry = await put_config(session, project_id, robot, config, created_by=created_by)
    return ConfirmResult(
        robot=robot,
        part_ids=[],
        config=config,
        document=dict(entry.payload or {}),
        created_robot=created,
    )


async def confirm_proposal(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    proposal: ProposalOut,
    body: ConfirmIn,
    created_by: uuid.UUID,
    in_graph: bool = True,
    onboarded_by: uuid.UUID | None = None,
) -> ConfirmResult:
    """Graph + config writes for a confirmation. Flushes; the caller owns the commit. A new
    robot is created in the graph or, for its onboarder alone, out of it (SOLUSDEV-326); its
    parts, brains and config nodes follow it."""
    if body.connection_only:
        return await _confirm_connection(
            session,
            project_id,
            proposal,
            body,
            created_by,
            in_graph=in_graph,
            onboarded_by=onboarded_by,
        )
    if proposal.identity is None or proposal.driver_id is None:
        raise APIError(422, "validation_error", "this device has no protocol to confirm yet")
    if proposal.identity.device_ref != proposal.device_ref:
        raise APIError(409, "proposal_changed", "The device's identity changed; propose again")
    rows = {row.id: row for row in proposal.rows}
    unknown = [a.row_id for a in body.accepted if a.row_id not in rows]
    if unknown:
        raise APIError(422, "validation_error", f"unknown proposal rows: {', '.join(unknown[:5])}")
    await _already_confirmed(session, project_id, [a.row_id for a in body.accepted])
    chosen = _chosen_repo_config(proposal, body.repo_config_id)
    repo_parts = {p.address: p for p in chosen.parts} if chosen is not None else {}

    saved: HardwareConfig | None = None
    if body.target.kind == "new":
        robot = await PhysicalRobotService(session).create(
            project_id, body.target.name, in_graph=in_graph, onboarded_by=onboarded_by
        )
        created = True
    else:
        await lock_project(session, project_id)
        robot = await robot_root(session, project_id, body.target.robot_id)
        created = False
        saved = await resolve_runtime_config(session, project_id, robot.id)

    detected: dict[str, Any] = {
        "identity": proposal.identity.model_dump(mode="json"),
        "protocol": {"driver_id": proposal.driver_id, "params": dict(proposal.params)},
        "bus_map": [],
        "parts": {},
    }
    repo: dict[str, Any] = {"parts": {}}
    part_ids: list[uuid.UUID] = []
    for accepted in body.accepted:
        row = rows[accepted.row_id]
        repo_part = repo_parts.get(row.address)
        name = accepted_part_name(
            robot.name,
            row.address,
            accepted.function_name,
            row.proposed_function,
            repo_part.name if repo_part else None,
            streamed=proposal.stream is not None,
        )
        part = await attach_part(
            session,
            project_id,
            robot,
            name=name,
            attrs={"address": row.address, "model": row.model, "device_ref": proposal.device_ref},
            provenance=FieldProvenance.REPO if repo_part else FieldProvenance.DETECTED,
            external_ref=row.id,
        )
        part_ids.append(part.id)
        detected["bus_map"].append(
            {
                "protocol": proposal.driver_id,
                "address": row.address,
                "part_entity_id": str(part.id),
                "model": row.model,
            }
        )
        detected["parts"][str(part.id)] = {
            "telemetry": [{"name": f"{name}.position", "unit": None}],
            "lifecycle": LifecycleState.LIVE.value,
        }
        if repo_part is not None:
            repo["parts"][str(part.id)] = {
                "telemetry": [
                    {"name": f"{name}.position", "unit": unit_for_mode(repo_part.calibration_mode)}
                ],
                "calibration": {
                    "mode": repo_part.calibration_mode.value
                    if repo_part.calibration_mode
                    else None,
                    "values": dict(repo_part.calibration or {}),
                    "source": repo_part.calibration_source,
                    "owner": "repo",
                },
            }
    layers = [
        ConfigLayer(by=FieldProvenance.DETECTED, document=detected),
        # The repo layer's source is the CONFIG id (class + calibration stem), which is what
        # binds this config to this device; each part's calibration keeps its file path.
        ConfigLayer(
            by=FieldProvenance.REPO,
            document=repo,
            source=chosen.config_id if chosen is not None else None,
        ),
    ]
    if chosen is not None and proposal.disambiguation is not None:
        layers.append(ConfigLayer(by=FieldProvenance.USER, document={"disambiguated_by": "user"}))
    config = merge_layers(robot.id, layers)
    if saved is not None:
        config = _merge_confirmation(saved, config)
    entry = await put_config(session, project_id, robot, config, created_by=created_by)
    return ConfirmResult(
        robot=robot,
        part_ids=part_ids,
        config=config,
        document=dict(entry.payload or {}),
        created_robot=created,
    )


__all__ = [
    "AcceptedRow",
    "ConfirmIn",
    "ConfirmResult",
    "DetectedDeviceOut",
    "ProposalOut",
    "ProposeIn",
    "bind_device",
    "bound_repo_config_ids",
    "confirm_proposal",
    "detected_devices_wire",
    "exclude_bound",
    "propose_via_local",
    "reconcile_device",
    "validated_repo_root",
]
