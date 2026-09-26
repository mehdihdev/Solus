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
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import (
    PART_KIND,
    attach_part,
    ensure_config,
    put_config,
    robot_root,
)
from solus_api.models import (
    GraphEntity,
    HardwareSuggestion,
    SolusEntry,
    SolusEntryKind,
    SuggestionStatus,
)
from solus_api.services.physical_robots import ROBOT_CATEGORIES, PhysicalRobotService, RobotName
from solus_api.services.solus_graph import lock_project

Category = Literal[
    "sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring"
]

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
    category: Category = "actuators"


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
) -> ProposalOut:
    """Run the local runtime's interrogation off-loop and re-validate its proposal."""
    options: dict[str, Any] = {"repo_root": repo_root, "budget_s": budget_s}
    if repo_sources:
        options["repo_sources"] = repo_sources
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(local.propose_device, device_ref, **options),
            PROPOSE_TIMEOUT_S,
        )
    except ValueError as exc:
        raise APIError(
            422, "invalid_source", "The selected source could not be parsed. Review its contents."
        ) from exc
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
        raise APIError(
            409,
            "conflict",
            f"{owned.external_ref} is already part of robot {owned.attrs.get('robot_id')} — "
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
            or candidate.config.identity is not None
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
    # A robot already bound to THIS device is not a candidate — there is nothing to link.
    candidates = [
        c
        for c in await robot_candidates(session, project_id)
        if c.config.identity is None or c.config.identity.device_ref != proposal.device_ref
    ]
    retained, suggestions = await _retained_owner(session, project_id, proposal, candidates)
    if not retained:
        suggestions = suggest_links(observation, candidates)
    await persist_suggestions(session, project_id, suggestions)
    pending = await list_suggestions(session, project_id, status=SuggestionStatus.PENDING)
    return [row for row in pending if row.subject_ref == proposal.device_ref]


def _mark_live(document: dict[str, Any], answered: set[str]) -> None:
    """A bound part that answered at its bus-map address is live — by detection."""
    for entry in document["bus_map"]:
        part_id = entry.get("part_entity_id")
        if part_id in document["parts"] and entry["address"] in answered:
            document["parts"][part_id]["lifecycle"] = LifecycleState.LIVE.value
            document["provenance"][f"parts.{part_id}.lifecycle"] = {
                "by": FieldProvenance.DETECTED.value,
                "source": None,
            }


async def bind_device(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    proposal: ProposalOut,
    *,
    created_by: uuid.UUID,
) -> HardwareConfig:
    """Bind a detected device to an existing robot (an accepted suggestion): the wire's
    identity, driver and parameters enter the config as `detected`, the bus map keeps the
    robot's parts, and each part's external_ref becomes `<device ref>/<address>` so its
    telemetry resolves."""
    if proposal.identity is None or proposal.driver_id is None:
        raise APIError(422, "validation_error", "this device has no protocol to bind yet")
    _, config = await ensure_config(session, project_id, robot, created_by=created_by)
    if config.identity is not None and config.identity.device_ref != proposal.device_ref:
        raise APIError(
            409, "conflict", f"{robot.name} is already bound to {config.identity.device_ref}"
        )
    document = config.model_dump(mode="json")
    document["identity"] = proposal.identity.model_dump(mode="json")
    document["protocol"] = {"driver_id": proposal.driver_id, "params": dict(proposal.params)}
    by_address = {entry["address"]: entry for entry in document["bus_map"]}
    for row in proposal.rows:
        entry = by_address.get(row.address)
        if entry is None:
            document["bus_map"].append(
                {
                    "protocol": proposal.driver_id,
                    "address": row.address,
                    "part_entity_id": None,
                    "model": row.model,
                }
            )
        else:
            entry["protocol"] = proposal.driver_id
            entry["model"] = entry.get("model") or row.model
    for path in ("identity", "protocol", "bus_map"):
        document["provenance"] = {
            k: v for k, v in document["provenance"].items() if not k.startswith(path)
        }
        document["provenance"][path] = {"by": FieldProvenance.DETECTED.value, "source": None}
    _mark_live(document, {row.address for row in proposal.rows})
    bound = HardwareConfig.model_validate(document)
    await put_config(session, project_id, robot, bound, created_by=created_by)
    for entry in bound.bus_map:
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
    """Append reviewed new parts without replacing the owner's saved decisions."""
    _check_saved_connection(saved, additions)
    document = saved.model_dump(mode="json")
    provenance = {
        path: saved.provenance_of(path).model_dump(mode="json") for path in saved.leaf_paths()
    }
    incoming = additions.model_dump(mode="json")
    for field in ("identity", "protocol", "disambiguated_by"):
        if document[field] is None:
            document[field] = incoming[field]
            for path in additions.leaf_paths():
                if path == field or path.startswith(f"{field}."):
                    provenance[path] = additions.provenance_of(path).model_dump(mode="json")
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


def _check_saved_connection(saved: HardwareConfig, additions: HardwareConfig) -> None:
    """A review for adding parts cannot authorize replacing an existing connection."""
    if saved.identity is not None and additions.identity is not None:
        if saved.identity.identity_key() != additions.identity.identity_key():
            raise APIError(
                409, "proposal_changed", "Saved device identity differs; review configuration"
            )
    if saved.protocol is not None and saved.protocol != additions.protocol:
        raise APIError(409, "proposal_changed", "Saved protocol differs; review configuration")
    endpoints = {(row.protocol, row.address) for row in saved.bus_map}
    if any((row.protocol, row.address) in endpoints for row in additions.bus_map):
        raise APIError(
            409, "proposal_changed", "A proposed bus address already has a saved binding"
        )


def accepted_part_name(
    robot_name: str,
    address: str,
    category: str,
    accepted: str | None,
    proposed: str | None,
    repo: str | None,
) -> str:
    """Preserve evidence names; bus addresses make unnamed motor labels stable."""
    return (
        accepted
        or proposed
        or repo
        or (f"{robot_name}-Motor-{address}" if category == "actuators" else f"address {address}")
    )


async def _confirm_connection(
    session: AsyncSession,
    project_id: uuid.UUID,
    proposal: ProposalOut,
    body: ConfirmIn,
    created_by: uuid.UUID,
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
    owner = next(
        (
            c
            for c in candidates
            if c.config.identity is not None
            and c.config.identity.identity_key() == identity.identity_key()
        ),
        None,
    )
    if owner is not None:
        if body.target.kind == "existing" and body.target.robot_id != owner.robot_entity_id:
            raise APIError(
                409, "conflict", f"Connection already belongs to robot {owner.robot_entity_id}"
            )
        robot = await robot_root(session, project_id, owner.robot_entity_id)
        saved = owner.config
        created = False
    elif body.target.kind == "existing":
        robot = await robot_root(session, project_id, body.target.robot_id)
        saved = await resolve_runtime_config(session, project_id, robot.id)
        created = False
    else:
        robot = await PhysicalRobotService(session).create(project_id, body.target.name)
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
        if saved.identity is not None and (
            saved.identity.vid != identity.vid or saved.identity.pid != identity.pid
        ):
            raise APIError(
                409, "proposal_changed", "Saved USB identity differs; review configuration"
            )
        if saved.protocol is not None or saved.bus_map or saved.parts:
            raise APIError(
                409, "conflict", "Connection-only acceptance cannot replace configured hardware"
            )
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
) -> ConfirmResult:
    """Graph + config writes for a confirmation. Flushes; the caller owns the commit."""
    if body.connection_only:
        return await _confirm_connection(session, project_id, proposal, body, created_by)
    if proposal.identity is None or proposal.driver_id is None:
        raise APIError(422, "validation_error", "this device has no protocol to confirm yet")
    rows = {row.id: row for row in proposal.rows}
    unknown = [a.row_id for a in body.accepted if a.row_id not in rows]
    if unknown:
        raise APIError(422, "validation_error", f"unknown proposal rows: {', '.join(unknown[:5])}")
    await _already_confirmed(session, project_id, [a.row_id for a in body.accepted])
    chosen = _chosen_repo_config(proposal, body.repo_config_id)
    repo_parts = {p.address: p for p in chosen.parts} if chosen is not None else {}

    saved: HardwareConfig | None = None
    if body.target.kind == "new":
        robot = await PhysicalRobotService(session).create(project_id, body.target.name)
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
            accepted.category,
            accepted.function_name,
            row.proposed_function,
            repo_part.name if repo_part else None,
        )
        part = await attach_part(
            session,
            project_id,
            robot,
            name=name,
            category=accepted.category,
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
    "ROBOT_CATEGORIES",
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
