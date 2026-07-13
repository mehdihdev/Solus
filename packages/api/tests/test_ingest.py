"""FP-02 fingerprint ingestion: canonical entities, precision at persistence (SOLUSDEV-59).

The graph is a system of record — it records what we BELIEVE, not what we
SUSPECT. These tests pin: constraint-based idempotency (unique index, never
check-then-insert), only-MATCHED-asserts, union-with-update evidence merge,
clear+stamp stale-assertion ownership, keyless-safe embedding, and hard
cross-tenant isolation of canonical entities.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from solus_api.fingerprint import (
    AmbiguousObservation,
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
    canonical_uuid,
)
from solus_api.fingerprint.ingest import ingest, ingest_output, resolve, scan_project
from solus_api.fingerprint.matcher import Observation
from solus_api.models import Domain, GraphEntity, Project, Team, utcnow
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Mirrors conftest (importing conftest trips single-file mypy runs): the session
# _schema fixture exports SOLUS_DATABASE_URL before any test executes.
API_DIR = Path(__file__).resolve().parent.parent


def _test_db_url() -> str:
    return str(os.environ["SOLUS_DATABASE_URL"])


# --- Helpers -----------------------------------------------------------------------


async def _project(db: AsyncSession, suffix: str) -> Project:
    team = Team(name=f"T-{suffix}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"P-{suffix}")
    db.add(project)
    await db.flush()
    return project


async def _obs(
    db: AsyncSession,
    project: Project,
    *,
    external_ref: str,
    hints: dict[str, Any],
    connector: str = "altium",
    attrs: dict[str, Any] | None = None,
) -> GraphEntity:
    row = GraphEntity(
        project_id=project.id,
        source_connector=connector,
        external_ref=external_ref,
        origin="connector",
        kind="component",
        domain=Domain.ELECTRICAL,
        name=external_ref,
        attrs=attrs or {},
        modality_hints=hints,
    )
    db.add(row)
    await db.flush()
    return row


def _ref(
    external_ref: str, connector: str = "altium", entity_id: uuid.UUID | None = None
) -> SourceRef:
    return SourceRef(
        graph_entity_id=entity_id, source_connector=connector, external_ref=external_ref
    )


def _mm(
    ref: SourceRef,
    *,
    modality: Modality = Modality.PART_NUMBER,
    state: MatchState = MatchState.MATCHED,
    confidence: float = 0.95,
    evidence: dict[str, Any] | None = None,
) -> ModalityMatch:
    return ModalityMatch(
        modality=modality,
        source_ref=ref,
        confidence=confidence,
        state=state,
        evidence=evidence or {"matched_on": "part_number", "value": "LM358"},
    )


def _part(
    base: str = "LM358",
    modalities: tuple[ModalityMatch, ...] = (),
    *,
    confidence: float = 0.97,
    manufacturer: str | None = None,
    datasheet_ref: str | None = None,
) -> CanonicalPart:
    return CanonicalPart(
        canonical_id=canonical_uuid(base),
        part_number=base,
        manufacturer=manufacturer,
        datasheet_ref=datasheet_ref,
        modalities=list(modalities),
        confidence=confidence,
    )


async def _fake_embed(text: str) -> list[float] | None:
    return [0.5] * 1536


async def _live_canonicals(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEntity]:
    return list(
        await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == "canonical_part",
                GraphEntity.deleted_at.is_(None),
            )
        )
    )


# --- Schema: the partial unique index (verify 1 substrate, 6) ------------------------


async def test_canonical_key_partial_unique_index(db: AsyncSession) -> None:
    project_a = await _project(db, "idx-a")
    project_b = await _project(db, "idx-b")

    def row(project_id: uuid.UUID) -> GraphEntity:
        return GraphEntity(
            project_id=project_id,
            kind="canonical_part",
            domain=Domain.ELECTRICAL,
            name="LM358",
            canonical_key="LM358",
            origin="fingerprint",
        )

    first = row(project_a.id)
    db.add(first)
    await db.flush()
    db.add(row(project_a.id))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()

    # Post-rollback: recreate in fresh state; soft-deleted rows don't collide,
    # and the same key in another project is fine.
    project_a = await _project(db, "idx-a2")
    project_b = await _project(db, "idx-b2")
    first = row(project_a.id)
    first.deleted_at = utcnow()
    db.add(first)
    db.add(row(project_a.id))
    db.add(row(project_b.id))
    await db.flush()


# --- ingest(): create + idempotency (verify 1) ---------------------------------------


async def test_ingest_creates_canonical_row(db: AsyncSession) -> None:
    project = await _project(db, "create")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    part = _part("LM358", (_mm(_ref("U1", entity_id=obs.id)),))

    result = await ingest(db, part, project_id=project.id)

    row = result.row
    assert row is not None and result.created
    assert row.kind == "canonical_part"
    assert row.origin == "fingerprint"
    assert row.source_id is None and row.external_ref is None
    assert row.canonical_key == "LM358"
    assert row.name == "LM358"
    assert row.domain is Domain.ELECTRICAL
    fingerprint = row.attrs["fingerprint"]
    assert fingerprint["canonical_id"] == str(canonical_uuid("LM358"))
    assert fingerprint["confidence"] == 0.97
    assert len(fingerprint["modalities"]) == 1


async def test_ingest_twice_same_part_one_row(db: AsyncSession) -> None:
    project = await _project(db, "twice")
    part = _part("LM358", (_mm(_ref("U1")),))
    first = await ingest(db, part, project_id=project.id)
    second = await ingest(db, part, project_id=project.id)
    assert first.row is not None and second.row is not None
    assert first.row.id == second.row.id
    assert not second.created
    assert len(await _live_canonicals(db, project.id)) == 1


async def test_ingest_concurrent_same_part_is_race_safe(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Constraint-based idempotency, not check-then-write: two CONCURRENT ingests
    of one CanonicalPart on separate sessions -> exactly one live canonical row,
    both callers get the same id (the loser re-selects the winner's row)."""
    project = await _project(db, "race")
    await db.commit()  # racing sessions must see the FK target
    project_id = project.id
    part = _part("LM358", (_mm(_ref("bom:1")), _mm(_ref("sch:U1"))))
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> uuid.UUID:
        async with maker() as session:
            result = await ingest(session, part, project_id=project_id)
            await session.commit()
            assert result.row is not None
            return result.row.id

    first, second = await asyncio.gather(attempt(), attempt())
    assert first == second
    rows = await _live_canonicals(db, project_id)
    assert len(rows) == 1 and rows[0].id == first


