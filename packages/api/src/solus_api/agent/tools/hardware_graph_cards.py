"""SOLUSDEV-326 P2-T5 — SOL's card tools that write the graph around hardware.

- `hardware.apply_evidence` — rows `read_evidence` proposed from an authorized firmware or host
  config file, added to the robot's wiring (`TopologyAcceptanceService`).
- `hardware.link_part` — a part linked to design nodes: its CAD body or schematic component is the
  same physical part (`same_as`); a code site commands or reads it. A target that cannot be linked
  is named and left out; the rest are linked (`graph/edges.write_edge`).
- `hardware.import_definition` — a library platform as a new robot, out of the graph for the member
  who imports it, or a library part into a robot they can see (`library_import`).
- `hardware.set_in_graph` — a robot or a lone part into the workspace graph or out of it
  (`in_graph.set_in_graph`); the card says what moves with it.

Each is a `hardware_cards._HardwareCard`: gated statically, its offer card built from the stored
arguments and the `shown` stamped beside them, its preview reading Solus's own state alone
(apply_evidence reads the member's file once, when it parks; the write refuses changed evidence).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.cards import chip, single_line
from solus_api.agent.confirmations import _canonical
from solus_api.agent.tools.hardware_cards import (
    _ID,
    _KEPT_OUT,
    _NAME,
    _ON_ROBOT,
    _ONLY_YOU,
    _YOUR_TEAM,
    ADD_PARTS,
    APPLY_EVIDENCE,
    IMPORT_DEFINITION,
    LINK_PART,
    MAX_CARD_ROWS,
    SET_IN_GRAPH,
    _chips,
    _clipped,
    _counted,
    _HardwareCard,
    _line_row,
    _offer,
    _refusal_of,
    _robot_shown,
    _stored_name,
    _uuid,
    _Written,
)
from solus_api.agent.tools.hardware_onboarding import SEARCH_LIBRARY, _tool_refusal
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.contracts.action_gate import Card, CardField
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.read_scope import IN_GRAPH, ONBOARDED_BY, bind_scope
from solus_api.hardware.in_graph import (
    ONLY_ONBOARDER,
    _members,
    _wired_parts,
    set_in_graph,
    wired_hidden,
)
from solus_api.hardware.library import PartDefinition, load_library
from solus_api.hardware.library_import import import_part_into_robot, import_platform
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
from solus_api.hardware.store import PART_KINDS, hardware_entity, robot_root
from solus_api.hardware.topology import derived_nodes
from solus_api.hardware.topology_acceptance import ExtractionConfirm, TopologyAcceptanceService
from solus_api.hardware.topology_evidence import TopologyEvidence
from solus_api.hardware.topology_proposals import (
    ExtractionProposal,
    ExtractionRequest,
    TopologyProposalService,
)
from solus_api.models import GraphEntity, Project, User
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_graph import lock_project

MAX_LINKS: Final = 16
_CODE_KINDS: Final = frozenset({kinds.CODE_FILE, kinds.CODE_MODULE, kinds.ARDUINO_SKETCH})
_WIRING: Final = frozenset({kinds.HARDWARE_BRAIN, kinds.HARDWARE_BUS, kinds.HARDWARE_EVIDENCE})
_RELATIONS: Final = {
    "same_as": "the same physical part",
    "commands": "commands it",
    "reads": "reads it",
}
_SOURCES: Final = {"firmware": "firmware", "host_config": "host config"}


# --------------------------------------------------------------------------- evidence


def _evidence_line(row: TopologyEvidence) -> str:
    words = (
        row.device,
        row.protocol,
        f"at {row.address}" if row.address else None,
        f"on {row.bus}" if row.bus else None,
    )
    return single_line(" ".join(word for word in words if word) or "a row of evidence", 200)


class ApplyEvidence(_HardwareCard):
    name = APPLY_EVIDENCE
    description = (
        "Add rows hardware.read_evidence proposed to the robot's wiring: the same source, "
        "robot_id, brain_id, source_ref and proposal_digest, and the rows to keep (row_index, a "
        "short name, entity_id when the row is a part the robot has). Changed evidence is "
        "refused. Parks a card."
    )
    params = {
        "type": "object",
        "properties": {
            "source": {"enum": ["firmware", "host_config"]},
            "robot_id": _ID,
            "brain_id": _ID,
            "source_ref": {"type": "string", "pattern": r"^source:[0-9a-f-]{36}$"},
            "proposal_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "rows": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CARD_ROWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "row_index": {"type": "integer", "minimum": 0, "maximum": 255},
                        "name": _NAME,
                        "entity_id": _ID,
                    },
                    "required": ["row_index", "name"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["source", "robot_id", "brain_id", "source_ref", "proposal_digest", "rows"],
        "additionalProperties": False,
    }
    consent = "Add the shown evidence rows to the robot's wiring"
    #: `evidence` is each kept row as the member's file said it when the card was parked.
    stamps = ("shown", "evidence")

    def working(self, args: dict[str, Any]) -> str:
        return "Preparing the evidence to add"

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        rows = [{**row, "name": str(row["name"]).strip()} for row in args["rows"]]
        # One name is one card row: two rows of a name could not be told apart on the card.
        kept = ({row["row_index"] for row in rows}, {row["name"].casefold() for row in rows})
        if any(len(once) != len(rows) for once in kept) or not all(row["name"] for row in rows):
            raise _refusal_of("Keep each row once, each with a short name.")
        return {**args, "rows": rows}

    def _reader(self) -> LocalHardwareSources:
        try:
            return LocalHardwareSources.for_local_runner(self.local)
        except LocalSourceError:
            raise APIError(
                503, "source_unavailable", "The local hardware runner is unavailable."
            ) from None

    async def _proposal(self, session: AsyncSession, args: Mapping[str, Any]) -> ExtractionProposal:
        request = ExtractionRequest.model_validate(
            {
                "brain_id": args["brain_id"],
                "source_ref": args["source_ref"],
                "source_kind": args["source"],
            }
        )
        service = TopologyProposalService(session, self.project_id, self.user_id, self._reader())
        return await service.propose(_uuid(args["robot_id"]), request)

    async def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """The file is read once, here: its rows are stamped as `evidence`, so the preview reads
        Solus's own state alone. Evidence that changes later is refused by the write, which
        proposes again and compares the digest (`TopologyAcceptanceService.confirm`)."""
        stored = await super().stored_args(args)
        try:
            with bind_scope(self.scope()):
                async with self.sessions() as session:
                    return {**stored, "evidence": await self._evidence(session, stored)}
        except APIError as exc:
            raise _tool_refusal(exc) from None

    async def _evidence(self, session: AsyncSession, args: Mapping[str, Any]) -> list[str]:
        proposal = await self._proposal(session, args)
        if proposal.proposal_digest != args["proposal_digest"]:
            raise APIError(
                409,
                "proposal_changed",
                "The evidence changed since it was read; read it again (hardware.read_evidence).",
            )
        evidence = proposal.extraction.rows
        if any(pick["row_index"] >= len(evidence) for pick in args["rows"]):
            raise APIError(422, "validation_error", "A row is not in the evidence.")
        return [_evidence_line(evidence[pick["row_index"]]) for pick in args["rows"]]

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        robot = await robot_root(session, self.project_id, _uuid(args["robot_id"]))
        return {"robot": robot.name, "entities": await self._entities(session, args)}

    async def _entities(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, str]:
        """The parts rows name, as the member sees them (404 when one is not theirs to see)."""
        ids = {_uuid(pick["entity_id"]) for pick in args["rows"] if "entity_id" in pick}
        if not ids:
            return {}
        rows = await session.execute(
            select(GraphEntity.id, GraphEntity.name).where(*self.visible(), GraphEntity.id.in_(ids))
        )
        found = {str(entity_id): name for entity_id, name in rows.tuples()}
        if len(found) != len(ids):
            raise APIError(404, "not_found", "A part a row names was not found.")
        return found

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        shown = stored["shown"]
        return [
            _line_row("Robot", shown["robot"]),
            _line_row("From", f"your {_SOURCES[stored['source']]} file"),
            *(
                _line_row(
                    pick["name"], line, before=shown["entities"].get(pick.get("entity_id", ""))
                )
                for pick, line in zip(stored["rows"], stored["evidence"], strict=True)
            ),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        robot = stored["shown"]["robot"]
        names = [pick["name"] for pick in stored["rows"]]
        rows = _counted(len(names), "row")
        return _offer(
            f"Add {rows} of evidence to the robot",
            f"From your {_SOURCES[stored['source']]} file to {chip(robot, 60)}: {_chips(names)}.",
            "Add",
            f"{_clipped(robot)}: {rows} of evidence added",
            more="Evidence records what a source says about the robot's wiring; its config "
            "stays as it is.",
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        selected = _canonical([args["rows"], args["proposal_digest"]])
        body = ExtractionConfirm.model_validate(
            {
                "brain_id": args["brain_id"],
                "source_ref": args["source_ref"],
                "source_kind": args["source"],
                "proposal_digest": args["proposal_digest"],
                "operation_id": str(
                    uuid.uuid5(self.project_id, f"{self.user_id}:{APPLY_EVIDENCE}:{selected}")
                ),
                "selections": [dict(pick) for pick in args["rows"]],
            }
        )
        service = TopologyAcceptanceService(session, self.project_id, self.user_id, self._reader())
        result, replayed = await service.confirm(_uuid(args["robot_id"]), body)
        value = {**result.model_dump(mode="json"), "replayed": replayed}
        if replayed:
            return _Written(value=value)
        count = len(result.entity_ids)
        confirmed = {
            "robot_id": str(args["robot_id"]),
            "brain_id": str(args["brain_id"]),
            "count": count,
        }
        return _Written(
            value=value,
            counts=GraphChangeCounts(entities_created=result.created, relations_created=count),
            events=(("hardware.extraction_confirmed", confirmed),),
        )


# --------------------------------------------------------------------------- links


def _link_target(
    entity: GraphEntity | None, wanted: Mapping[str, Any], part_id: uuid.UUID
) -> dict[str, Any]:
    """One target as the card shows it: the relation it gets, or why it gets none."""
    shown: dict[str, Any] = {
        "entity_id": str(wanted["entity_id"]),
        "name": None,
        "relation": None,
        "reason": None,
    }
    if entity is None:
        return {**shown, "reason": "not found"}
    shown["name"] = single_line(entity.name, 80)
    if entity.id == part_id or (entity.origin == "manual" and entity.source_id is None):
        return {**shown, "reason": "made in Solus, not a design node"}
    if entity.kind in _CODE_KINDS:
        relation = wanted.get("relation")
        if relation is None:
            return {**shown, "reason": "say whether this code commands or reads the part"}
        return {**shown, "relation": relation}
    if entity.kind in PART_KINDS:
        return {**shown, "relation": "same_as"}
    return {**shown, "reason": "not a CAD body, schematic component or code site"}


class LinkPart(_HardwareCard):
    name = LINK_PART
    description = (
        "Link a hardware part to design nodes: its CAD body or schematic component (the same "
        "physical part), or a code site that commands or reads it (say which in relation). "
        "Targets that cannot be linked are named and skipped. Parks a card."
    )
    params = {
        "type": "object",
        "properties": {
            "part_id": _ID,
            "targets": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_LINKS,
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_id": _ID,
                        "relation": {"enum": ["commands", "reads"]},
                    },
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["part_id", "targets"],
        "additionalProperties": False,
    }
    consent = "Link the shown part to the shown design nodes"

    def working(self, args: dict[str, Any]) -> str:
        return "Checking what the part can link to"

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        ids = [str(target["entity_id"]).lower() for target in args["targets"]]
        if len(set(ids)) != len(ids):
            raise _refusal_of("Name each target once.")
        return dict(args)

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        part = await hardware_entity(session, self.project_id, _uuid(args["part_id"]))
        if part.kind not in PART_KINDS or part.origin != "manual" or part.source_id is not None:
            raise APIError(409, "conflict", "Only a hardware part is linked here.")
        ids = [_uuid(target["entity_id"]) for target in args["targets"]]
        found = {
            row.id: row
            for row in await session.scalars(
                select(GraphEntity).where(*self.visible(), GraphEntity.id.in_(ids))
            )
        }
        targets = [
            _link_target(found.get(_uuid(target["entity_id"])), target, part.id)
            for target in args["targets"]
        ]
        if not any(target["relation"] for target in targets):
            reasons = "; ".join(f"{t['name'] or t['entity_id']}: {t['reason']}" for t in targets)
            raise APIError(422, "validation_error", single_line(f"Nothing to link: {reasons}", 300))
        return {"part": part.name, "targets": targets}

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        shown = stored["shown"]
        return [
            _line_row("Part", shown["part"]),
            *(
                _line_row(
                    target["name"] or target["entity_id"],
                    _RELATIONS[target["relation"]]
                    if target["relation"]
                    else f"not linked: {target['reason']}",
                )
                for target in shown["targets"]
            ),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        shown = stored["shown"]
        linked = [target["name"] for target in shown["targets"] if target["relation"]]
        left = len(shown["targets"]) - len(linked)
        return _offer(
            f"Link this part to {_counted(len(linked), 'design node')}",
            f"{chip(shown['part'], 60)} ↔ {_chips(linked)}."
            + (f" {left} more can't be linked." if left else ""),
            "Link",
            f"{_clipped(shown['part'])}: {_counted(len(linked), 'link')}",
            more="A link says two nodes are one physical part, or that code commands or reads "
            "it; nothing is imported.",
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        await lock_project(session, self.project_id)
        shown = await self.shown(session, args)  # as it stands now, under the lock
        part_id = _uuid(args["part_id"])
        linked: list[dict[str, Any]] = []
        skipped = [
            {"entity_id": target["entity_id"], "reason": target["reason"]}
            for target in shown["targets"]
            if not target["relation"]
        ]
        for target in (t for t in shown["targets"] if t["relation"]):
            try:
                await self._link_one(session, part_id, target)
            except APIError as exc:
                skipped.append({"entity_id": target["entity_id"], "reason": exc.message})
                continue
            linked.append({"entity_id": target["entity_id"], "relation": target["relation"]})
        outcome = {"part_id": str(part_id), "linked": len(linked), "skipped": len(skipped)}
        return _Written(
            value={"part_id": str(part_id), "linked": linked, "skipped": skipped},
            counts=GraphChangeCounts(relations_created=len(linked)) if linked else None,
            events=(("hardware.part_linked", outcome),),
        )

    async def _link_one(
        self, session: AsyncSession, part_id: uuid.UUID, target: Mapping[str, Any]
    ) -> None:
        other = _uuid(target["entity_id"])
        same = target["relation"] == "same_as"
        await write_edge(
            session,
            project_id=self.project_id,
            src_id=part_id if same else other,
            dst_id=other if same else part_id,
            relation_type=target["relation"],
            origin="manual",
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.USER_CONFIRMED, ref=str(self.user_id))],
            created_by=self.user_id,
        )


# --------------------------------------------------------------------------- the library


def _library_definition(definition_id: str) -> dict[str, Any]:
    """A library definition as its card shows it (static: the shipped library)."""
    library = load_library()
    platform = library.platforms.get(definition_id)
    if platform is not None:
        parts = [
            [slot.role, library.parts[slot.part].name, slot.address] for slot in platform.parts
        ]
        return {"platform": True, "name": platform.name, "parts": parts}
    part = library.parts.get(definition_id)
    if part is None:
        raise APIError(404, "not_found", "No such definition in the library.")
    return {"platform": False, "name": part.name, "parts": []}


class ImportDefinition(_HardwareCard):
    name = IMPORT_DEFINITION
    description = (
        "Add a hardware.search_library definition: a platform as a new robot (out of the "
        "workspace graph until the person adds it), or a part into a robot (robot_id). name "
        "names it. Parks a card."
    )
    params = {
        "type": "object",
        "properties": {
            "definition_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "robot_id": _ID,
            "name": _NAME,
        },
        "required": ["definition_id"],
        "additionalProperties": False,
    }
    consent = "Add the shown library definition"

    def working(self, args: dict[str, Any]) -> str:
        return "Looking up the library definition"

    def stamp(self, args: dict[str, Any]) -> dict[str, Any]:
        library = load_library()
        platform = library.platforms.get(str(args["definition_id"]))
        if platform is None and str(args["definition_id"]) not in library.parts:
            raise _refusal_of(
                f"No such definition; search the library ({SEARCH_LIBRARY}).",
                ToolErrorCode.NOT_FOUND,
            )
        if platform is not None and ("robot_id" in args or len(platform.parts) > MAX_CARD_ROWS):
            raise _refusal_of("A platform becomes a new robot of its own; leave out robot_id.")
        if platform is None and "robot_id" not in args:
            raise _refusal_of(
                f"A library part goes into a robot: give robot_id ({ADD_PARTS} adds an "
                "inspected device on its own)."
            )
        name = _stored_name(args.get("name", ""))
        stored = {key: value for key, value in args.items() if key != "name"}
        return {**stored, **({"name": name} if name else {})}

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        target = {"kind": "existing", "robot_id": args["robot_id"]} if "robot_id" in args else {}
        return {
            "definition": _library_definition(str(args["definition_id"])),
            "robot": await _robot_shown(session, self.project_id, target),
        }

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        definition, robot = stored["shown"]["definition"], stored["shown"]["robot"]
        name = stored.get("name") or definition["name"]
        if definition["platform"]:
            return [
                _line_row("Robot", f"{name} (new)"),
                *(
                    _line_row(f"Part {role}", f"{model} at {address}")
                    for role, model, address in definition["parts"]
                ),
                _line_row("Who sees it", _ONLY_YOU),
            ]
        return [
            _line_row("Robot", robot["name"]),
            _line_row("Part", f"{name} ({definition['name']})"),
            _line_row("Who sees it", _YOUR_TEAM if robot["in_graph"] else _ONLY_YOU),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        definition, robot = stored["shown"]["definition"], stored["shown"]["robot"]
        name = stored.get("name") or definition["name"]
        if definition["platform"]:
            roles = [role for role, _, _ in definition["parts"]]
            return _offer(
                "Add a new robot from the library",
                f"{chip(definition['name'], 60)} with {_counted(len(roles), 'part')}: "
                f"{_chips(roles)}.",
                "Add",
                f"{_clipped(name)} added from the library",
                more=_KEPT_OUT,
                field=CardField(label="Robot name", value=single_line(name, 200)),
            )
        return _offer(
            "Add a library part to your robot",
            f"{chip(definition['name'], 60)} as {chip(name, 60)} on {chip(robot['name'], 60)}.",
            "Add",
            f"{_clipped(name)} added to {_clipped(robot['name'])}",
            more=_ON_ROBOT,
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        library = load_library()
        platform = library.platforms.get(str(args["definition_id"]))
        if platform is None:
            return await self._part(session, args, library.parts[str(args["definition_id"])])
        imported = await import_platform(
            session,
            self.local,
            library,
            platform,
            project_id=self.project_id,
            user_id=self.user_id,
            name=args.get("name"),
            in_graph=False,
            onboarded_by=self.user_id,
        )
        robot, parts = imported.robot, len(imported.part_ids)
        added = {"definition_id": platform.id, "robot_id": str(robot.id), "parts": parts}
        suggested = (
            ("hardware.suggestion_created", {"suggestion_id": str(row.id), "tier": row.tier})
            for row in imported.suggestions
        )
        return _Written(
            value={
                "robot_id": str(robot.id),
                "robot": robot.name,
                "part_ids": [str(part) for part in imported.part_ids],
                "in_graph": False,
            },
            counts=GraphChangeCounts(entities_created=1 + parts, relations_created=parts),
            events=(("hardware.library_imported", added), *suggested),
        )

    async def _part(
        self, session: AsyncSession, args: Mapping[str, Any], part: PartDefinition
    ) -> _Written:
        robot_id = str(args["robot_id"])
        entity, _ = await import_part_into_robot(
            session,
            part,
            project_id=self.project_id,
            user_id=self.user_id,
            robot_id=_uuid(robot_id),
            name=args.get("name"),
        )
        added = {"definition_id": part.id, "robot_id": robot_id, "parts": 1}
        return _Written(
            value={"part_id": str(entity.id), "part": entity.name, "robot_id": robot_id},
            counts=GraphChangeCounts(entities_created=1, relations_created=1),
            events=(("hardware.library_imported", added),),
        )


# --------------------------------------------------------------------------- the graph


def _moved_kind(row: GraphEntity) -> str:
    if row.kind in PART_KINDS:
        return "part"
    if row.kind in _WIRING:
        return "wiring"
    return "run" if row.kind == kinds.BENCH_RUN else "other"


def _in_words(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}"


def _what_moves(shown: Mapping[str, Any]) -> str:
    counts = (
        (shown["parts"], "part"),
        (shown["wiring"], "wiring node"),
        (shown["runs"], "bench run"),
    )
    named = [_counted(number, noun) for number, noun in counts if number]
    return _in_words(named) if named else ""


class SetInGraph(_HardwareCard):
    name = SET_IN_GRAPH
    description = (
        "Add a robot (with its parts, wiring and runs) or a lone part to the workspace graph so "
        "the person's team sees it, or take it out (in_graph false; only its onboarder can). "
        "Parks a card saying what moves."
    )
    params = {
        "type": "object",
        "properties": {"entity_id": _ID, "in_graph": {"type": "boolean"}},
        "required": ["entity_id", "in_graph"],
        "additionalProperties": False,
    }
    consent = "Move the shown hardware into or out of the workspace graph"

    def working(self, args: dict[str, Any]) -> str:
        return "Checking what moves with it"

    async def shown(self, session: AsyncSession, args: Mapping[str, Any]) -> dict[str, Any]:
        target = await hardware_entity(session, self.project_id, _uuid(args["entity_id"]))
        wanted = args["in_graph"] is True
        if (target.attrs.get(IN_GRAPH) is not False) is wanted:
            where = "in" if wanted else "out of"
            raise APIError(409, "conflict", f"{target.name} is already {where} the graph.")
        if not wanted and target.attrs.get(ONBOARDED_BY) != str(self.user_id):
            raise APIError(403, "forbidden", ONLY_ONBOARDER)
        members = await _members(session, self.project_id, target)
        moved = Counter(_moved_kind(row) for row in members if row.id != target.id)
        robot = target.kind == kinds.PHYSICAL_ROBOT
        return {
            "name": target.name,
            "robot": robot,
            "parts": moved["part"],
            "wiring": moved["wiring"]
            + (await self._shared(session, target.id) if robot and wanted else 0),
            "runs": moved["run"],
            "wired": await self._wired(session, members) if wanted else [],
        }

    async def _shared(self, session: AsyncSession, robot_id: uuid.UUID) -> int:
        """Wiring this robot shares with others that joins the graph with it (`stamp_shared`)."""
        _, shared = await derived_nodes(session, self.project_id, robot_id)
        return sum(node.attrs.get(IN_GRAPH) is False for node in shared)

    async def _wired(self, session: AsyncSession, members: Sequence[GraphEntity]) -> list[str]:
        """The member's parts on other hardware that join the graph because the configs of what
        moves wire them — what `set_in_graph` admits (409, naming nothing, when one is not the
        member's to add)."""
        ids = {row.id for row in members}
        wired = await _wired_parts(session, self.project_id, ids)
        joining = await wired_hidden(session, self.project_id, wired, str(self.user_id))
        return sorted(single_line(part.name, 80) for part in joining if part.id not in ids)

    def rows(self, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        shown, wanted = stored["shown"], stored["in_graph"] is True
        return [
            _line_row(
                f"{'Robot' if shown['robot'] else 'Part'} {shown['name']}",
                _YOUR_TEAM if wanted else _ONLY_YOU,
                before=_ONLY_YOU if wanted else _YOUR_TEAM,
            ),
            _line_row("Moves with it", _what_moves(shown) or "nothing else"),
            *(
                _line_row("Wired part on other hardware", name, before=_ONLY_YOU)
                for name in shown["wired"]
            ),
        ]

    def card(self, stored: dict[str, Any]) -> Card:
        shown = stored["shown"]
        thing, moves = "robot" if shown["robot"] else "part", _what_moves(shown)
        name = shown["name"]
        what = f"{chip(name, 60)} and its {moves}" if moves else chip(name, 60)
        more = "The workspace graph is what your whole team works from."
        if stored["in_graph"] is True:
            wired = shown["wired"]
            if wired:
                what += f" and {_counted(len(wired), 'wired part')} on other hardware: "
                what += _chips(wired)
            many = bool(moves or wired)
            return _offer(
                f"Add this {thing} to the workspace graph",
                f"{what} {'move' if many else 'moves'} into the workspace graph; your team "
                f"will see {'them' if many else 'it'}.",
                "Add to workspace graph",
                f"{_clipped(name)} added to the graph",
                more=more,
            )
        return _offer(
            f"Take this {thing} out of the graph",
            f"{what} {'leave' if moves else 'leaves'} the workspace graph. Only you will see "
            f"{'them' if moves else 'it'}, in your hardware connections.",
            "Remove from graph",
            f"{_clipped(name)} taken out of the graph",
            more=more,
        )

    async def write(self, session: AsyncSession, args: Mapping[str, Any]) -> _Written:
        """`set_in_graph` commits, emits its one data event and publishes itself."""
        project = await session.get(Project, self.project_id)
        viewer = await session.get(User, self.user_id)
        if project is None or viewer is None:
            raise APIError(404, "not_found", "Project not found")
        wanted = args["in_graph"] is True
        change = await set_in_graph(
            session, project, viewer, _uuid(args["entity_id"]), wanted, hub=self.hub
        )
        return _Written(
            value={
                "entity_id": str(change.entity.id),
                "in_graph": wanted,
                "updated": change.updated,
            }
        )


#: Registered beside add_parts and add_connection (`hardware_cards.register_hardware_cards`).
GRAPH_CARDS: Final = (ApplyEvidence, LinkPart, ImportDefinition, SetInGraph)

__all__ = ["GRAPH_CARDS", "MAX_LINKS"]
