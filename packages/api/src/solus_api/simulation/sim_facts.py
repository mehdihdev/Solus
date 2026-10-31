"""SOLUSDEV-321 P4-T1 — the facts a simulation run leaves in the graph (docs/api/simulation.md §3).

`record_sim_result` is the one writer of `sim_result` entities, of their `verified_by` edges and
of `attrs.expected`. One run leaves three things:

- one `sim_result` entity (kind `sim_result`, domain `simulation`, origin `system`) holding the
  subject, the rung, the values and the whole provenance. It is constructed here, the way
  `raise_finding` constructs a finding: `graph/` has no entity writer;
- a `verified_by` edge from the subject to it, written through `write_edge` with `sim`
  evidence;
- for each computed quantity, `attrs.expected[quantity] = {value, unit, sim_result_id}` on the
  subject. This is reassigned, never mutated, over the quantities the subject already holds.
  The envelopes (`bounds_source = "sim"`) and the matrix's `FactStore.expected` read it.

It owns its transaction, in this order:
1. The JSON it will persist is validated, and that JSON is what it writes. A result without its
   full provenance raises and writes nothing, even one assembled from `model_construct` shells.
2. `lock_project`.
3. The subject is read fresh under a row lock it never waits for. Under the project lock,
   waiting could deadlock with a sync, which locks entity rows first (R68).
4. The writes, then the commit.
5. After the commit, in its own guard (the way a sync does), a published `graph.changed`. The
   envelope cache, keyed by config version, would not notice the new expected value otherwise
   (M69).

Ceiling (M126): a connector-owned subject's next sync rewrites its attrs whole and drops
`attrs.expected`. The `sim_result` and its edge survive.

`run_and_record` (P4-T3) is the one shape of the rung-3 ARQ jobs (§7). Their results are never
kept by the queue (`keep_result=0`), so a job records its own run through `record_sim_result`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator
from pydantic_core import PydanticSerializationError
from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.live import graph_changed_frame
from solus_api.models import Domain, GraphEntity, utcnow
from solus_api.orchestration.config import SimRung
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_graph import lock_project
from solus_api.simulation.sim_capability import (
    SimInput,
    SimProvider,
    SimResult,
    SimulationFailedError,
    SimulationRefusedError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.graph.live import LiveHub

logger = logging.getLogger("solus.simulation.sim_facts")

ORIGIN: Final = EdgeOrigin.SYSTEM.value
#: What one recorded run changes: its own entity, the subject's attrs and one `verified_by` edge.
CHANGED: Final = GraphChangeCounts(entities_created=1, entities_updated=1, relations_created=1)
#: The rungs a run may record: the ones the config names (1-4).
_RUNG: Final = TypeAdapter(SimRung)
#: The facts one rung-3 job request may carry, as JSON.
MAX_JOB_FACTS_BYTES: Final = 1024 * 1024


async def record_sim_result(
    sessions: async_sessionmaker[AsyncSession],
    hub: LiveHub,
    *,
    project_id: UUID,
    subject_id: UUID,
    rung: int,
    result: SimResult,
    created_by: UUID | None,
) -> UUID:
    """Record one run (module docstring) and return its `sim_result` id. Each of these raises
    before anything is written:
    - pydantic's `ValidationError`, for a result without its full provenance, or for a rung the
      config does not name (1-4: P4-T5 reads it back as the band's `rung`);
    - `APIError` 404, for a subject that is not live in the project;
    - `APIError` 409, retryable, for a subject another transaction holds.

    It validates the result's own JSON, which is what `_write` persists, so no instance at any
    depth is taken on trust."""
    _RUNG.validate_python(rung)
    try:
        dumped: object = result.model_dump(mode="json")
    except PydanticSerializationError:  # M127: a malformed constructed result
        dumped = None  # refused just below, as the ValidationError this writer documents
    checked = SimResult.model_validate(dumped)
    async with sessions() as session:
        await lock_project(session, project_id)
        subject = await _subject(session, project_id, subject_id)
        sim_id = await _write(session, subject, rung, checked, created_by)
        await session.commit()
    logger.info(
        "sim result recorded project=%s subject=%s rung=%d sim_result=%s",
        project_id,
        subject_id,
        rung,
        sim_id,
    )
    await _publish(hub, project_id)
    return sim_id


async def _subject(session: AsyncSession, project_id: UUID, subject_id: UUID) -> GraphEntity:
    """The subject, read under a row lock that is never waited for. `SKIP LOCKED` reads a held row
    as absent, so a second, unlocked read tells a held row from a missing one, as `annotate_edge`
    does."""
    live = select(GraphEntity).where(
        GraphEntity.id == subject_id,
        GraphEntity.project_id == project_id,
        GraphEntity.deleted_at.is_(None),
    )
    row = await session.scalar(live.with_for_update(skip_locked=True))
    if row is not None:
        return row
    if await session.scalar(live) is not None:
        raise APIError(409, "conflict", "The simulation subject is being written; record it again")
    raise APIError(404, "not_found", "Simulation subject not found in this project")


async def _write(
    session: AsyncSession,
    subject: GraphEntity,
    rung: int,
    result: SimResult,
    created_by: UUID | None,
) -> UUID:
    """The `sim_result` row, its `verified_by` edge and the subject's expected values, flushed."""
    row = GraphEntity(
        project_id=subject.project_id,
        kind=kinds.SIM_RESULT,
        domain=Domain.SIMULATION,
        origin=ORIGIN,
        name=f"{', '.join(sorted(result.values))} — {subject.name}"[:512],
        attrs={
            "subject_id": str(subject.id),
            "rung": rung,
            **result.model_dump(mode="json"),
            "created_by": str(created_by) if created_by else None,
        },
    )
    session.add(row)
    await session.flush()
    await write_edge(
        session,
        project_id=subject.project_id,
        src_id=subject.id,
        dst_id=row.id,
        relation_type=RelationType.VERIFIED_BY.value,
        origin=ORIGIN,
        confidence=1.0,
        evidence=[
            EdgeEvidence(kind=EvidenceKind.SIM, ref=str(row.id), detail=result.provenance.solver)
        ],
        created_by=created_by,
    )
    held = subject.attrs.get("expected")
    expected = {
        **(held if isinstance(held, dict) else {}),
        **{
            quantity: {"value": found.value, "unit": found.unit, "sim_result_id": str(row.id)}
            for quantity, found in result.values.items()
        },
    }
    subject.attrs = {**subject.attrs, "expected": expected}
    subject.version += 1
    await session.flush()
    return row.id


async def _publish(hub: LiveHub, project_id: UUID) -> None:
    """`graph.changed` for the project, after the commit and in its own guard: a failed fan-out
    never undoes a recorded run (`connectors/runtime.py` guards a sync's publish the same way)."""
    frame = graph_changed_frame(
        project_id=project_id,
        source_id=None,
        sync_id=None,
        counts=CHANGED,
        at=utcnow().isoformat(),
    )
    try:
        await hub.publish(project_id, frame)
    except Exception:  # noqa: BLE001 — the run is committed; fan-out is never worth a lie about it
        logger.exception("graph fan-out failed project=%s (the sim result stands)", project_id)


class SimJobRequest(BaseModel):
    """What a rung-3 job is handed: whose question it is, and the facts its provider reads. The
    enqueuer (P4-T4's tool) derives the ids from the turn's own scope, never from the facts. The
    facts are bounded at `MAX_JOB_FACTS_BYTES` as JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    subject_id: UUID
    requested_by: UUID | None = None
    facts: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(json.dumps(self.facts)) > MAX_JOB_FACTS_BYTES:
            raise ValueError(f"a job's facts exceed {MAX_JOB_FACTS_BYTES} bytes as JSON")
        return self


class RunnableProvider(SimProvider, Protocol):
    """A provider a job runs. It says whether it is available on this machine, and which of a
    subject's facts it reads."""

    @property
    def available(self) -> bool: ...

    def inputs_for(self, facts: Mapping[str, Any]) -> dict[str, SimInput]: ...


async def run_and_record(
    ctx: Mapping[str, Any], provider: RunnableProvider, raw: object
) -> dict[str, JsonValue]:
    """One rung-3 job (docs/api/simulation.md §7), in order:

    1. validate the request: a malformed one is the enqueuer's bug, and raises;
    2. check again that the provider is available, on the worker's own machine;
    3. run it off the event loop;
    4. record the result through `record_sim_result` (`ctx["sessionmaker"]`, `ctx["graph_hub"]`).

    It returns a status for an inline caller or a test, since the queue keeps nothing:
    `recorded` with the id, or `not_available`, `refused` or `failed` with a bounded reason. Every
    status but `recorded` is also a log line naming the provider, the project and the subject."""
    request = SimJobRequest.model_validate(raw)
    where = f"provider={provider.name} project={request.project_id} subject={request.subject_id}"
    if not provider.available:
        logger.warning("simulation not available %s", where)
        return {
            "status": "not_available",
            "reason": f"{provider.name} is not available on this machine",
        }
    try:
        result = await asyncio.to_thread(provider.run, provider.inputs_for(request.facts))
    except SimulationRefusedError as exc:
        logger.warning("simulation refused %s: %s", where, exc)
        return {"status": "refused", "reason": str(exc)}
    except SimulationFailedError as exc:
        logger.warning("simulation failed %s: %s", where, exc)
        return {"status": "failed", "reason": str(exc)}
    try:
        sim_id = await record_sim_result(
            ctx["sessionmaker"],
            ctx["graph_hub"],
            project_id=request.project_id,
            subject_id=request.subject_id,
            rung=provider.rung,
            result=result,
            created_by=request.requested_by,
        )
    except APIError as exc:
        logger.warning("simulation not recorded %s: %s", where, exc.code)
        return {"status": "failed", "reason": f"not recorded: {exc.code}"}
    return {"status": "recorded", "sim_result_id": str(sim_id)}