async def test_oversized_key_skipped_never_truncated(db: AsyncSession) -> None:
    project = await _project(db, "oversize")
    part = _part("X1" + "A" * 70, (_mm(_ref("U1")),))
    result = await ingest(db, part, project_id=project.id)
    assert result.row is None
    assert await _live_canonicals(db, project.id) == []


# --- Precision at persistence (verify 2) ---------------------------------------------


async def test_matched_sets_canonical_fk_and_stamp(db: AsyncSession) -> None:
    project = await _project(db, "matched")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    part = _part("LM358", (_mm(_ref("U1", entity_id=obs.id)),))

    result = await ingest(db, part, project_id=project.id)

    assert result.row is not None and result.linked == 1
    await db.refresh(obs)
    assert obs.canonical_part_id == result.row.id
    assert obs.attrs["fingerprint_link"]["canonical_key"] == "LM358"
    assert obs.version == 2  # FK write is a real change


async def test_low_confidence_no_fk_recorded_as_candidate(db: AsyncSession) -> None:
    project = await _project(db, "lowconf")
    matched = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    shaky = await _obs(db, project, external_ref="U1d", hints={"datasheet": "lm358.pdf"})
    part = _part(
        "LM358",
        (
            _mm(_ref("U1", entity_id=matched.id)),
            _mm(
                _ref("U1d", entity_id=shaky.id),
                modality=Modality.DATASHEET,
                state=MatchState.LOW_CONFIDENCE,
                confidence=0.55,
            ),
        ),
    )

    result = await ingest(db, part, project_id=project.id)

    assert result.row is not None
    await db.refresh(shaky)
    assert shaky.canonical_part_id is None
    assert "fingerprint_link" not in shaky.attrs
    entries = result.row.attrs["fingerprint"]["modalities"]
    states = {entry["state"] for entry in entries.values()}
    assert states == {"matched", "low_confidence"}


