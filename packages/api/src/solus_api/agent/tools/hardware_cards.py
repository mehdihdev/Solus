"""SOLUSDEV-326 P2-T5 — SOL's hardware card tools: every write waits for the person's card.

Six gated tools over the hardware services, each as the requesting member through their bound
read scope (docs/api/hardware.md §1a and "SOL's hardware tools"). This module holds what they
share and the two that write from an inspection; the other four are in `hardware_graph_cards`:

- `hardware.add_parts` — an inspection's rows as parts of a new robot or an existing one, or (a
  board streaming lines) as ONE part on its own keyed by its device ref, its channels named from
  the evidence.
- `hardware.add_connection` — a device nothing was identified on, kept as a plain connection.
- `hardware.apply_evidence` — rows `read_evidence` proposed from an authorized firmware or host
  config file, added to the robot's topology.
- `hardware.link_part` — a part linked to design nodes: its CAD body or schematic component is the
  same physical part (`same_as`); a code site commands or reads it. A target that cannot be linked
  is named and left out; the rest are linked.
- `hardware.import_definition` — a library platform as a new robot, or a library part into one.
- `hardware.set_in_graph` — a robot or a lone part into the workspace graph or out of it, with
  what moves with it.

Each is gated statically (`requires_confirmation`, a complete preview), resumes SOL after any
decision on its card, and is never an owned routine: Build never runs one on its own. Hardware SOL
adds stays out of the graph, seen only by the member who added it, until set_in_graph adds it.

The card is an offer — these write the graph, never the hardware — built from the STORED
arguments alone: `stored_args` stamps beside the model's arguments what the card shows (`shown`,
read now as the member; add_parts and add_connection also the whole inspection, so approval never
listens to the device again; apply_evidence the rows its file said), and the preview re-reads it
and refuses once it no longer holds. The preview reads Solus's own state only, never the local
runner or a file: a decision goes stale only when what the card says stopped being true.
Approval runs the stored call; a write that publishes publishes one `graph.changed` after its
commit.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.cards import chip, fitted, single_line
from solus_api.agent.confirmations import _canonical, _complete_preview
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.hardware_onboarding import DeviceOffer, _HardwareRead, _tool_refusal
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.contracts.action_gate import Card, CardField
from solus_api.core.errors import APIError
from solus_api.graph.live import graph_changed_frame
from solus_api.graph.read_scope import IN_GRAPH, bind_scope
from solus_api.hardware.detect import (
    ConfirmIn,
    ConfirmResult,
    ProposalOut,
    ProposalRowOut,
    _chosen_repo_config,
    accepted_part_name,
    bound_repo_config_ids,
)
from solus_api.hardware.detection_service import add_inspected_board, confirm_inspected
from solus_api.hardware.device_memory import device_context
from solus_api.hardware.inspections import INSPECTIONS
from solus_api.hardware.store import robot_root
from solus_api.models import GraphEntity, Project, User, utcnow
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts

if TYPE_CHECKING:
    from solus_api.graph.live import LiveHub

logger = logging.getLogger("solus.agent.tools.hardware_cards")

ADD_PARTS: Final = "hardware.add_parts"
ADD_CONNECTION: Final = "hardware.add_connection"
APPLY_EVIDENCE: Final = "hardware.apply_evidence"
LINK_PART: Final = "hardware.link_part"
IMPORT_DEFINITION: Final = "hardware.import_definition"
SET_IN_GRAPH: Final = "hardware.set_in_graph"
HARDWARE_CARDS: Final = (
    ADD_PARTS,
    ADD_CONNECTION,
    APPLY_EVIDENCE,
    LINK_PART,
    IMPORT_DEFINITION,
    SET_IN_GRAPH,
)
#: Rows one card adds or links: every one is a row of its preview, and a card shows all it does.
MAX_CARD_ROWS: Final = 32
CHANGED: Final = (
    "What this card shows has changed since it was shown. Nothing was applied; ask again."
)
_ID: Final = {"type": "string", "pattern": "^[0-9a-fA-F-]{36}$"}
_NAME: Final = {"type": "string", "minLength": 1, "maxLength": 120}


def _target_schema(*kinds_: str) -> dict[str, Any]:
    """Where hardware goes: `existing` names a robot_id, any other kind a name (`_stored_target`
    holds the pairing, so the schema the model reads stays one object)."""
    return {
        "type": "object",
        "properties": {"kind": {"enum": list(kinds_)}, "name": _NAME, "robot_id": _ID},
        "required": ["kind"],
        "additionalProperties": False,
    }


_ONLY_YOU: Final = "Only you, in your hardware connections"
_YOUR_TEAM: Final = "Your team, in the workspace graph"
_KEPT_OUT: Final = (
    "It stays in your hardware connections, seen only by you, until you add it to the "
    "workspace graph."
)
_ON_ROBOT: Final = "Parts on a robot are seen by whoever sees the robot."


# --------------------------------------------------------------------------- shared words


def _line_row(label: object, after: object, before: object = None) -> dict[str, Any]:
    """One complete preview row: each text one printable line, capped."""

    def line(value: object) -> str | None:
        return None if value is None else single_line(value, 400) or "-"

    return {"label": single_line(label, 120) or "-", "before": line(before), "after": line(after)}


def _clipped(value: object) -> str:
    return single_line(value, 60)


def _counted(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _chips(names: Sequence[str], shown: int = 3) -> str:
    """Up to `shown` names, each one code chip, then how many more."""
    listed = ", ".join(chip(name, 40) for name in names[:shown])
    rest = len(names) - shown
    return f"{listed} and {rest} more" if rest > 0 else listed


def _offer(
    title: str,
    body: str,
    primary: str,
    receipt: str,
    *,
    more: str,
    field: CardField | None = None,
) -> Card:
    # Cut to the contract's bounds: a card that failed them would park its call with no card.
    return Card(
        **fitted(
            {
                "kind": "offer",
                "title": title,
                "body": body,
                "more": more,
                "field": field,
                "primary": primary,
                "secondary": "Not now",
                "receipt": single_line(receipt, 160),
            }
        )
    )


def _refusal_of(message: str, code: ToolErrorCode = ToolErrorCode.INVALID_ARGS) -> ToolException:
    return ToolException(message, code=code)


def _stored_name(value: object) -> str:
    """A name as the hardware writers store it: one line, each run of whitespace one space."""
    return " ".join(str(value).split())


def _uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise APIError(422, "validation_error", f"Not an id: {single_line(value, 40)}") from None


@dataclass(frozen=True)
class _Written:
    """What a write answers, and what follows its commit: the data events and one fan-out."""

    value: dict[str, Any]
    counts: GraphChangeCounts | None = None
    events: tuple[tuple[str, dict[str, Any]], ...] = ()


class _HardwareCard(_HardwareRead):
    """A hardware write behind an offer card, as the member (the module docstring)."""

    requires_complete_preview: ClassVar[bool] = True
    card_resumes: ClassVar[bool] = True
    #: The Solus sentence the person approves (`ToolDescriptor.consent_summary`).
    consent: ClassVar[str]
    #: What `stored_args` adds beside the model's arguments; never the model's to send.
    stamps: ClassVar[tuple[str, ...]] = ("shown",)

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        local: Any,
        hub: LiveHub,
    ) -> None:
        super().__init__(sessions, project_id, user_id, local)
        self.hub = hub
        self._descriptor = self._descriptor.model_copy(
            update={"requires_confirmation": True, "consent_summary": self.consent}
        )
        self.stored_params: dict[str, Any] = {
            **self.params,
            "properties": {**self.params["properties"], **{key: {} for key in self.stamps}},
            "required": [*self.params.get("required", []), *self.stamps],
        }

    async def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """What the card and the approval read: the model's arguments, normalized and checked
        (a refusal parks nothing), with `shown` read now as the member."""
        stamped = self.stamp(args)
        try:
            shown = await self._read(stamped)
        except APIError as exc:
            raise _tool_refusal(exc) from None
        return {**stamped, "shown": shown}

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """The card's rows from the stored arguments, once what they show still holds."""
        try:
            shown = await self._read(args)
        except APIError as exc:
            raise PreviewRefusal(f"{single_line(exc.message, 300)} Nothing was applied.") from None
        if shown != args.get("shown"):
            raise PreviewRefusal(CHANGED)
        rows = self.rows(args)
        if not _complete_preview(rows):
            raise PreviewRefusal("This change does not fit on one card. Nothing was parked.")
        return rows

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        """Only ever the approved card's stored call: the confirmation flow runs it."""
        if "shown" not in args:
            raise _refusal_of(
                "This runs only once the person approves its card.", ToolErrorCode.UNAUTHORIZED
            )
        with bind_scope(self.scope()):
            async with self.sessions() as session:
                try:
                    written = await self.write(session, args)
                except APIError as exc:
                    raise _tool_refusal(exc) from None
                await self._emit(session, written.events)
                await session.commit()
        if written.counts is not None:
            await self._publish(written.counts)
        return written.value

    async def _read(self, args: Mapping[str, Any]) -> dict[str, Any]:
        with bind_scope(self.scope()):
            async with self.sessions() as session:
                return await self.shown(session, args)

    async def _emit(
        self, session: AsyncSession, events: Sequence[tuple[str, dict[str, Any]]]
    ) -> None:
        if not events:
            return
        user = await session.get(User, self.user_id)
        project = await session.get(Project, self.project_id)
        if user is None or project is None:
            return
        for event_type, payload in events:
            emit_event(
                session,
                user=user,
                event_type=event_type,
                team_id=project.team_id,
                project_id=self.project_id,
                payload=payload,
            )

    async def _publish(self, counts: GraphChangeCounts) -> None:
        """After the commit, in its own guard: a failed fan-out never undoes the change."""
        frame = graph_changed_frame(
            project_id=self.project_id,
            source_id=None,
            sync_id=None,
            counts=counts,
            at=utcnow().isoformat(),
        )
        try:
            await self.hub.publish(self.project_id, frame)
        except Exception:  # noqa: BLE001 — the change is committed; fan-out never undoes it
            logger.exception("graph fan-out failed project=%s (the change stands)", self.project_id)

    # Each card tool fills these in.

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        """The model's arguments as stored, before `shown`: a refusal parks nothing."""
        return dict(args)

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        """What the card shows of Solus's state, read as the member (an APIError refuses)."""
        return {}

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def card(self, stored: dict[str, Any]) -> Card:
        raise NotImplementedError

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        raise NotImplementedError

    def _inspection(self, args: Mapping[str, Any]) -> ProposalOut:
        """The member's own inspection here, as `inspect_device` kept it."""
        found = INSPECTIONS.get(self.project_id, self.user_id, str(args["inspection_id"]))
        if found is None:
            raise _refusal_of(
                "No inspection of yours by that id here: inspect the device again "
                "(hardware.inspect_device).",
                ToolErrorCode.NOT_FOUND,
            )
        return found.proposal


