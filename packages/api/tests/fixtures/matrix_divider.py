"""SOLUSDEV-321 P3-T4 — the divider project, the netlist half of the P3 acceptance.

`kicad_divider_adc.net` is synced through the schematic connector's real mapping
(`build_graph` + `apply_sync_result`). It holds an R–R divider (R1 from the battery, R2 to ground)
into U1's ADC0 pin at /VSENSE, with C1 to ground there, beside C2 decoupling U1's +3V3 rail.

The firmware that samples the divider comes with it:

- a code entity stating its `loop_rate_hz`;
- the CONFIRMED `reads` edge into the divider's ADC net, onto its bottom leg R2, as a person
  accepts it in the hardware review.

That gives `sample_rate_vs_adc_settling` its inputs: R1‖R2 = 50 kΩ into C1 = 100 nF, so
τ = 5 ms and the input settles in 25 ms. Nothing here is a real part: the MCU is labelled fake.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from solus_api.connectors.contracts import SyncResult
from solus_api.connectors.eda import NET_KEY_PREFIX, build_graph
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.runtime import apply_sync_result
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.models import (
    Domain,
    GraphEntity,
    Membership,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

NET_PATH: Final = Path(__file__).parent / "kicad_divider_adc.net"
CODE_PATH: Final = "fw/divider.ino"
#: The pin the firmware's analog read names (the bottom leg's net is the ADC input).
READ_PIN: Final = "A0"


@dataclass(frozen=True)
class DividerProject:
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    source_id: uuid.UUID
    code: uuid.UUID
    #: designator → component id, and net name → net id.
    parts: dict[str, uuid.UUID]
    nets: dict[str, uuid.UUID]


async def seed_divider(db: AsyncSession, *, loop_rate_hz: float | None = 100.0) -> DividerProject:
    """A fresh project holding the divider netlist and the firmware sampling it. With
    `loop_rate_hz=None` the code states no rate. Commits."""
    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@divider.example")
    team = Team(name=f"divider-{tag}")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=f"divider-{tag}", created_by=user.id)
    db.add(project)
    await db.flush()
    source = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.KICAD,
        name="divider",
        status=SourceStatus.CONNECTED,
        config={},
    )
    db.add(source)
    await db.flush()
    entities, relations, errors = build_graph(parse_kicad_netlist(NET_PATH.read_text()))
    assert errors == [], errors
    await apply_sync_result(db, source, SyncResult(entities=entities, relations=relations))
    rows = {
        row.external_ref: row
        for row in await db.scalars(select(GraphEntity).where(GraphEntity.source_id == source.id))
        if row.external_ref
    }
    code = GraphEntity(
        project_id=project.id,
        kind=kinds.CODE_FILE,
        domain=Domain.CODE,
        origin="manual",
        name=CODE_PATH,
        attrs={"loop_rate_hz": loop_rate_hz} if loop_rate_hz is not None else {},
    )
    db.add(code)
    await db.flush()
    await write_edge(
        db,
        project_id=project.id,
        src_id=code.id,
        dst_id=rows["R2"].id,
        relation_type=RelationType.READS.value,
        origin=EdgeOrigin.MANUAL.value,
        confidence=1.0,
        evidence=[EdgeEvidence(kind=EvidenceKind.USER_CONFIRMED, ref=str(user.id))],
        created_by=user.id,
        attrs={"pin": READ_PIN},
    )
    await db.commit()
    return DividerProject(
        project_id=project.id,
        team_id=team.id,
        user_id=user.id,
        source_id=source.id,
        code=code.id,
        parts={key: row.id for key, row in rows.items() if row.kind == kinds.COMPONENT},
        nets={
            key.removeprefix(NET_KEY_PREFIX): row.id
            for key, row in rows.items()
            if row.kind == kinds.NET
        },
    )