async def test_ambiguous_no_fk_candidate_on_each_canonical(db: AsyncSession) -> None:
    project = await _project(db, "ambig")
    ambiguous_obs = await _obs(
        db, project, external_ref="U60", hints={"schematic_symbol": "LM358_LM2904"}
    )
    output = FingerprintOutput(
        canonical_parts=[
            _part("LM358", (_mm(_ref("U1")),)),
            _part("LM2904", (_mm(_ref("U2")),)),
        ],
        unmatched=[],
        ambiguous=[
            AmbiguousObservation(
                source_ref=_ref("U60", entity_id=ambiguous_obs.id),
                candidate_canonical_ids=[canonical_uuid("LM358"), canonical_uuid("LM2904")],
                note="symbol names: LM2904, LM358",
            )
        ],
    )

    await ingest_output(db, output, project_id=project.id)

    await db.refresh(ambiguous_obs)
    assert ambiguous_obs.canonical_part_id is None
    for row in await _live_canonicals(db, project.id):
        ambiguous_map = row.attrs["fingerprint"]["ambiguous"]
        assert any(e["note"] == "symbol names: LM2904, LM358" for e in ambiguous_map.values())


# --- Evidence merge (verify 3) --------------------------------------------------------


async def test_reingest_updates_one_source_preserves_others(db: AsyncSession) -> None:
    """The clobber case: a re-sync of one source must not erase another's evidence."""
    project = await _project(db, "merge")
    ref_a = _ref("U1", connector="altium")
    ref_b = _ref("repo/f.step", connector="github")
    both = _part(
        "LM358",
        (
            _mm(ref_a, evidence={"matched_on": "part_number", "value": "LM358"}),
            _mm(ref_b, modality=Modality.CAD_MODEL, evidence={"matched_on": "cad", "v": 1}),
        ),
    )
    first = await ingest(db, both, project_id=project.id)

    only_a_updated = _part(
        "LM358",
        (_mm(ref_a, evidence={"matched_on": "part_number", "value": "LM358N", "package": "N"}),),
    )
    second = await ingest(db, only_a_updated, project_id=project.id)

    assert first.row is not None and second.row is not None
    entries = second.row.attrs["fingerprint"]["modalities"]
    assert entries["part_number:altium:U1"]["evidence"]["value"] == "LM358N"  # updated
    assert entries["cad_model:github:repo/f.step"]["evidence"] == {"matched_on": "cad", "v": 1}


async def test_version_bumps_only_on_real_change(db: AsyncSession) -> None:
    project = await _project(db, "version")
    part = _part("LM358", (_mm(_ref("U1")),))
    first = await ingest(db, part, project_id=project.id)
    assert first.row is not None
    version_after_create = first.row.version

    await ingest(db, part, project_id=project.id)  # identical → no-op
    assert first.row.version == version_after_create

    changed = _part("LM358", (_mm(_ref("U1"), confidence=0.9),))
    await ingest(db, changed, project_id=project.id)
    assert first.row.version == version_after_create + 1


# --- Keyless / embedder seam (verify 4) ------------------------------------------------


async def test_scan_without_embedder_embedding_null(db: AsyncSession) -> None:
    project = await _project(db, "keyless")
    await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    summary = await scan_project(db, project.id)
    assert summary.canonical_created == 1 and summary.embedded == 0
    (row,) = await _live_canonicals(db, project.id)
    assert row.embedding is None