# --------------------------------------------------------------------------- robots and devices


def _stored_target(target: Mapping[str, Any]) -> dict[str, Any]:
    """The target as stored: an existing robot by its robot_id alone; anything new by a name as
    the writer stores it."""
    if target["kind"] == "existing":
        if "robot_id" not in target or "name" in target:
            raise _refusal_of("An existing robot is named by its robot_id alone.")
        return {"kind": "existing", "robot_id": str(target["robot_id"])}
    name = _stored_name(target.get("name", ""))
    if not name or "robot_id" in target:
        raise _refusal_of("Give what is new a name, and no robot_id.")
    return {"kind": target["kind"], "name": name}


async def _robot_shown(
    session: AsyncSession, project_id: uuid.UUID, target: Mapping[str, Any]
) -> dict[str, Any] | None:
    """An existing robot as its card names it, read as the member (404 when not theirs)."""
    if target.get("kind") != "existing":
        return None
    robot = await robot_root(session, project_id, _uuid(target["robot_id"]))
    return {"name": robot.name, "in_graph": robot.attrs.get(IN_GRAPH) is not False}


def _robot_name(stored: Mapping[str, Any]) -> str:
    robot = stored["shown"]["robot"]
    return str(stored["target"]["name"] if robot is None else robot["name"])


