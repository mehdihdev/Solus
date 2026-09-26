"""The link-suggestion engine (R5, docs/api/hardware.md §3; ADR-012 propose, never assert).

Given a new part or device observation and the existing robots, emit candidate links with
evidence and confidence through the fingerprint seam (`ModalityMatch`). Bus-enumerated
evidence is high, firmware-inferred medium, telemetry-shape low — the CTR-08 bands, load-
validated here as ceilings. Precision over recall: two plausible robots are two suggestions,
never a chosen winner; below the floor nothing is emitted; nothing auto-accepts.

`suggest_links` is pure. The persistence half keeps durable rows because the user decides
later (data events persist nothing without consent, and the action gate expires in 30 min).
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Sequence
from typing import Any, Final, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import FrozenModel
from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import Modality, ModalityMatch
from solus_api.hardware.config import BusMapEntry, HardwareConfig
from solus_api.models import HardwareSuggestion, SuggestionStatus, utcnow
from solus_api.services.solus_graph import lock_project

TIER_CEILING: Final[dict[Modality, float]] = {
    Modality.BUS_ENUMERATION: 0.92,
    Modality.FIRMWARE_SYMBOL: 0.55,
    Modality.TELEMETRY_CHANNEL: 0.30,
}
SUGGESTION_FLOOR: Final = 0.30
_SLOT_SCORE: Final = 0.80  # a free bus-map slot at this address awaiting this part

Rule = tuple[float, str]


class LinkTier(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PartObservation(FrozenModel):
    subject_ref: str = Field(min_length=1, max_length=512)
    subject_kind: Literal["device", "part"]
    device_ref: str | None = None
    address: str | None = None
    model: str | None = None
    driver_id: str | None = None
    evidence: list[ModalityMatch] = Field(default_factory=list)
    channel_names: list[str] = Field(default_factory=list)
    #: A whole-device observation: what the interrogation found at each address.
    bus_map: list[BusMapEntry] = Field(default_factory=list)


class RobotCandidate(FrozenModel):
    robot_entity_id: uuid.UUID
    name: str
    config: HardwareConfig


class LinkSuggestion(FrozenModel):
    subject_ref: str
    subject_kind: Literal["device", "part"]
    candidate_robot_id: uuid.UUID
    confidence: float = Field(ge=0, le=1)
    tier: LinkTier
    evidence: list[ModalityMatch]
    reason: str


def _tier(score: float) -> LinkTier:
    if score > TIER_CEILING[Modality.FIRMWARE_SYMBOL]:
        return LinkTier.HIGH
    if score > TIER_CEILING[Modality.TELEMETRY_CHANNEL]:
        return LinkTier.MEDIUM
    return LinkTier.LOW


def _channel_names(config: HardwareConfig) -> set[str]:
    return {channel.name for part in config.parts.values() for channel in part.telemetry}


def _rule_identity(observation: PartObservation, config: HardwareConfig) -> Rule | None:
    """Bus-enumerated on the robot's own bus identity — the strongest signal."""
    bus = [m for m in observation.evidence if m.modality is Modality.BUS_ENUMERATION]
    if not bus or observation.device_ref is None or config.identity is None:
        return None
    if config.identity.device_ref != observation.device_ref:
        return None
    score = min(TIER_CEILING[Modality.BUS_ENUMERATION], max(m.confidence for m in bus))
    return score, f"the device {observation.device_ref} is this robot's bus identity"


def _rule_slot(observation: PartObservation, config: HardwareConfig) -> Rule | None:
    """A free bus-map slot at this address (model unset or equal) awaits this part."""
    if observation.address is None:
        return None
    if not any(m.modality is Modality.BUS_ENUMERATION for m in observation.evidence):
        return None
    for entry in config.bus_map:
        if (
            entry.address == observation.address
            and entry.part_entity_id is None
            and (entry.model is None or entry.model == observation.model)
        ):
            return _SLOT_SCORE, f"a free bus-map slot at address {entry.address}"
    return None