async def test_scan_with_embedder_writes_embedding_same_links(db: AsyncSession) -> None:
    project_plain = await _project(db, "emb-plain")
    project_embed = await _project(db, "emb-on")
    for project in (project_plain, project_embed):
        await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
        await _obs(db, project, external_ref="U2", hints={"part_number": "LM358DR"})

    plain = await scan_project(db, project_plain.id)
    embedded = await scan_project(db, project_embed.id, embed=_fake_embed)

    assert embedded.embedded == 1
    (row_embed,) = await _live_canonicals(db, project_embed.id)
    assert row_embed.embedding is not None
    (row_plain,) = await _live_canonicals(db, project_plain.id)
    assert row_plain.embedding is None
    # Embedding presence never changes match outcomes.
    assert (plain.canonical_created, plain.linked) == (
        embedded.canonical_created,
        embedded.linked,
    )
    assert row_plain.canonical_key == row_embed.canonical_key


async def test_embedder_raising_is_best_effort(db: AsyncSession) -> None:
    async def broken(text: str) -> list[float] | None:
        raise RuntimeError("no provider")

    project = await _project(db, "emb-broken")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    summary = await scan_project(db, project.id, embed=broken)
    assert summary.canonical_created == 1 and summary.embedded == 0
    (row,) = await _live_canonicals(db, project.id)
    assert row.embedding is None
    await db.refresh(obs)
    assert obs.canonical_part_id == row.id  # links unaffected by embed failure


# --- Integration acceptance (verify 5) --------------------------------------------------


async def test_scan_multimodal_resolves_to_one_canonical(db: AsyncSession) -> None:
    """The mock-swap proof: a part seen across netlist + BOM + schematic collapses
    to ONE canonical entity, resolvable from every observation by either ref style."""
    project = await _project(db, "e2e")
    netlist = await _obs(
        db, project, external_ref="U1", hints={"part_number": "LM358"}, connector="protel"
    )
    bom = await _obs(db, project, external_ref="bom:3", hints={"part_number": "LM358DR"})
    await _obs(
        db,
        project,
        external_ref="sch:U1",
        hints={"schematic_symbol": "Amplifier_Operational:LM358"},
    )

    summary = await scan_project(db, project.id)

    assert summary.canonical_created == 1
    assert summary.linked == 3
    (canonical,) = await _live_canonicals(db, project.id)
    by_id = await resolve(db, SourceRef(graph_entity_id=netlist.id), project_id=project.id)
    by_pair = await resolve(db, _ref("bom:3"), project_id=project.id)
    by_pair_symbol = await resolve(db, _ref("sch:U1"), project_id=project.id)
    assert by_id is not None and by_pair is not None and by_pair_symbol is not None
    resolved = {by_id.id, by_pair.id, by_pair_symbol.id}
    assert resolved == {canonical.id}
    assert {m for m in canonical.attrs["fingerprint"]["modalities"]} >= {
        "part_number:protel:U1",
        "part_number:altium:bom:3",
        "schematic_symbol:altium:sch:U1",
    }
    await db.refresh(bom)
    assert bom.canonical_part_id == canonical.id


# --- Isolation (verify 6) ----------------------------------------------------------------


async def test_same_part_two_projects_two_canonicals(db: AsyncSession) -> None:
    project_a = await _project(db, "iso-a")
    project_b = await _project(db, "iso-b")
    part = _part("LM358", (_mm(_ref("U1")),))
    result_a = await ingest(db, part, project_id=project_a.id)
    result_b = await ingest(db, part, project_id=project_b.id)
    assert result_a.row is not None and result_b.row is not None
    assert result_a.row.id != result_b.row.id
    assert result_a.row.canonical_key == result_b.row.canonical_key == "LM358"