def _robot_line(stored: Mapping[str, Any]) -> str:
    new = stored["target"]["kind"] == "new"
    return f"{_robot_name(stored)} (new)" if new else _robot_name(stored)


def _who_sees(stored: Mapping[str, Any]) -> str:
    robot = stored["shown"]["robot"]
    return _YOUR_TEAM if robot is not None and robot["in_graph"] else _ONLY_YOU


def _port_note(proposal: ProposalOut) -> str:
    if proposal.identity_basis != "port_position":
        return ""
    return " It has no serial number, so it is tied to this USB port."


def _robot_written(result: ConfirmResult, proposal: ProposalOut, repo_config: object) -> _Written:
    robot, parts = result.robot, len(result.part_ids)
    confirmed = {
        "robot_id": str(robot.id),
        "device_ref": proposal.device_ref,
        "parts": parts,
        "repo_config": repo_config,
    }
    return _Written(
        value={
            "robot_id": str(robot.id),
            "robot": robot.name,
            "created_robot": result.created_robot,
            "part_ids": [str(part) for part in result.part_ids],
            "in_graph": robot.attrs.get(IN_GRAPH) is not False,
        },
        counts=GraphChangeCounts(
            entities_created=parts + int(result.created_robot), relations_created=parts
        ),
        events=(("hardware.robot_confirmed", confirmed),),
    )