def _model_key(model: str | None) -> str:
    return "".join(ch for ch in (model or "").lower() if ch.isalnum())


def _models_agree(left: str | None, right: str | None) -> bool:
    """Unknown on either side agrees; otherwise one normalised name must contain the other
    (a library part is named 'Vendor XY-100', the wire says 'XY100')."""
    a, b = _model_key(left), _model_key(right)
    return not a or not b or a in b or b in a


def _rule_bus_map(observation: PartObservation, config: HardwareConfig) -> Rule | None:
    """A whole device whose bus map equals an identity-less robot's — the library-imported
    platform and the same machine on the wire reconcile to one robot."""
    if observation.subject_kind != "device" or not observation.bus_map or config.identity:
        return None
    if not any(m.modality is Modality.BUS_ENUMERATION for m in observation.evidence):
        return None
    declared = {e.address: e.model for e in config.bus_map}
    observed = {e.address: e.model for e in observation.bus_map}
    if not declared or set(declared) != set(observed):
        return None
    if not all(_models_agree(declared[a], observed[a]) for a in observed):
        return None
    return (
        _SLOT_SCORE,
        f"this robot's bus map ({len(declared)} parts at addresses "
        f"{', '.join(sorted(declared, key=len))}) matches the device; nothing is bound to it yet",
    )


def _rule_firmware(observation: PartObservation, channels: set[str]) -> Rule | None:
    """A firmware symbol naming a channel this robot carries — medium at best."""
    best: Rule | None = None
    for match in observation.evidence:
        value = match.evidence.get("value")
        if (
            match.modality is not Modality.FIRMWARE_SYMBOL
            or not isinstance(value, str)
            or not value
        ):
            continue
        if any(name.lower().startswith(value.lower()) for name in channels):
            score = min(TIER_CEILING[Modality.FIRMWARE_SYMBOL], match.confidence)
            if best is None or score > best[0]:
                best = (score, f"firmware names {value!r}, a channel this robot carries")
    return best


def _rule_shape(observation: PartObservation, channels: set[str]) -> Rule | None:
    """Telemetry shape only constrains; a full overlap just reaches the floor."""
    if not observation.channel_names:
        return None
    wanted = set(observation.channel_names)
    overlap = len(wanted & channels) / len(wanted)
    if overlap == 0:
        return None
    score = TIER_CEILING[Modality.TELEMETRY_CHANNEL] * overlap
    return score, f"telemetry shape overlaps {overlap:.0%} of the channels"


def _score(observation: PartObservation, candidate: RobotCandidate) -> Rule | None:
    """The best single rule for this candidate (max, never a sum), or None."""
    channels = _channel_names(candidate.config)
    rules = [
        rule
        for rule in (
            _rule_identity(observation, candidate.config),
            _rule_slot(observation, candidate.config),
            _rule_bus_map(observation, candidate.config),
            _rule_firmware(observation, channels),
            _rule_shape(observation, channels),
        )
        if rule is not None
    ]
    return max(rules, key=lambda rule: rule[0]) if rules else None


def suggest_links(
    observation: PartObservation, candidates: Sequence[RobotCandidate]
) -> list[LinkSuggestion]:
    """Ranked suggestions (confidence desc, then robot id). Empty beats invented."""
    suggestions: list[LinkSuggestion] = []
    for candidate in candidates:
        scored = _score(observation, candidate)
        if scored is None or scored[0] < SUGGESTION_FLOOR:
            continue
        score, reason = scored
        suggestions.append(
            LinkSuggestion(
                subject_ref=observation.subject_ref,
                subject_kind=observation.subject_kind,
                candidate_robot_id=candidate.robot_entity_id,
                confidence=score,
                tier=_tier(score),
                evidence=list(observation.evidence),
                reason=reason,
            )
        )
    return sorted(suggestions, key=lambda s: (-s.confidence, str(s.candidate_robot_id)))


# ------------------------------------------------------------------ persistence


