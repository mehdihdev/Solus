"""SOLUSDEV-326 P2-T4 — SOL's hardware reads, each as the requesting member.

Six tools over the existing hardware services; none is gated:

- `hardware.list_devices` — what is plugged into this computer now (no port is opened) and, for
  the machine's owner, what was here and left; each with what the caller may know of it: what
  binds it, their "Not now", their latest inspection (`hardware/device_memory.annotate`).
- `hardware.inspect_device` — listen to and ping one device (`hardware/inspections.py`). Free on a
  board just plugged in or a port already open; when opening the port would restart a running
  board, its per-call hook (`agent/dynamic_gate.py`) parks an approval card first. Answers an
  `inspection_id` and a compact summary, never the whole proposal.
- `hardware.expected_parts` — what the workspace says should exist: the planned bus-map rows of
  robots the caller may see, MCU symbols in schematics, sensor topics in ROS code and the
  libraries sketches include.
- `hardware.list_parts` — the robots and parts the caller may see, and whether each is in the
  graph.
- `hardware.read_evidence` — what one source proposes, read-only: an authorized firmware or host
  config file (by its opaque reference), or a CAD part's matched identity link.
- `hardware.search_library` — Solus's part and platform definitions.

Registered only for a person on a local API (`runtime.build_sol_registry(hardware_local=)`, the
device watcher's own condition): a hosted API has none, and the prompt says so. Every read goes
through the member's own read scope (docs/api/hardware.md §1a): hardware a teammate keeps out of
the graph never appears. Each says what it is doing (`working`): Solus's own words, which carry a
model value only as its schema admits it and inside one chip. Every answer fits the prompt's result
cap — rows left out are counted, never cut mid-way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from solus_api.agent.cards import chip, single_line
from solus_api.agent.prompt import TOOL_RESULT_CAP
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.contracts.action_gate import Card
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.read_scope import IN_GRAPH, GraphReadScope, current_scope, owns_machine
from solus_api.hardware.config import DEVICE_REF_PATTERN
from solus_api.hardware.expected_parts import MAX_ROWS, expected_parts
from solus_api.hardware.inspections import (
    INSPECTION_FRESH_S,
    INSPECTIONS,
    Inspection,
    inspect_device,
)
from solus_api.models import GraphEntity

if TYPE_CHECKING:
    from solus_api.graph.live import LiveHub

logger = logging.getLogger("solus.agent.tools.hardware_onboarding")

LIST_DEVICES: Final = "hardware.list_devices"
INSPECT_DEVICE: Final = "hardware.inspect_device"
EXPECTED_PARTS: Final = "hardware.expected_parts"
LIST_PARTS: Final = "hardware.list_parts"
READ_EVIDENCE: Final = "hardware.read_evidence"
SEARCH_LIBRARY: Final = "hardware.search_library"
HARDWARE_READS: Final = (
    LIST_DEVICES,
    INSPECT_DEVICE,
    EXPECTED_PARTS,
    LIST_PARTS,
    READ_EVIDENCE,
    SEARCH_LIBRARY,
)
#: Above the proposal's own 30 s wait, so its "did not answer in time" reaches the model.
INSPECT_TIMEOUT_S: Final = 45.0
#: What one answer may encode to, leaving the prompt's result envelope its room.
RESULT_BUDGET: Final = TOOL_RESULT_CAP - 400
_TEXT: Final = 80
_SUMMARY_TEXT: Final = 300
_UUID: Final = {"type": "string", "format": "uuid"}
_DEVICE_REF: Final = {"type": "string", "pattern": DEVICE_REF_PATTERN, "maxLength": 160}
_NOTHING: Final = {"type": "object", "properties": {}, "additionalProperties": False}
#: A refusal's status → what the model is told it was. 409 is busy, or changed underneath.
_CODES: Final = {
    403: ToolErrorCode.UNAUTHORIZED,
    404: ToolErrorCode.NOT_FOUND,
    409: ToolErrorCode.UNAVAILABLE,
    503: ToolErrorCode.UNAVAILABLE,
}
#: `read_evidence`'s sources in Solus's own words: its working line never carries the model's.
_EVIDENCE_WORDS: Final = {"firmware": "firmware", "host_config": "host config", "cad": "CAD"}


def _tool_refusal(exc: APIError) -> ToolException:
    """A service's refusal as the model reads it: its arguments only when the service says the
    request was invalid. A file the runner could not parse is no device_ref the model can fix."""
    if exc.code == "validation_error":
        return ToolException(exc.message, code=ToolErrorCode.INVALID_ARGS)
    return ToolException(exc.message, code=_CODES.get(exc.status_code, ToolErrorCode.TOOL_ERROR))


def _capped_line(value: object, cap: int = _TEXT) -> str | None:
    """Device- or repo-supplied text as one printable line, capped; None stays None."""
    return None if value is None else single_line(value, cap)


def _encoded_length(value: dict[str, Any]) -> int:
    """At least what `prompt.contain_result` encodes `value` to: ASCII-escaped, `<` escaped."""
    return len(json.dumps(value, ensure_ascii=True, default=str).replace("<", "\\u003c"))


def _fitted(value: dict[str, Any], key: str) -> dict[str, Any]:
    """`value` with its `key` rows halved until it encodes within `RESULT_BUDGET`; how many were
    left out is `more`."""
    rows = list(value[key])
    total = len(rows)
    while rows and _encoded_length({**value, key: rows}) > RESULT_BUDGET:
        rows = rows[: len(rows) // 2]
    return {**value, key: rows, "more": total - len(rows)}


class _HardwareRead:
    """One read, bound to a project, the member asking and this API's local runner."""

    name: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[dict[str, Any]] = _NOTHING
    timeout: ClassVar[float | None] = None

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        local: Any,
    ) -> None:
        self.sessions, self.project_id, self.user_id, self.local = (
            sessions,
            project_id,
            user_id,
            local,
        )
        self._descriptor = ToolDescriptor(
            name=self.name,
            description=self.description,
            params=self.params,
            returns={"type": "object"},
            timeout_seconds=self.timeout,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def scope(self) -> GraphReadScope:
        """The turn's bound view (its source branches), always as this member."""
        bound = current_scope(self.project_id)
        return bound if bound.viewer_id == self.user_id else replace(bound, viewer_id=self.user_id)

    def visible(self) -> tuple[ColumnElement[bool], ...]:
        return (self.scope().entity_predicate(), GraphEntity.deleted_at.is_(None))


class DeviceOffer:
    """A card about one device. Declining it is the person's "Not now" to that device: the
    decide route reads `declined_device` off the tool (duck-typed, like `needs_confirmation`)
    and dismisses what it names — a pure read of the STORED arguments, nothing more."""

    def declined_device(self, stored: Mapping[str, Any]) -> str | None:
        proposal = stored.get("proposal")
        ref = stored.get("device_ref") or (
            proposal.get("device_ref") if isinstance(proposal, Mapping) else None
        )
        well_formed = (
            isinstance(ref, str) and len(ref) <= 160 and re.fullmatch(DEVICE_REF_PATTERN, ref)
        )
        return ref if well_formed else None


# --------------------------------------------------------------------------- list_devices


def _device_state(device: Mapping[str, Any]) -> str:
    if device.get("device_ref") is None:
        return "unidentified"
    if device.get("bound_to"):
        return "bound"
    return "dismissed" if device.get("dismissed") else "new"


class ListDevices(_HardwareRead):
    name = LIST_DEVICES
    description = (
        "What is plugged into this computer now, at the level actually known (no port is "
        "opened): each device's state — new, bound (to the robot or part in bound_to), "
        "dismissed (the person said Not now) or, on their own machine, gone with when it was "
        "last seen — and the id of the person's latest inspection of it."
    )

    def working(self, args: dict[str, Any]) -> str:
        return "Looking at what is plugged into this computer"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        from solus_api.hardware.detect import detected_devices_wire
        from solus_api.hardware.device_memory import annotate, device_context, this_machine
        from solus_api.hardware.host_topology import LocalHostProvider

        devices = detected_devices_wire(await asyncio.to_thread(self.local.detect_devices))
        host = await LocalHostProvider(self.local).identity()
        async with self.sessions() as session:
            machine = await this_machine(session, self.project_id, host)
            context = await device_context(session, self.project_id, devices, machine)
        rows = [self._row(device) for device in annotate(devices, context, self.user_id)]
        present = {row["device_ref"] for row in rows}
        rows += [row for row in self._gone(context.machine) if row["device_ref"] not in present]
        return _fitted({"devices": rows}, "devices")

    def _row(self, device: Mapping[str, Any]) -> dict[str, Any]:
        ref = device.get("device_ref")
        inspection = INSPECTIONS.latest(self.project_id, self.user_id, ref) if ref else None
        return {
            "device_ref": ref,
            "headline": device.get("headline"),
            "level": device.get("level"),
            "identity_basis": device.get("identity_basis"),
            "state": _device_state(device),
            "bound_to": device.get("bound_to"),
            "last_seen": device.get("last_seen"),
            "inspection_id": inspection.id if inspection is not None else None,
        }

    def _gone(self, machine: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        """What this machine remembers and is not plugged in now: its owner's alone."""
        if machine is None or not owns_machine(machine, self.user_id):
            return []
        return [
            {
                "device_ref": row["device_ref"],
                "headline": row.get("headline"),
                "level": None,
                "identity_basis": row.get("identity_basis"),
                "state": "gone",
                "bound_to": None,
                "last_seen": row.get("last_seen"),
                "inspection_id": None,
            }
            for row in machine.get("devices") or []
            if isinstance(row, Mapping) and row.get("present") is False
        ]


# --------------------------------------------------------------------------- inspect_device


def _stream_shape(inspection: Inspection) -> dict[str, Any] | None:
    stream = inspection.proposal.stream
    if stream is None:
        return None
    return {
        "framing": stream.framing,
        "channels": stream.channel_count,
        "hz": round(stream.update_hz, 1),
        "names": [_capped_line(name) for name in (stream.channel_names or [])[:16]] or None,
    }


def _inspection_summary(inspection: Inspection) -> dict[str, Any]:
    """What the model reads of an inspection: bounded, its row ids kept for a card to name."""
    proposal = inspection.proposal
    question = proposal.disambiguation.question if proposal.disambiguation else None
    return _fitted(
        {
            "inspection_id": inspection.id,
            "device_ref": proposal.device_ref,
            "headline": proposal.headline,
            "level": proposal.level,
            "tone": proposal.tone,
            "summary": _capped_line(proposal.summary, _SUMMARY_TEXT),
            "driver_id": proposal.driver_id,
            "identity_basis": proposal.identity_basis,
            "stream": _stream_shape(inspection),
            "repo_matches": [
                {"config_id": _capped_line(match.config_id), "label": _capped_line(match.label)}
                for match in proposal.repo_matches[:4]
            ],
            "question": _capped_line(question, _SUMMARY_TEXT),
            "port_repair": _capped_line(proposal.port_repair.note)
            if proposal.port_repair
            else None,
            "rows": [
                {
                    "id": row.id,
                    "address": row.address,
                    "model": _capped_line(row.model),
                    "function": _capped_line(row.proposed_function),
                    "from": row.provenance,
                }
                for row in proposal.rows
            ],
        },
        "rows",
    )


class InspectDevice(DeviceOffer, _HardwareRead):
    name = INSPECT_DEVICE
    description = (
        "Listen to one device from hardware.list_devices and ping it, with the person's "
        "authorized repo files as evidence: what it is, its rows (address, model, function), the "
        "repo configs that match and a question when several do, and an inspection_id a later "
        "card names. Listening is free on a board just plugged in or a port already open; when "
        "it would restart a running board the person approves that first. A busy device is said "
        "busy, never silence. The first call after a plug-in answers what Solus heard then "
        "(heard_s_ago); call again to listen now."
    )
    params = {
        "type": "object",
        "properties": {"device_ref": _DEVICE_REF},
        "required": ["device_ref"],
        "additionalProperties": False,
    }
    timeout = INSPECT_TIMEOUT_S
    #: SOL continues after the person decides the restart card (its result, or "Not now").
    card_resumes = True
    #: A PARKED call's arguments: the model's, plus Solus's own mark that the person was asked.
    #: The model schema admits no other key, so a model can never send it.
    stored_params: ClassVar[dict[str, Any]] = {
        **params,
        "properties": {**params["properties"], "restart_approved": {"const": True}},
        "required": ["device_ref", "restart_approved"],
    }

    def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Runs only for a call that parks: the restart card is what this call's approval is."""
        return {**args, "restart_approved": True}

    def _fresh(self, args: dict[str, Any], *, take: bool = False) -> Inspection | None:
        """What the device's plug-in heard for this member moments ago (`hardware/plug_in.py`),
        while no call has been answered it: the first is, every later one listens — `take`
        spends it."""
        return INSPECTIONS.unasked(
            self.project_id,
            self.user_id,
            str(args.get("device_ref")),
            within_s=INSPECTION_FRESH_S,
            take=take,
        )

    async def needs_confirmation(self, args: dict[str, Any]) -> bool:
        """Card the listen only when opening the port would restart a running board."""
        if self._fresh(args) is not None:
            return False  # no port is opened
        ref = str(args.get("device_ref"))
        return bool(await asyncio.to_thread(self.local.listen_restarts, ref))

    def card(self, stored_args: dict[str, Any]) -> Card:
        ref = chip(stored_args["device_ref"], 140)  # the device's own serial: one chip
        return Card(
            kind="approval",
            title="Approve: restart the board to listen",
            body=f"This restarts the board to listen to it: {ref}.",
            more=(
                "Opening a running board's port resets it, so its program starts over; "
                "listening itself changes nothing."
            ),
            primary="Restart and listen",
            secondary="Not now",
            receipt=f"Listened to {ref}",
        )

    def working(self, args: dict[str, Any]) -> str:
        # Solus's own line: a ref only when its pattern admits it, and then inside one chip.
        ref = args.get("device_ref")
        admitted = isinstance(ref, str) and re.fullmatch(DEVICE_REF_PATTERN, ref) is not None
        return f"Listening to {chip(ref, 140) if admitted else 'the device'}"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if (fresh := self._fresh(args, take=True)) is not None:
            # Said as heard earlier, never as a listen made now.
            return {**_inspection_summary(fresh), "heard_s_ago": INSPECTIONS.age_s(fresh)}
        ref = str(args["device_ref"])
        # The gate may have passed this call on a plug-in's inspection that another turn spent
        # (or that aged out) since: a restart is never the fallback for a card nobody saw.
        if args.get("restart_approved") is not True and await asyncio.to_thread(
            self.local.listen_restarts, ref
        ):
            raise ToolException(
                "Listening now restarts the board; call hardware.inspect_device again so the "
                "person can approve it.",
                code=ToolErrorCode.UNAUTHORIZED,
                retryable=True,
            )
        async with self.sessions() as session:
            try:
                inspection = await inspect_device(
                    session,
                    self.local,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    device_ref=ref,
                )
            except APIError as exc:
                raise _tool_refusal(exc) from None
            await session.commit()
        return _inspection_summary(inspection)


# --------------------------------------------------------------------------- expected_parts


#: An expected row's fields that carry the workspace's own text, cut to one line each.
_EXPECTED_TEXT: Final = ("model", "symbol", "value")


def _expected_row(row: Mapping[str, Any]) -> dict[str, Any]:
    capped: dict[str, Any] = {key: _capped_line(row[key]) for key in _EXPECTED_TEXT if key in row}
    if "libraries" in row:
        capped["libraries"] = [_capped_line(name) for name in row["libraries"]]
    return {**row, **capped}


class ExpectedParts(_HardwareRead):
    name = EXPECTED_PARTS
    description = (
        "What the workspace says should exist, to compare with what is plugged in: planned "
        "bus-map rows of robots (library slots too), MCU symbols in schematics, sensor topics "
        "in ROS code and the libraries sketches include. Give robot_id for one robot's rows."
    )
    params = {
        "type": "object",
        "properties": {"robot_id": _UUID},
        "additionalProperties": False,
    }

    def working(self, args: dict[str, Any]) -> str:
        return "Reading what the workspace says should be here"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        robot = uuid.UUID(args["robot_id"]) if "robot_id" in args else None
        async with self.sessions() as session:
            found = await expected_parts(session, self.project_id, self.visible(), robot)
        return _fitted({"expected": [_expected_row(part.row) for part in found]}, "expected")


# --------------------------------------------------------------------------- list_parts


class ListParts(_HardwareRead):
    name = LIST_PARTS
    description = (
        "The robots and parts in the person's hardware connections: what each is, its robot, "
        "whether it is in the workspace graph and the device it was found on. Give robot_id "
        "for one robot's parts."
    )
    params = {
        "type": "object",
        "properties": {"robot_id": _UUID},
        "additionalProperties": False,
    }

    def working(self, args: dict[str, Any]) -> str:
        return "Reading the hardware connections"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        from solus_api.hardware.ownership import list_parts

        wanted = str(uuid.UUID(args["robot_id"])) if "robot_id" in args else None
        async with self.sessions() as session:
            stmt = select(GraphEntity).where(
                *self.visible(),
                GraphEntity.kind == kinds.PHYSICAL_ROBOT,
                GraphEntity.origin == "manual",
            )
            robots = list(await session.scalars(stmt.order_by(GraphEntity.name).limit(MAX_ROWS)))
            parts, meta = await list_parts(
                session, self.project_id, self.user_id, ownership="all", limit=100, cursor=None
            )
        shown = [
            {
                "id": str(part.id),
                "name": part.name,
                "kind": part.kind,
                "robot_id": str(parent) if parent else None,
                "in_graph": part.attrs.get(IN_GRAPH) is not False,
                "device_ref": part.external_ref,
            }
            for part, parent in parts
            if wanted is None or str(parent) == wanted
        ]
        return _fitted(
            {
                "robots": [
                    _robot_listing(robot)
                    for robot in robots
                    if wanted is None or str(robot.id) == wanted
                ],
                "parts": shown,
                "complete": not meta["has_next"],
            },
            "parts",
        )


def _robot_listing(robot: GraphEntity) -> dict[str, Any]:
    connection = robot.attrs.get("connection")
    return {
        "id": str(robot.id),
        "name": robot.name,
        "in_graph": robot.attrs.get(IN_GRAPH) is not False,
        "device_ref": robot.external_ref,
        "connection": connection.get("status") if isinstance(connection, Mapping) else None,
    }


# --------------------------------------------------------------------------- read_evidence


class ReadEvidence(_HardwareRead):
    name = READ_EVIDENCE
    description = (
        "What one source proposes about a robot, read-only. firmware or host_config: rows "
        "from an authorized file (source_ref) about the brain_id of robot_id — without "
        "source_ref, the person's authorized files are listed. cad: the robot a CAD part "
        "(part_id) belongs to by its matched identity links."
    )
    params = {
        "type": "object",
        "properties": {
            "source": {"enum": ["firmware", "host_config", "cad"]},
            "robot_id": _UUID,
            "brain_id": _UUID,
            "source_ref": {"type": "string", "pattern": r"^source:[0-9a-f-]{36}$"},
            "part_id": _UUID,
        },
        "required": ["source"],
        "additionalProperties": False,
    }

    def working(self, args: dict[str, Any]) -> str:
        return f"Reading {_EVIDENCE_WORDS.get(str(args.get('source')), 'the')} evidence"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if args["source"] == "cad":
            return await self._cad(args)
        if "source_ref" not in args:
            return await self._sources()
        if not {"robot_id", "brain_id"} <= args.keys():
            raise ToolException(
                "Name the robot_id and the brain_id the file is about.",
                code=ToolErrorCode.INVALID_ARGS,
            )
        return await self._extraction(args)

    async def _sources(self) -> dict[str, Any]:
        """The member's authorized sources by ref and suffix. Listing opens no file."""
        from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError

        def listed() -> list[tuple[str, str]]:
            try:
                reader = LocalHardwareSources.for_local_runner(self.local)
                return reader.listed_sources(self.project_id, self.user_id)
            except LocalSourceError:
                return []

        found = await asyncio.to_thread(listed)
        return {"sources": [{"source_ref": ref, "suffix": suffix} for ref, suffix in found]}

    async def _extraction(self, args: dict[str, Any]) -> dict[str, Any]:
        from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
        from solus_api.hardware.topology_proposals import ExtractionRequest, TopologyProposalService

        keys = ("brain_id", "source_ref")
        async with self.sessions() as session:
            try:
                request = ExtractionRequest.model_validate(
                    {**{key: args[key] for key in keys}, "source_kind": args["source"]}
                )
                reader = LocalHardwareSources.for_local_runner(self.local)
                proposal = await TopologyProposalService(
                    session, self.project_id, self.user_id, reader
                ).propose(uuid.UUID(args["robot_id"]), request)
            except APIError as exc:
                raise _tool_refusal(exc) from None
            except LocalSourceError:
                raise ToolException(
                    "The local hardware runner is unavailable.", code=ToolErrorCode.UNAVAILABLE
                ) from None
        extraction = proposal.extraction
        rows = [
            {
                "bus": _capped_line(row.bus),
                "device": _capped_line(row.device),
                "protocol": _capped_line(row.protocol),
                "address": _capped_line(row.address),
                "part_candidate": _capped_line(row.part_candidate),
                "confidence": row.confidence,
            }
            for row in extraction.rows[:MAX_ROWS]
        ]
        return _fitted(
            {
                "source": args["source"],
                "robot_id": args["robot_id"],
                "brain_id": args["brain_id"],
                "source_ref": args["source_ref"],
                "proposal_digest": proposal.proposal_digest,
                "status": extraction.status,
                "notes": [_capped_line(note, 200) for note in extraction.notes[:8]],
                "rows": rows,
            },
            "rows",
        )

    async def _cad(self, args: dict[str, Any]) -> dict[str, Any]:
        from solus_api.hardware.cad_suggestions import cad_association

        if "part_id" not in args:
            raise ToolException("Name the CAD part_id.", code=ToolErrorCode.INVALID_ARGS)
        part = uuid.UUID(args["part_id"])
        async with self.sessions() as session:
            try:
                link = await cad_association(session, self.project_id, part, self.user_id)
            except APIError as exc:
                raise _tool_refusal(exc) from None
        candidate = (
            None
            if link is None
            else {
                "robot_id": str(link.candidate_robot_id),
                "confidence": link.confidence,
                "reason": link.reason,
            }
        )
        return {"source": "cad", "part_id": str(part), "candidate": candidate}


# --------------------------------------------------------------------------- search_library


class SearchLibrary(_HardwareRead):
    name = SEARCH_LIBRARY
    description = (
        "Solus's library of part and platform definitions, by words in their names and "
        "keywords. Match against the workspace first; the library names what nothing there "
        "describes."
    )
    params = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "maxLength": 256},
            "kind": {"enum": ["part", "platform"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["q"],
        "additionalProperties": False,
    }

    def working(self, args: dict[str, Any]) -> str:
        return "Searching the parts library"  # the model's query is never Solus's line

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        from solus_api.hardware.library import load_library

        hits = load_library().search(args["q"], kind=args.get("kind"), limit=args.get("limit", 10))
        return {
            "hits": [
                {
                    "kind": hit.kind,
                    "id": hit.id,
                    "name": hit.name,
                    "manufacturer": hit.manufacturer,
                    "summary": hit.summary,
                }
                for hit in hits
            ]
        }


_READS: Final = (ListDevices, InspectDevice, ExpectedParts, ListParts, ReadEvidence, SearchLibrary)


def register_hardware_tools(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    local: Any,
    hub: LiveHub | None = None,
) -> None:
    """The hardware reads, as `user_id` in `project_id`, over this API's local runner; with the
    app's `hub` to publish through, the card tools too (P2-T5, `hardware_cards`)."""
    for read in _READS:
        registry.register(read(sessions, project_id, user_id, local))
    if hub is not None:
        from solus_api.agent.tools.hardware_cards import register_hardware_cards

        register_hardware_cards(
            registry, sessions, project_id, user_id=user_id, local=local, hub=hub
        )


__all__ = [
    "EXPECTED_PARTS",
    "HARDWARE_READS",
    "INSPECT_DEVICE",
    "LIST_DEVICES",
    "LIST_PARTS",
    "READ_EVIDENCE",
    "SEARCH_LIBRARY",
    "register_hardware_tools",
]