def _picked(row: Mapping[str, Any]) -> dict[str, Any]:
    name = _stored_name(row.get("name", ""))
    return {"row_id": str(row["row_id"]), **({"name": name} if name else {})}


def _check_parts(
    proposal: ProposalOut,
    target: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    repo_config_id: object,
) -> None:
    """What add_parts refuses before a card, saying what to do instead."""
    if proposal.identity is None or proposal.driver_id is None:
        raise _refusal_of(
            f"Nothing was identified on this device to add as parts; {ADD_CONNECTION} keeps it "
            "as a plain connection."
        )
    if target["kind"] == "none" and proposal.stream is None:
        raise _refusal_of(
            "Only a board that streams lines is added on its own; add these rows to a robot."
        )
    ids = [row["row_id"] for row in rows]
    unknown = set(ids) - {row.id for row in proposal.rows}
    if unknown or len(set(ids)) != len(ids) or not 1 <= len(ids) <= MAX_CARD_ROWS:
        raise _refusal_of(f"Name 1 to {MAX_CARD_ROWS} distinct rows of this inspection.")
    try:
        _chosen_repo_config(proposal, None if repo_config_id is None else str(repo_config_id))
    except APIError as exc:
        raise _refusal_of(exc.message) from None


def _named_rows(
    stored: Mapping[str, Any], proposal: ProposalOut
) -> list[tuple[ProposalRowOut, str]]:
    """Each picked row with the name its part gets — the writer's own rule
    (`accepted_part_name`): the person's, the proposal's, the chosen repo config's, else its
    address."""
    by_id = {row.id: row for row in proposal.rows}
    chosen = _chosen_repo_config(proposal, stored.get("repo_config_id"))
    repo = {part.address: part.name for part in chosen.parts} if chosen is not None else {}
    named: list[tuple[ProposalRowOut, str]] = []
    for pick in stored["rows"]:
        row = by_id[pick["row_id"]]
        name = accepted_part_name(
            _robot_name(stored),
            row.address,
            pick.get("name"),
            row.proposed_function,
            repo.get(row.address),
            streamed=proposal.stream is not None,
        )
        named.append((row, _stored_name(name)))
    return named