def _evidence_set(evidence: Sequence[dict[str, Any]]) -> frozenset[str]:
    """Compare facts independently of record ordering, duplicates and object-key order."""
    return frozenset(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in evidence)


async def persist_suggestions(
    session: AsyncSession, project_id: uuid.UUID, suggestions: Sequence[LinkSuggestion]
) -> list[HardwareSuggestion]:
    """Deduplicate pending proposals and retain declined evidence across rediscovery."""
    await lock_project(session, project_id)
    rows: list[HardwareSuggestion] = []
    for suggestion in suggestions:
        evidence = [m.model_dump(mode="json") for m in suggestion.evidence]
        existing = await session.scalars(
            select(HardwareSuggestion)
            .where(
                HardwareSuggestion.project_id == project_id,
                HardwareSuggestion.subject_kind == suggestion.subject_kind,
                HardwareSuggestion.subject_ref == suggestion.subject_ref,
                HardwareSuggestion.candidate_robot_id == suggestion.candidate_robot_id,
                HardwareSuggestion.status.in_(
                    [SuggestionStatus.PENDING, SuggestionStatus.REJECTED]
                ),
            )
            .execution_options(populate_existing=True)
        )
        canonical = _evidence_set(evidence)
        if any(
            row.status is SuggestionStatus.PENDING or _evidence_set(row.evidence) == canonical
            for row in existing
        ):
            continue
        row = HardwareSuggestion(
            project_id=project_id,
            subject_ref=suggestion.subject_ref,
            subject_kind=suggestion.subject_kind,
            candidate_robot_id=suggestion.candidate_robot_id,
            confidence=suggestion.confidence,
            tier=suggestion.tier.value,
            evidence=evidence,
            reason=suggestion.reason,
            status=SuggestionStatus.PENDING,
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return rows


async def list_suggestions(
    session: AsyncSession,
    project_id: uuid.UUID,
    status: SuggestionStatus | None = SuggestionStatus.PENDING,
) -> list[HardwareSuggestion]:
    stmt = select(HardwareSuggestion).where(HardwareSuggestion.project_id == project_id)
    if status is not None:
        stmt = stmt.where(HardwareSuggestion.status == status)
    stmt = stmt.order_by(HardwareSuggestion.created_at.desc(), HardwareSuggestion.id.desc())
    return list((await session.scalars(stmt)).all())


async def decide_suggestion(
    session: AsyncSession,
    project_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    accept: bool,
    user_id: uuid.UUID,
    reason: str | None = None,
) -> HardwareSuggestion:
    """Accept or reject one pending row. Accepting supersedes the pending siblings for the
    same subject — one subject links to one robot."""
    await lock_project(session, project_id)
    row = await session.scalar(
        select(HardwareSuggestion)
        .where(
            HardwareSuggestion.id == suggestion_id,
            HardwareSuggestion.project_id == project_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise APIError(404, "not_found", "Suggestion not found")
    if row.status is not SuggestionStatus.PENDING:
        raise APIError(409, "conflict", f"Suggestion already {row.status.value}")
    now = utcnow()
    row.status = SuggestionStatus.ACCEPTED if accept else SuggestionStatus.REJECTED
    row.decided_at = now
    row.decided_by = user_id
    if reason:
        row.reason = reason
    if accept:
        siblings = await session.scalars(
            select(HardwareSuggestion).where(
                HardwareSuggestion.project_id == project_id,
                HardwareSuggestion.subject_ref == row.subject_ref,
                HardwareSuggestion.subject_kind == row.subject_kind,
                HardwareSuggestion.status == SuggestionStatus.PENDING,
                HardwareSuggestion.id != row.id,
            )
        )
        for sibling in siblings:
            sibling.status = SuggestionStatus.SUPERSEDED
            sibling.decided_at = now
    await session.flush()
    return row


def serialize_suggestion(row: HardwareSuggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_ref": row.subject_ref,
        "subject_kind": row.subject_kind,
        "candidate_robot_id": row.candidate_robot_id,
        "confidence": row.confidence,
        "tier": row.tier,
        "evidence": row.evidence,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }
