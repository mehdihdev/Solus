"""SOL's finding, run and envelope reads (SOLUSDEV-321 P1-T4, P2-T1): `get_finding`, `get_run`
and `get_envelope`.

`get_finding` reads one finding through `load_finding`, `subject_rows` and `serialize_finding` —
the findings route's own reads — and renders its headline, status, the entities it blames and
its newest evidence (never the re-raise history). The evidence is one row per key, `{"evidence":
{key: value}}`: nested, so the redactor sees every key beside its value, and a row of its own, so
an evidence too large for the result still shows the keys that fit. `get_run` reads the recorded
summary of one bench run through `runs.store.record`, the project-scoped loader the run routes
use; a run's packets, an artifact of up to 8 MiB, are not rendered. `get_envelope` tells one
quantity of one part through `part_envelopes`: its nominal, warn and limit and where each came
from, or that nothing states any. It reads the database alone, so a baseline run's learned bounds
(its packets are an artifact, and no store is bound here) are not among them. An id the project
does not hold — absent, deleted, another kind, or another project's — is the same `not_found`, so
neither is an existence oracle. The project is bound at registration by Solus code; no argument
names it.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.tools.read_tool import ReadResult, bounded_read_tool, uuid_arg, uuid_params
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.core.errors import APIError
from solus_api.graph.findings import load_finding, serialize_finding, subject_rows
from solus_api.livebench.findings.envelopes import QUANTITIES, envelope_line, part_envelopes
from solus_api.livebench.runs import store as run_store
from solus_api.orchestration.gateway import default_orchestration_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.tools.registry import ToolRegistry

#: Subjects named in full; `subject_count` carries the rest, so a finding blaming many parts
#: leaves room for its evidence in the 20 rows.
_SUBJECTS: Final = 6


async def get_finding_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    finding_id = uuid_arg(args, "finding_id")
    async with sessions() as session:
        finding = await load_finding(session, project_id, finding_id)
        subjects = await subject_rows(session, finding)
    data = serialize_finding(finding, subjects)
    return [
        {
            "id": data["id"],
            "headline": data["headline"],
            "severity": data["severity"],
            "status": data["status"],
            "rule": data["rule_id"],
            "source": data["source"],
            "domain": data["domain"],
            "matrix_cell": data["matrix_cell"],
            "count": data["count"],
            "first_seen": data["first_seen"],
            "last_seen": data["last_seen"],
            "subject_count": len(data["subject_entities"]),
            "explanation": data["explanation"],
            "detail": data["detail"],
        },
        *(
            {"subject": s["name"], "kind": s["kind"], "id": s["id"]}
            for s in data["subject_entities"][:_SUBJECTS]
        ),
        *({"evidence": {key: value}} for key, value in data["evidence"].items() if key != "items"),
    ]


async def get_run_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    run_id = uuid_arg(args, "run_id")
    async with sessions() as session:
        # ponytail: the summary only. The packets (`run_store.load`, an artifact of up to 8 MiB
        # read through the artifact store) cannot fit the cap; add a digest of them when a
        # question needs one.
        summary = run_store.summary(await run_store.record(session, project_id, run_id))
    return [summary.model_dump(mode="json")]


_ENVELOPES: Final = default_orchestration_config().envelopes
_NO_ENVELOPE: Final = (
    "no envelope: no limits, definition, scene joint, expected value or baseline for this part"
)
_ENVELOPE_PARAMS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "part_id": {"type": "string", "format": "uuid", "description": "The part's UUID."},
        "quantity": {
            "type": "string",
            "enum": list(QUANTITIES),
            "description": "Which quantity of the part: the stem of its limit keys.",
        },
    },
    "required": ["part_id", "quantity"],
    "additionalProperties": False,
}


def _quantity_arg(args: dict[str, Any]) -> str:
    """The quantity the model asked for; the schema checks it, this is the second lock."""
    quantity = args.get("quantity")
    if not isinstance(quantity, str) or quantity not in QUANTITIES:
        raise ToolException(
            f"quantity must be one of {', '.join(QUANTITIES)}", code=ToolErrorCode.INVALID_ARGS
        )
    return quantity


async def get_envelope_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    part_id = uuid_arg(args, "part_id")
    quantity = _quantity_arg(args)
    async with sessions() as session:
        found = await part_envelopes(session, project_id, [part_id], envelopes=_ENVELOPES)
    if part_id not in found:  # absent, another project's, or no part: one answer
        raise APIError(404, "not_found", "Part not found")
    told = [envelope_line(e) for e in found[part_id] if e.quantity == quantity]
    return told[0] if told else _NO_ENVELOPE


def register_finding_tools(
    registry: ToolRegistry, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> None:
    """Add `get_finding`, `get_run` and `get_envelope`, all bound to ONE project."""
    registry.register(
        bounded_read_tool(
            "get_finding",
            "Read one finding in this project by id: its headline, severity, status, rule, the "
            "entities it blames (subjects) and its newest evidence.",
            uuid_params("finding_id", "The finding's UUID."),
            partial(get_finding_handler, sessions=sessions, project_id=project_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "get_run",
            "Read the recorded summary of one bench run in this project by id: its robot, origin, "
            "status, times, packet and drop counts and whether it is its robot's baseline run "
            "(baseline), not the packets. The status is as last recorded; a run whose server "
            "stopped mid-capture can still read running.",
            uuid_params("run_id", "The run's UUID."),
            partial(get_run_handler, sessions=sessions, project_id=project_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "get_envelope",
            "Read the operating envelope of ONE quantity of a part in this project by id: its "
            "nominal, warn and limit bounds in one unit and where each came from (the part's "
            "config limits, its library definition, a scene joint, a simulation's expected "
            "value), or that nothing states any. A baseline run's learned bounds are not read "
            "here.",
            _ENVELOPE_PARAMS,
            partial(get_envelope_handler, sessions=sessions, project_id=project_id),
        )
    )