def _repo_config(stored: Mapping[str, Any], proposal: ProposalOut) -> tuple[str, str] | None:
    """The repo config this card's write binds to the device and takes part names and
    calibration from — the one named, or the only match — as (label, where it reads from)."""
    chosen = _chosen_repo_config(proposal, stored.get("repo_config_id"))
    if chosen is None:
        return None
    return single_line(chosen.label, 80), single_line(
        chosen.calibration_source or chosen.source, 200
    )


def _channels(stored: Mapping[str, Any], proposal: ProposalOut) -> list[str]:
    """A lone board's channel per picked column: the person's name, the evidence's (the stream's
    names, else the row's), else what the line driver calls an unnamed column."""
    names = (proposal.stream.channel_names if proposal.stream is not None else None) or []
    position = {row.id: (index, row) for index, row in enumerate(proposal.rows)}
    channels: list[str] = []
    for pick in stored["rows"]:
        index, row = position[pick["row_id"]]
        evidence = names[index] if index < len(names) else row.proposed_function
        channels.append(single_line(pick.get("name") or evidence or f"ch{row.address}.value", 128))
    return channels


class AddParts(DeviceOffer, _HardwareCard):
    name = ADD_PARTS
    description = (
        "Add what hardware.inspect_device found (inspection_id): its rows as parts of a new "
        "robot (target new + name) or an existing one (robot_id), or a board streaming lines as "
        "one part (target none + name; channels named from the evidence). rows picks and names "
        "rows (default all); repo_config_id answers the inspection's question. Stays out of the "
        "workspace graph until the person adds it. Parks a card."
    )
    params = {
        "type": "object",
        "properties": {
            "inspection_id": _ID,
            "target": _target_schema("new", "existing", "none"),
            "rows": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CARD_ROWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "row_id": {"type": "string", "minLength": 1, "maxLength": 600},
                        "name": _NAME,
                    },
                    "required": ["row_id"],
                    "additionalProperties": False,
                },
            },
            "repo_config_id": {"type": "string", "minLength": 1, "maxLength": 256},
        },
        "required": ["inspection_id", "target"],
        "additionalProperties": False,
    }
    consent = "Add the shown parts from the inspected device"
    stamps = ("shown", "proposal")

    def working(self, args: dict[str, Any]) -> str:
        return "Preparing the parts to add"

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        proposal = self._inspection(args)
        target = _stored_target(args["target"])
        picks = args.get("rows") or [{"row_id": row.id} for row in proposal.rows]
        rows = [_picked(row) for row in picks]
        _check_parts(proposal, target, rows, args.get("repo_config_id"))
        stored = {**args, "target": target, "rows": rows}
        return {**stored, "proposal": proposal.model_dump(mode="json")}

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        proposal = ProposalOut.model_validate(args["proposal"])
        offered = {match.config_id for match in proposal.repo_matches}
        if offered & await bound_repo_config_ids(session, self.project_id):
            raise APIError(
                409,
                "proposal_changed",
                "A repo config this device matched is now bound to other hardware; inspect "
                "the device again.",
            )
        return {"robot": await _robot_shown(session, self.project_id, args["target"])}

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        proposal = ProposalOut.model_validate(stored["proposal"])
        device = f"{proposal.device_ref}{_port_note(proposal)}"
        if stored["target"]["kind"] == "none":
            return [
                _line_row("Part", stored["target"]["name"]),
                _line_row("Device", device),
                _line_row("Channels", ", ".join(_channels(stored, proposal))),
                _line_row("Who sees it", _ONLY_YOU),
            ]
        config = _repo_config(stored, proposal)
        return [
            _line_row("Robot", _robot_line(stored)),
            _line_row("Device", device),
            *(
                _line_row(f"Part {name}", f"{row.model or 'device'} at {row.address}")
                for row, name in _named_rows(stored, proposal)
            ),
            *([_line_row("Repo config", f"{config[0]} ({config[1]})")] if config else []),
            _line_row("Who sees it", _who_sees(stored)),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        proposal = ProposalOut.model_validate(stored["proposal"])
        target, device = stored["target"], chip(proposal.device_ref, 140)
        if target["kind"] == "none":
            channels = _channels(stored, proposal)
            return _offer(
                "Add this board as a part",
                f"{device} streams {_counted(len(channels), 'channel')}: {_chips(channels)}."
                + _port_note(proposal),
                "Add",
                f"{_clipped(target['name'])} added",
                more=_KEPT_OUT,
                field=CardField(label="Part name", value=target["name"]),
            )
        names = [name for _, name in _named_rows(stored, proposal)]
        parts = _counted(len(names), "part")
        config = _repo_config(stored, proposal)
        calibrated = f" Calibration from repo config {chip(config[0], 40)}." if config else ""
        if target["kind"] == "new":
            return _offer(
                f"Add {parts} as a new robot",
                f"From {device}: {_chips(names)}.{calibrated}{_port_note(proposal)}",
                "Add",
                f"{_clipped(target['name'])}: {parts} added",
                more=_KEPT_OUT,
                field=CardField(label="Robot name", value=target["name"]),
            )
        robot = _robot_name(stored)
        return _offer(
            f"Add {parts} to your robot",
            # The config before the device and names: at their longest the bound cuts the tail,
            # and two calls that differ only in the config must show different cards.
            f"To {chip(robot, 60)}.{calibrated} From {device}: {_chips(names)}.",
            "Add",
            f"{_clipped(robot)}: {parts} added",
            more=_ON_ROBOT,
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        proposal = ProposalOut.model_validate(args["proposal"])
        if args["target"]["kind"] == "none":
            return await self._board(session, args, proposal)
        accepted = [
            {
                "row_id": pick["row_id"],
                **({"function_name": pick["name"]} if "name" in pick else {}),
            }
            for pick in args["rows"]
        ]
        body = ConfirmIn.model_validate(
            {
                "target": dict(args["target"]),
                "accepted": accepted,
                "repo_config_id": args.get("repo_config_id"),
                "start_session": False,
            }
        )
        result = await confirm_inspected(
            session,
            self.local,
            project_id=self.project_id,
            user_id=self.user_id,
            proposal=proposal,
            body=body,
            in_graph=False,
            onboarded_by=self.user_id,
        )
        return _robot_written(result, proposal, args.get("repo_config_id"))

    async def _board(
        self, session: AsyncSession, args: Mapping[str, Any], proposal: ProposalOut
    ) -> _Written:
        response, replayed = await add_inspected_board(
            session,
            self.local,
            project_id=self.project_id,
            user_id=self.user_id,
            proposal=proposal,
            name=str(args["target"]["name"]),
            channels=_channels(args, proposal),
            key=uuid.uuid5(self.project_id, f"{self.user_id}:{ADD_PARTS}:{_canonical(args)}"),
        )
        entity = response["entity"]
        value = {
            "part_id": str(entity["id"]),
            "part": entity["name"],
            "device_ref": proposal.device_ref,
            "in_graph": False,
        }
        if replayed:
            return _Written(value=value)
        created = {"entity_id": str(entity["id"]), "kind": "part", "parent_id": None}
        return _Written(
            value=value,
            counts=GraphChangeCounts(entities_created=1),
            events=(("hardware.entity_created", created),),
        )


class AddConnection(DeviceOffer, _HardwareCard):
    name = ADD_CONNECTION
    description = (
        "Keep a device hardware.inspect_device identified nothing on as a plain connection of a "
        "new robot (target new + name) or an existing one (robot_id). Parks a card."
    )
    params = {
        "type": "object",
        "properties": {"inspection_id": _ID, "target": _target_schema("new", "existing")},
        "required": ["inspection_id", "target"],
        "additionalProperties": False,
    }
    consent = "Keep the shown device as a plain connection"
    stamps = ("shown", "proposal")

    def working(self, args: dict[str, Any]) -> str:
        return "Preparing to keep the device as a connection"

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        proposal = self._inspection(args)
        heard = proposal.driver_id or proposal.rows or proposal.params or proposal.stream
        if heard or proposal.identity is None or proposal.identity.kind.value != "usb_serial":
            raise _refusal_of(
                "Only a USB serial device nothing was identified on is kept as a plain "
                f"connection; {ADD_PARTS} adds what was found."
            )
        target = _stored_target(args["target"])
        return {**args, "target": target, "proposal": proposal.model_dump(mode="json")}

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        await self._refuse_held(session, str(args["proposal"]["device_ref"]))
        return {"robot": await _robot_shown(session, self.project_id, args["target"])}

    async def _refuse_held(self, session: AsyncSession, device_ref: str) -> None:
        """409 when other hardware already holds the device: the write would re-bind it to that
        holder, not make the connection this card offers. A holder the member may see is named;
        one they may not is never (docs/api/hardware.md §1a)."""
        context = await device_context(session, self.project_id, [{"device_ref": device_ref}], None)
        holders = context.holders.get(device_ref, ())
        if not holders:
            return
        seen = next((held for held, attrs in holders if not self.scope().hides(attrs)), None)
        holder = await session.get(GraphEntity, seen) if seen is not None else None
        named = (
            "a teammate's hardware that isn't in the graph yet"
            if holder is None
            else single_line(holder.name, 120)
        )
        raise APIError(
            409,
            "conflict",
            f"This device is already connected to {named}. Nothing was added.",
        )

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        proposal = ProposalOut.model_validate(stored["proposal"])
        return [
            _line_row("Robot", _robot_line(stored)),
            _line_row("Connection", f"{proposal.device_ref}{_port_note(proposal)}"),
            _line_row("Who sees it", _who_sees(stored)),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        proposal = ProposalOut.model_validate(stored["proposal"])
        new = stored["target"]["kind"] == "new"
        robot = chip(_robot_name(stored), 60)
        return _offer(
            "Firmware and protocol are unknown",
            f"Keep {chip(proposal.device_ref, 140)} as a plain connection of "
            f"{'a new robot ' if new else ''}{robot}; its raw data shows as it streams."
            + _port_note(proposal),
            "Add as a connection",
            f"{_clipped(proposal.device_ref)} kept as a connection",
            more="Solus keeps only how to reach it; what it is can be named later.",
            field=CardField(label="Robot name", value=_robot_name(stored)) if new else None,
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        proposal = ProposalOut.model_validate(args["proposal"])
        body = ConfirmIn.model_validate(
            {
                "target": dict(args["target"]),
                "accepted": [],
                "connection_only": True,
                "start_session": False,
            }
        )
        result = await confirm_inspected(
            session,
            self.local,
            project_id=self.project_id,
            user_id=self.user_id,
            proposal=proposal,
            body=body,
            in_graph=False,
            onboarded_by=self.user_id,
        )
        return _robot_written(result, proposal, None)


def register_hardware_cards(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    local: Any,
    hub: LiveHub,
) -> None:
    """The six card tools, as `user_id` in `project_id`, publishing through the app's `hub`."""
    from solus_api.agent.tools.hardware_graph_cards import GRAPH_CARDS  # it imports this module

    for card in (AddParts, AddConnection, *GRAPH_CARDS):
        registry.register(card(sessions, project_id, user_id, local, hub))


__all__ = [
    "ADD_CONNECTION",
    "ADD_PARTS",
    "APPLY_EVIDENCE",
    "HARDWARE_CARDS",
    "IMPORT_DEFINITION",
    "LINK_PART",
    "SET_IN_GRAPH",
    "register_hardware_cards",
]
