"""SOLUSDEV-322 P5-T1 — `sim.map_to_parts`: a simulated joint becomes an alias of ONE graph part.

A simulated stream names its joints by the simulator's own ids (`<world>/<model>/<joint>`,
`<scene>/<joint>`); the graph names a part. This tool records which part each simulated channel
stands for, so a sim session resolves to the same entity a real session does (P5-T2 reads the
alias). It is a static card: `requires_confirmation=True` and a complete preview — the person
sees every proposed `part → provider/device_id` row and every joint that stays unmapped, with
the candidates named. The gate re-previews at decision time and refuses a diverged card, so the
handler recomputes the same deterministic match and writes only what the card showed.

Matching, per channel, first rung that yields candidates:

1. the bound `simulation_model`'s joint binding whose `name` is the joint (one entity, exact);
2. a live part whose normalized name is the joint, or whose hardware config carries a telemetry
   channel `<joint>.<signal>`; the two pools are unioned;
3. the generated models' `joint` entities (SOLUSDEV-322 P6-T2, `simulation/model_job.py`): one
   whose name is the joint maps the part it moves — its `actuator_part_id` when the bus map stated
   one, else the mate's `child_part_id`; scoped to the robot when one is given.

Exactly one candidate maps; none or several stay unmapped and are named on the card. The write
is `part.attrs["sim_aliases"] = existing + [{provider, device_id}]`, deduped, REASSIGNED (never
mutated in place), under `lock_project`; `external_ref` is never touched. A data event
`sim.aliases_mapped` is emitted through `services/events.emit_event` (consent-gated there).
`provider` is a string: this module names no simulator.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.confirmations import _complete_preview
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.isaac_models import EntityId, SimulationModel
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.read_scope import current_scope
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.store import PART_KINDS, config_of, configuration_entries, robot_root
from solus_api.models import Domain, GraphEntity, Project, User
from solus_api.services.events import emit_event
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.sessions_ledger import SessionsLedger

logger = logging.getLogger("solus.agent.tools.sim_mapping")

NAME: Final = "sim.map_to_parts"
EVENT: Final = "sim.aliases_mapped"
ALIASES: Final = "sim_aliases"
MAX_CHANNELS: Final = 64
#: A provider is one lowercase word (`gazebo`, `mujoco`, `isaac`): the ledger's discriminator.
PROVIDER: Final = r"^[a-z][a-z0-9_]{0,31}$"
#: A joint name as a model binding spells it (`isaac_models.Binding.name`).
JOINT: Final = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
#: A device id as a sim source emits it: path-like, never an argv option, no text-format or
#: protobuf metacharacters, no whitespace.
DEVICE: Final = r"^[A-Za-z0-9_][A-Za-z0-9_./:-]{0,255}$"
SESSION: Final = r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$"
_LABEL_CAP: Final = 200
_NO_MATCH: Final = "no part matches"
_NOTHING: Final = "no joint matched a part; nothing to map"


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class JointChannel(_ClosedModel):
    device_id: Annotated[str, Field(pattern=DEVICE)]
    joint_name: Annotated[str, Field(pattern=JOINT)]


class MapToPartsArgs(_ClosedModel):
    provider: Annotated[str, Field(pattern=PROVIDER)]
    session_id: Annotated[str, Field(pattern=SESSION)] | None = None
    model_entity_id: EntityId | None = None
    channels: Annotated[list[JointChannel], Field(min_length=1, max_length=MAX_CHANNELS)]
    robot_id: EntityId | None = None

    @model_validator(mode="after")
    def distinct(self) -> Self:
        joints = {channel.joint_name for channel in self.channels}
        devices = {channel.device_id for channel in self.channels}
        if len(joints) != len(self.channels) or len(devices) != len(self.channels):
            raise ValueError("each joint and each device id appears once")
        return self


@dataclass(frozen=True)
class JointMatch:
    channel: JointChannel
    part: GraphEntity | None
    candidates: tuple[str, ...]

    @property
    def reason(self) -> str:
        return "ambiguous: " + ", ".join(self.candidates) if self.candidates else _NO_MATCH


def _mapping_refusal(message: str, code: ToolErrorCode) -> ToolException:
    return ToolException(message, code=code, retryable=False)


def _parse_map_args(args: dict[str, Any]) -> MapToPartsArgs:
    try:
        return MapToPartsArgs.model_validate(args)
    except ValidationError:
        raise _mapping_refusal(
            "Invalid mapping arguments: provider, up to 64 distinct {device_id, joint_name} "
            "channels, optional session_id, model_entity_id and robot_id.",
            ToolErrorCode.INVALID_ARGS,
        ) from None


def _normalized_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _card_label(text: str) -> str:
    return " ".join(text.split())[:_LABEL_CAP]


def _aliases_of(part: GraphEntity) -> list[dict[str, Any]]:
    rows = part.attrs.get(ALIASES) if isinstance(part.attrs, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _current_device(part: GraphEntity, provider: str) -> str | None:
    devices = [
        str(row["device_id"]) for row in _aliases_of(part) if row.get("provider") == provider
    ]
    return f"{provider}/" + ", ".join(devices) if devices else None


def _card_row(match: JointMatch, provider: str) -> dict[str, Any]:
    if match.part is None:
        label = _card_label(f"unmapped: {match.channel.joint_name} ({match.reason})")
        return {"label": label, "before": None, "after": None}
    return {
        "label": _card_label(match.part.name),
        "before": _current_device(match.part, provider),
        "after": f"{provider}/{match.channel.device_id}",
    }


class SimMappingTool:
    """`sim.map_to_parts`, bound to one project and person (the module docstring)."""

    requires_complete_preview = True

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        ledger: SessionsLedger | None = None,
    ) -> None:
        self.sessions, self.project_id, self.user_id = sessions, project_id, user_id
        self.ledger = ledger or SessionsLedger(sessions)
        self._descriptor = ToolDescriptor(
            name=NAME,
            description=(
                "Record which graph part each simulated joint stands for, so a simulated stream "
                "resolves to the same part as the real robot. Give the provider, the channels "
                "{device_id, joint_name} the session emits and, when known, the simulation model "
                "or robot to match within. One candidate maps; several or none stay unmapped and "
                "are named. The person approves the mapping first."
            ),
            params=MapToPartsArgs.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary="Record the shown simulated joints as aliases of the shown parts",
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = _parse_map_args(args)
        async with self.sessions() as session:
            matches = await self._match(session, parsed)
        if all(match.part is None for match in matches):
            raise PreviewRefusal(f"{_NOTHING}. Nothing was parked.")
        ordered = sorted(matches, key=lambda match: match.part is None)  # mapped rows first
        rows = [_card_row(match, parsed.provider) for match in ordered]
        if not _complete_preview(rows):
            raise PreviewRefusal(
                "The mapping cannot be shown whole on its card. Nothing was parked."
            )
        return rows

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        """Only ever after the person approved the card (the confirmation flow runs it)."""
        parsed = _parse_map_args(args)
        async with self.sessions() as session:
            await lock_project(session, self.project_id)
            matches = await self._match(session, parsed)
            mapped = [(m.part, m.channel) for m in matches if m.part is not None]
            if not mapped:
                raise _mapping_refusal(f"{_NOTHING}.", ToolErrorCode.INVALID_ARGS)
            for part, channel in mapped:
                alias = {"provider": parsed.provider, "device_id": channel.device_id}
                existing = _aliases_of(part)
                if alias not in existing:
                    part.attrs = {**part.attrs, ALIASES: [*existing, alias]}
                    part.version += 1
            await self._emit_mapped(session, parsed.provider, matches)
            await session.commit()
        return {
            "provider": parsed.provider,
            "mapped": [
                {"part_id": str(part.id), "part": part.name, "device_id": channel.device_id}
                for part, channel in mapped
            ],
            "unmapped": [
                {"joint_name": match.channel.joint_name, "reason": match.reason}
                for match in matches
                if match.part is None
            ],
        }

    async def _emit_mapped(
        self, session: AsyncSession, provider: str, matches: Sequence[JointMatch]
    ) -> None:
        user = await session.get(User, self.user_id)
        project = await session.get(Project, self.project_id)
        if user is None or project is None:
            return
        part_ids = [str(match.part.id) for match in matches if match.part is not None]
        emit_event(
            session,
            user=user,
            event_type=EVENT,
            team_id=project.team_id,
            project_id=self.project_id,
            payload={
                "provider": provider,
                "mapped": len(part_ids),
                "unmapped": len(matches) - len(part_ids),
                "part_ids": part_ids,
            },
        )

    # ------------------------------------------------------------------------------ matching

    async def _match(self, session: AsyncSession, parsed: MapToPartsArgs) -> list[JointMatch]:
        await self._check_session(parsed)
        bound = await self._model_joints(session, parsed.model_entity_id)
        parts = await self._candidate_parts(session, parsed.robot_id)
        prefixes = await self._telemetry_prefixes(session, parts)
        generated = await self._generated_joint_parts(session, parsed.robot_id)
        matches = []
        for channel in parsed.channels:
            joint = channel.joint_name
            wanted = _normalized_name(joint)
            candidates = (
                [bound[joint]]
                if joint in bound
                else [
                    part
                    for part in parts
                    if _normalized_name(part.name) == wanted or wanted in prefixes.get(part.id, ())
                ]
                or generated.get(joint, [])
            )
            part = candidates[0] if len(candidates) == 1 else None
            names = tuple(sorted(_card_label(p.name) for p in candidates)) if part is None else ()
            matches.append(JointMatch(channel, part, names))
        return matches

    async def _check_session(self, parsed: MapToPartsArgs) -> None:
        if parsed.session_id is None:
            return
        running = await self.ledger.running(project_id=self.project_id, provider=parsed.provider)
        if all(record.session_id != parsed.session_id for record in running):
            raise _mapping_refusal(
                f"No live {parsed.provider} session {parsed.session_id} in this project.",
                ToolErrorCode.NOT_FOUND,
            )

    def _live_entities(self) -> tuple[Any, ...]:
        return (
            GraphEntity.project_id == self.project_id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.domain != Domain.WORKSPACE,
            current_scope(self.project_id).entity_predicate(),
        )

    async def _model_joints(
        self, session: AsyncSession, model_text: str | None
    ) -> dict[str, GraphEntity]:
        """Joint binding name → the bound entity, every one live in THIS project."""
        if model_text is None:
            return {}
        model_id = uuid.UUID(model_text)
        root = await session.scalar(
            select(GraphEntity).where(GraphEntity.id == model_id, *self._live_entities())
        )
        definition = root.attrs.get("simulation_model") if root is not None else None
        if not isinstance(definition, dict):
            raise _mapping_refusal("The simulation model is unavailable.", ToolErrorCode.NOT_FOUND)
        try:
            model = SimulationModel.model_validate(definition)
        except ValidationError:
            raise _mapping_refusal(
                "The graph simulation model is invalid or unsupported.", ToolErrorCode.INVALID_ARGS
            ) from None
        ids = [uuid.UUID(joint.entity_id) for joint in model.joints]
        rows = {
            row.id: row
            for row in await session.scalars(
                select(GraphEntity).where(GraphEntity.id.in_(ids), *self._live_entities())
            )
        }
        if set(rows) != set(ids):
            raise _mapping_refusal(
                "A simulation binding is unavailable in this project.", ToolErrorCode.NOT_FOUND
            )
        return {joint.name: rows[uuid.UUID(joint.entity_id)] for joint in model.joints}

    async def _generated_joint_parts(
        self, session: AsyncSession, robot_id: str | None
    ) -> dict[str, list[GraphEntity]]:
        """Rung 3: generated joint name → the live part(s) it moves (actuator, else child)."""
        stmt = select(GraphEntity).where(
            GraphEntity.kind == kinds.JOINT, GraphEntity.origin == "system", *self._live_entities()
        )
        if robot_id is not None:
            stmt = stmt.where(GraphEntity.attrs["robot_id"].as_string() == robot_id)
        joints = list(await session.scalars(stmt.order_by(GraphEntity.name, GraphEntity.id)))
        wanted: dict[str, set[uuid.UUID]] = {}
        for joint in joints:
            moved = joint.attrs.get("actuator_part_id") or joint.attrs.get("child_part_id")
            if isinstance(moved, str):
                wanted.setdefault(joint.name, set()).add(uuid.UUID(moved))
        ids = {part for group in wanted.values() for part in group}
        rows = {
            row.id: row
            for row in await session.scalars(
                select(GraphEntity).where(GraphEntity.id.in_(ids), *self._live_entities())
            )
        }
        return {
            name: sorted((rows[i] for i in group if i in rows), key=lambda p: (p.name, p.id))
            for name, group in wanted.items()
        }

    async def _candidate_parts(
        self, session: AsyncSession, robot_id: str | None
    ) -> list[GraphEntity]:
        stmt = select(GraphEntity).where(GraphEntity.kind.in_(PART_KINDS), *self._live_entities())
        if robot_id is not None:
            try:
                await robot_root(session, self.project_id, uuid.UUID(robot_id))
            except APIError as exc:
                raise _mapping_refusal(exc.message, ToolErrorCode.NOT_FOUND) from None
            stmt = stmt.where(GraphEntity.attrs["robot_id"].astext == robot_id)
        return list(await session.scalars(stmt.order_by(GraphEntity.name, GraphEntity.id)))

    async def _telemetry_prefixes(
        self, session: AsyncSession, parts: Iterable[GraphEntity]
    ) -> Mapping[uuid.UUID, frozenset[str]]:
        """Part id → the `<joint>` prefixes of its configured telemetry channels."""
        try:
            entries = await configuration_entries(session, self.project_id, [p.id for p in parts])
        except APIError:
            logger.warning(
                "hardware config unreadable project=%s: no telemetry matching", self.project_id
            )
            return {}
        prefixes: dict[uuid.UUID, frozenset[str]] = {}
        for entry in entries:
            config = config_of(entry)
            if isinstance(config, EntityHardwareConfig) and config.component is not None:
                prefixes[config.entity_id] = frozenset(
                    _normalized_name(channel.name.split(".", 1)[0])
                    for channel in config.component.telemetry
                )
        return prefixes


def register_sim_mapping(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    ledger: SessionsLedger | None = None,
) -> None:
    registry.register(SimMappingTool(sessions, project_id, user_id=user_id, ledger=ledger))