async def test_resolve_and_ingest_are_project_scoped(db: AsyncSession) -> None:
    """Cross-tenant guard: a SourceRef leaking another project's entity id must
    neither link nor resolve."""
    project_a = await _project(db, "tenant-a")
    project_b = await _project(db, "tenant-b")
    foreign = await _obs(db, project_b, external_ref="U1", hints={"part_number": "LM358"})

    part = _part("LM358", (_mm(_ref("U1", entity_id=foreign.id)),))
    result = await ingest(db, part, project_id=project_a.id)

    assert result.row is not None and result.linked == 0 and result.unresolved == 1
    await db.refresh(foreign)
    assert foreign.canonical_part_id is None  # never a cross-tenant FK

    assert await resolve(db, SourceRef(graph_entity_id=foreign.id), project_id=project_a.id) is None
    assert await resolve(db, _ref("U1"), project_id=project_a.id) is None


# --- Edges ---------------------------------------------------------------------------------


async def test_reingest_after_soft_delete_creates_fresh_live_row(db: AsyncSession) -> None:
    project = await _project(db, "tombstone")
    part = _part("LM358", (_mm(_ref("U1")),))
    first = await ingest(db, part, project_id=project.id)
    assert first.row is not None
    first.row.deleted_at = utcnow()
    await db.flush()

    second = await ingest(db, part, project_id=project.id)
    assert second.row is not None and second.created
    assert second.row.id != first.row.id
    live = await _live_canonicals(db, project.id)
    assert [r.id for r in live] == [second.row.id]
    assert first.row.deleted_at is not None  # tombstone intact for audit


async def test_dangling_source_ref_skipped_gracefully(db: AsyncSession) -> None:
    project = await _project(db, "dangling")
    part = _part("LM358", (_mm(_ref("nowhere:U9")),))
    result = await ingest(db, part, project_id=project.id)
    assert result.row is not None  # canonical still created
    assert result.linked == 0 and result.unresolved == 1


async def test_unmatched_untouched_and_empty_output_noop(db: AsyncSession) -> None:
    project = await _project(db, "noop")
    stray = await _obs(db, project, external_ref="U9", hints={"part_number": "TBD"})
    version_before = stray.version

    empty = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
    summary = await ingest_output(db, empty, project_id=project.id)
    assert summary.canonical_created == 0

    with_unmatched = FingerprintOutput(
        canonical_parts=[], unmatched=[_ref("U9", entity_id=stray.id)], ambiguous=[]
    )
    summary = await ingest_output(db, with_unmatched, project_id=project.id)
    assert summary.unmatched == 1
    await db.refresh(stray)
    assert stray.canonical_part_id is None and stray.version == version_before
    assert "fingerprint_link" not in stray.attrs


async def test_scan_on_hintless_project_is_empty(db: AsyncSession) -> None:
    project = await _project(db, "hintless")
    await _obs(db, project, external_ref="U1", hints={})
    summary = await scan_project(db, project.id)
    assert summary.observations == 0 and summary.canonical_created == 0
    assert await _live_canonicals(db, project.id) == []


async def test_scan_marks_evidence_of_gone_observation_stale(db: AsyncSession) -> None:
    project = await _project(db, "stale-ev")
    await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    obs_b = await _obs(db, project, external_ref="U2", hints={"part_number": "LM358DR"})
    await scan_project(db, project.id)
    (canonical,) = await _live_canonicals(db, project.id)
    assert len(canonical.attrs["fingerprint"]["modalities"]) == 2

    obs_b.deleted_at = utcnow()
    await db.flush()
    await scan_project(db, project.id)

    await db.refresh(canonical)
    entries = canonical.attrs["fingerprint"]["modalities"]
    key_a = "part_number:altium:U1"
    key_b = "part_number:altium:U2"
    assert entries[key_a]["stale_at"] is None  # still live, refreshed
    assert entries[key_b]["stale_at"] is not None  # marked, not dropped
    assert entries[key_b]["evidence"]  # provenance survives


async def test_stale_assertion_cleared_with_stamp_ownership(db: AsyncSession) -> None:
    """Clear + stamp (human decision 2026-07-12): a fingerprint-made assertion the
    current evidence no longer supports is retracted; unstamped FKs are never touched."""
    project = await _project(db, "sweep")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    # Hint-less: never enters matching, so its manually-set FK below is a pure
    # human assertion the sweep must not touch.
    manual = await _obs(db, project, external_ref="U7", hints={})
    await scan_project(db, project.id)
    await db.refresh(obs)
    first_target = obs.canonical_part_id  # local: mypy can't see refresh() mutate
    assert first_target is not None  # fingerprint asserted + stamped

    # A human manually links `manual` to some canonical WITHOUT a stamp.
    (lm358_canonical,) = [
        r for r in await _live_canonicals(db, project.id) if r.canonical_key == "LM358"
    ]
    manual.canonical_part_id = lm358_canonical.id
    await db.flush()

    # The observation's hint degrades to garbage → no longer MATCHED anywhere.
    obs.modality_hints = {"part_number": "TBD"}
    await db.flush()
    summary = await scan_project(db, project.id)

    await db.refresh(obs)
    assert obs.canonical_part_id is None  # assertion retracted
    assert "fingerprint_link" not in obs.attrs  # stamp removed
    assert summary.cleared == 1
    await db.refresh(manual)
    assert manual.canonical_part_id == lm358_canonical.id  # unstamped → untouched


async def test_scan_reassignment_moves_fk_and_stamp(db: AsyncSession) -> None:
    project = await _project(db, "reassign")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    await scan_project(db, project.id)
    await db.refresh(obs)
    old_target = obs.canonical_part_id

    obs.modality_hints = {"part_number": "TL072"}
    await db.flush()
    summary = await scan_project(db, project.id)

    await db.refresh(obs)
    assert obs.canonical_part_id is not None and obs.canonical_part_id != old_target
    assert obs.attrs["fingerprint_link"]["canonical_key"] == "TL072"
    # The abandoned LM358 canonical lost all support: its evidence is stale-marked.
    assert summary.canonical_staled == 1


async def test_manual_unstamped_fk_survives_matcher_disagreement(db: AsyncSession) -> None:
    """The SET side of CLEAR+STAMP: an unstamped (human/LNK-01) assertion is
    never overwritten, even when the matcher disagrees — a human correction of
    a false merge must not be reverted on every scan."""
    project = await _project(db, "human-fix")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    other = GraphEntity(
        project_id=project.id,
        kind="canonical_part",
        domain=Domain.ELECTRICAL,
        name="LM2904",
        canonical_key="LM2904",
        origin="fingerprint",
    )
    db.add(other)
    await db.flush()
    # Human corrects the link to LM2904 WITHOUT a stamp.
    obs.canonical_part_id = other.id
    await db.flush()

    summary = await scan_project(db, project.id)  # matcher still says LM358

    await db.refresh(obs)
    assert obs.canonical_part_id == other.id  # human assertion survives
    assert "fingerprint_link" not in obs.attrs
    assert summary.skipped_unstamped == 1
    assert summary.cleared == 0


async def test_orphaned_canonical_evidence_marked_stale(db: AsyncSession) -> None:
    """A canonical that loses ALL support is not silently left asserting
    fresh-looking MATCHED evidence: the orphan sweep stale-marks it."""
    project = await _project(db, "orphan")
    obs = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    await scan_project(db, project.id)
    (canonical,) = await _live_canonicals(db, project.id)
    version_before = canonical.version

    obs.modality_hints = {"part_number": "TBD"}  # no longer matches anything
    await db.flush()
    summary = await scan_project(db, project.id)

    assert summary.canonical_staled == 1 and summary.cleared == 1
    await db.refresh(canonical)
    assert canonical.version == version_before + 1
    entries = canonical.attrs["fingerprint"]["modalities"]
    assert all(entry["stale_at"] is not None for entry in entries.values())
    assert all(entry["evidence"] for entry in entries.values())  # marked, never dropped


async def test_concurrent_scans_serialize_per_project(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Two concurrent scan_project runs serialize on the per-project advisory
    lock: no deadlock, no clobbered assertion, one canonical row."""
    project = await _project(db, "scan-race")
    await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    await db.commit()
    project_id = project.id
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> int:
        async with maker() as session:
            summary = await scan_project(session, project_id)
            await session.commit()
            return summary.cleared

    cleared_counts = await asyncio.gather(attempt(), attempt())
    assert list(cleared_counts) == [0, 0]  # neither run retracted the other's assertion
    rows = await _live_canonicals(db, project_id)
    assert len(rows) == 1
    linked = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.canonical_part_id == rows[0].id,
        )
    )
    assert linked is not None  # the observation link survived both runs


# --- Migration reversibility (verify 7) — sync on purpose: env.py calls asyncio.run ------


def _column_exists() -> bool:
    async def check() -> bool:
        conn = await asyncpg.connect(_test_db_url().replace("+asyncpg", ""))
        try:
            found = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'graph_entity' AND column_name = 'canonical_key'"
            )
            return bool(found)
        finally:
            await conn.close()

    return asyncio.run(check())


def _index_exists() -> bool:
    async def check() -> bool:
        conn = await asyncpg.connect(_test_db_url().replace("+asyncpg", ""))
        try:
            found = await conn.fetchval(
                "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_graph_entity_project_canonical_key'"
            )
            return bool(found)
        finally:
            await conn.close()

    return asyncio.run(check())


def test_migration_downgrade_and_reupgrade() -> None:
    """The FP-02 migration reverses cleanly and reapplies. Restores head in
    finally so a mid-test failure cannot poison the rest of the session."""
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    try:
        # Explicit pre-FP-02 target (not "-1"): stays correct when later
        # migrations land on top — everything above it must reverse cleanly.
        command.downgrade(cfg, "8d4f2a91c6e3")
        assert not _column_exists()
        assert not _index_exists()
    finally:
        command.upgrade(cfg, "head")
    assert _column_exists()
    assert _index_exists()


async def test_photo_evidence_never_sets_the_graph_fk(db: AsyncSession) -> None:
    """FP-03 end-to-end containment: a photo-corroborated part carries the photo
    as LOW_CONFIDENCE candidate evidence in canonical attrs, and the photo's
    observation row NEVER gets canonical_part_id — the graph makes no assertion
    from a photo."""
    from solus_api.fingerprint import MarkingCandidate, match, photo_observations

    project = await _project(db, "photo")
    pn_row = await _obs(db, project, external_ref="U1", hints={"part_number": "LM358"})
    photo_row = await _obs(db, project, external_ref="assets/board.jpg", hints={})

    pn_obs = Observation(
        source_ref=SourceRef(
            graph_entity_id=pn_row.id, source_connector="altium", external_ref="U1"
        ),
        modality=Modality.PART_NUMBER,
        value="LM358",
    )
    photo_obs = photo_observations(
        SourceRef(
            graph_entity_id=photo_row.id,
            source_connector="altium",
            external_ref="assets/board.jpg",
        ),
        [MarkingCandidate(text="LM358", confidence=0.9)],
    )
    output = match([pn_obs, *photo_obs])
    summary = await ingest_output(db, output, project_id=project.id)

    assert summary.low_confidence == 1
    await db.refresh(pn_row)
    await db.refresh(photo_row)
    (canonical,) = await _live_canonicals(db, project.id)
    assert pn_row.canonical_part_id == canonical.id  # structured assertion stands
    assert photo_row.canonical_part_id is None  # NO assertion from a photo
    assert "fingerprint_link" not in photo_row.attrs
    entries = canonical.attrs["fingerprint"]["modalities"]
    photo_entry = entries["photo:altium:assets/board.jpg"]
    assert photo_entry["state"] == "low_confidence"
    assert photo_entry["evidence"]["readings"] == ["LM358"]
