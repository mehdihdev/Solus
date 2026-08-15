"""LNK-01 cross-domain linking: SAME_AS edges from the W0-06 fingerprint contract (SOLUSDEV-106).

The linker consumes `FingerprintOutput` (the mock today, FP-02's real output at
LNK-02) and materializes cross-domain identity as `graph_edge` rows. These tests
pin: pairwise same_as edges with honest confidence (never promote a maybe),
normalized direction, idempotent re-link, linker-owned retraction that never
touches connector or manual edges, ambiguity refusal, unresolved-ref tolerance,
and hard cross-project isolation.
"""

import uuid
from typing import Any

import pytest
from solus_api.fingerprint.contract import (
    CanonicalPart,
    FingerprintOutput,
    MatchState,
    Modality,
    ModalityMatch,
    SourceRef,
    load_mock_output,
)
from solus_api.linking import LinkResult, link, link_from_fingerprint, link_from_mock
from solus_api.linking.linker import LINK_ORIGIN, RELATION_SAME_AS
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helpers -----------------------------------------------------------------------

_CONNECTOR_DOMAIN = {
    "kicad": Domain.ELECTRICAL,
    "onshape": Domain.MECHANICAL,
    "github": Domain.CODE,
}


async def _project(db: AsyncSession, suffix: str) -> Project:
    team = Team(name=f"T-{suffix}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"P-{suffix}")
    db.add(project)
    await db.flush()
    return project


async def _entity(
    db: AsyncSession,
    project: Project,
    *,
    external_ref: str,
    connector: str = "kicad",
    domain: Domain = Domain.ELECTRICAL,
    entity_id: uuid.UUID | None = None,
    hints: dict[str, Any] | None = None,
) -> GraphEntity:
    row = GraphEntity(
        project_id=project.id,
        source_connector=connector,
        external_ref=external_ref,
        origin="connector",
        kind="component",
        domain=domain,
        name=external_ref,
        attrs={},
        modality_hints=hints or {},
    )
    if entity_id is not None:
        row.id = entity_id
    db.add(row)
    await db.flush()
    return row


def _ref(
    external_ref: str, connector: str = "kicad", entity_id: uuid.UUID | None = None
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
) -> ModalityMatch:
    return ModalityMatch(
        modality=modality,
        source_ref=ref,
        confidence=confidence,
        state=state,
        evidence={"matched_on": modality.value},
    )


def _part(
    base: str,
    modalities: tuple[ModalityMatch, ...],
    *,
    confidence: float = 0.97,
) -> CanonicalPart:
    return CanonicalPart(
        canonical_id=uuid.uuid5(uuid.NAMESPACE_DNS, base),
        part_number=base,
        modalities=list(modalities),
        confidence=confidence,
    )


def _output(
    *parts: CanonicalPart,
    unmatched: list[SourceRef] | None = None,
    ambiguous: list[Any] | None = None,
) -> FingerprintOutput:
    return FingerprintOutput(
        canonical_parts=list(parts), unmatched=unmatched or [], ambiguous=ambiguous or []
    )


async def _live_link_edges(db: AsyncSession, project: Project) -> list[GraphEdge]:
    rows = (
        (
            await db.execute(
                select(GraphEdge).where(
                    GraphEdge.project_id == project.id,
                    GraphEdge.origin == LINK_ORIGIN,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --- Edge creation -----------------------------------------------------------------


async def test_link_creates_cross_domain_same_as_edge(db: AsyncSession) -> None:
    project = await _project(db, "lnk-basic")
    circuit = await _entity(db, project, external_ref="U1", connector="kicad")
    cad = await _entity(
        db,
        project,
        external_ref="JHD-1",
        connector="onshape",
        domain=Domain.MECHANICAL,
    )
    part = _part(
        "LM358",
        (
            _mm(_ref("U1", entity_id=circuit.id), confidence=0.99),
            _mm(
                _ref("JHD-1", "onshape", entity_id=cad.id),
                modality=Modality.CAD_MODEL,
                confidence=0.9,
            ),
        ),
        confidence=0.98,
    )

    result = await link(db, _output(part), project_id=project.id)

    assert result.created == 1
    edges = await _live_link_edges(db, project)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.relation_type == RELATION_SAME_AS
    assert edge.origin == LINK_ORIGIN
    assert edge.source_id is None
    # confidence is the weakest link of the pair, capped by the part's own belief
    assert edge.confidence == pytest.approx(0.9)
    expected = {circuit.id: circuit.domain.value, cad.id: cad.domain.value}
    assert edge.domain_pair == f"{expected[edge.src_id]}<->{expected[edge.dst_id]}"
    assert edge.attrs["canonical_id"] == str(part.canonical_id)


async def test_direction_is_normalized(db: AsyncSession) -> None:
    project = await _project(db, "lnk-dir")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    forward = _part("P1", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("B", entity_id=b.id))))
    await link(db, _output(forward), project_id=project.id)
    backward = _part("P1", (_mm(_ref("B", entity_id=b.id)), _mm(_ref("A", entity_id=a.id))))
    result = await link(db, _output(backward), project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert len(edges) == 1
    assert result.created == 0 and result.updated == 0
    assert edges[0].src_id == min(a.id, b.id)
    assert edges[0].dst_id == max(a.id, b.id)


async def test_multi_instance_part_links_pairwise(db: AsyncSession) -> None:
    project = await _project(db, "lnk-multi")
    rows = [await _entity(db, project, external_ref=f"E{i}", entity_id=None) for i in range(3)]
    part = _part(
        "TL072",
        tuple(_mm(_ref(r.external_ref or "", entity_id=r.id)) for r in rows),
    )
    result = await link(db, _output(part), project_id=project.id)
    assert result.created == 3  # C(3,2)


async def test_low_confidence_edge_carries_honest_confidence(db: AsyncSession) -> None:
    project = await _project(db, "lnk-low")
    a = await _entity(db, project, external_ref="U3")
    b = await _entity(db, project, external_ref="U3-sym")
    part = _part(
        "NE555",
        (
            _mm(_ref("U3", entity_id=a.id), confidence=0.94),
            _mm(
                _ref("U3-sym", entity_id=b.id),
                modality=Modality.SCHEMATIC_SYMBOL,
                state=MatchState.LOW_CONFIDENCE,
                confidence=0.55,
            ),
        ),
        confidence=0.88,
    )
    result = await link(db, _output(part), project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert len(edges) == 1
    assert edges[0].confidence == pytest.approx(0.55)
    assert edges[0].attrs["matched"] is False
    assert result.low_confidence_edges == 1


async def test_matched_edge_is_not_flagged(db: AsyncSession) -> None:
    project = await _project(db, "lnk-matched")
    a = await _entity(db, project, external_ref="X")
    b = await _entity(db, project, external_ref="Y")
    part = _part("P", (_mm(_ref("X", entity_id=a.id)), _mm(_ref("Y", entity_id=b.id))))
    result = await link(db, _output(part), project_id=project.id)
    edges = await _live_link_edges(db, project)
    assert edges[0].attrs["matched"] is True
    assert result.low_confidence_edges == 0


async def test_duplicate_pair_keeps_best_support(db: AsyncSession) -> None:
    # part_number AND datasheet both land on entity A; symbol on entity B: the
    # (A, B) pair is supported twice — one edge, best support wins.
    project = await _project(db, "lnk-dup")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    part = _part(
        "P",
        (
            _mm(_ref("A", entity_id=a.id), confidence=0.99),
            _mm(
                _ref("A", entity_id=a.id),
                modality=Modality.DATASHEET,
                confidence=0.6,
                state=MatchState.LOW_CONFIDENCE,
            ),
            _mm(_ref("B", entity_id=b.id), modality=Modality.SCHEMATIC_SYMBOL, confidence=0.9),
        ),
        confidence=0.95,
    )
    result = await link(db, _output(part), project_id=project.id)
    edges = await _live_link_edges(db, project)
    assert len(edges) == 1
    assert result.created == 1
    assert edges[0].confidence == pytest.approx(0.9)  # min(0.95, 0.99, 0.9)
    assert edges[0].attrs["matched"] is True


# --- Idempotency & retraction ------------------------------------------------------


async def test_relink_is_idempotent(db: AsyncSession) -> None:
    project = await _project(db, "lnk-idem")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    output = _output(_part("P", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("B", entity_id=b.id)))))
    first = await link(db, output, project_id=project.id)
    second = await link(db, output, project_id=project.id)

    assert first.created == 1
    assert second == LinkResult()
    assert len(await _live_link_edges(db, project)) == 1


async def test_confidence_change_updates_in_place(db: AsyncSession) -> None:
    project = await _project(db, "lnk-upd")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    await link(
        db,
        _output(_part("P", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("B", entity_id=b.id))))),
        project_id=project.id,
    )
    result = await link(
        db,
        _output(
            _part(
                "P",
                (
                    _mm(_ref("A", entity_id=a.id), confidence=0.8),
                    _mm(_ref("B", entity_id=b.id)),
                ),
            )
        ),
        project_id=project.id,
    )
    edges = await _live_link_edges(db, project)
    assert result.updated == 1 and result.created == 0
    assert len(edges) == 1
    assert edges[0].confidence == pytest.approx(0.8)


async def test_retraction_soft_deletes_only_linker_edges(db: AsyncSession) -> None:
    project = await _project(db, "lnk-retract")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    c = await _entity(db, project, external_ref="C")
    # a manual same_as edge between the same pair must survive linker retraction
    manual = GraphEdge(
        project_id=project.id,
        src_id=min(a.id, b.id),
        dst_id=max(a.id, b.id),
        relation_type=RELATION_SAME_AS,
        domain_pair="electrical<->electrical",
        confidence=1.0,
        origin="manual",
        attrs={},
    )
    db.add(manual)
    await db.flush()

    both = _output(
        _part("P1", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("B", entity_id=b.id)))),
        _part("P2", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("C", entity_id=c.id)))),
    )
    await link(db, both, project_id=project.id)
    only_p2 = _output(_part("P2", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("C", entity_id=c.id)))))
    result = await link(db, only_p2, project_id=project.id)

    assert result.retracted == 1
    live = await _live_link_edges(db, project)
    assert len(live) == 1
    assert {live[0].src_id, live[0].dst_id} == {a.id, c.id}
    refreshed_manual = await db.get(GraphEdge, manual.id)
    assert refreshed_manual is not None and refreshed_manual.deleted_at is None


# --- Refusals ----------------------------------------------------------------------


async def test_unresolved_refs_counted_never_raised(db: AsyncSession) -> None:
    project = await _project(db, "lnk-unres")
    a = await _entity(db, project, external_ref="A")
    part = _part(
        "P",
        (
            _mm(_ref("A", entity_id=a.id)),
            _mm(_ref("GHOST", entity_id=None)),  # nothing in the graph
        ),
    )
    result = await link(db, _output(part), project_id=project.id)
    assert result.unresolved == 1
    assert result.created == 0  # one resolved observation cannot form a pair


async def test_ambiguous_observations_are_never_edged(db: AsyncSession) -> None:
    project = await _project(db, "lnk-ambig")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    amb = await _entity(db, project, external_ref="U12")
    from solus_api.fingerprint.contract import AmbiguousObservation

    part = _part("P", (_mm(_ref("A", entity_id=a.id)), _mm(_ref("B", entity_id=b.id))))
    output = _output(
        part,
        ambiguous=[
            AmbiguousObservation(
                source_ref=_ref("U12", entity_id=amb.id),
                candidate_canonical_ids=[part.canonical_id],
                note="cannot disambiguate",
            )
        ],
    )
    result = await link(db, output, project_id=project.id)

    assert result.ambiguous == 1
    edges = await _live_link_edges(db, project)
    assert len(edges) == 1
    assert amb.id not in {edges[0].src_id, edges[0].dst_id}


async def test_ambiguous_connector_ref_resolution_is_refused(db: AsyncSession) -> None:
    # two live entities share (connector, external_ref): provenance is ambiguous,
    # the linker must refuse rather than guess (mirrors fingerprint resolve()).
    project = await _project(db, "lnk-dupref")
    await _entity(db, project, external_ref="DUP")
    await _entity(db, project, external_ref="DUP")
    b = await _entity(db, project, external_ref="B")
    part = _part("P", (_mm(_ref("DUP")), _mm(_ref("B", entity_id=b.id))))
    result = await link(db, _output(part), project_id=project.id)
    assert result.unresolved == 1
    assert result.created == 0


async def test_mock_path_falls_back_to_connector_ref(db: AsyncSession) -> None:
    # the mock's graph_entity_id is a fixture that doesn't exist in this graph,
    # but the (connector, external_ref) pair identifies exactly one live entity —
    # the mock path opts into this fallback explicitly.
    project = await _project(db, "lnk-fallback")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    part = _part(
        "P",
        (
            _mm(_ref("A", entity_id=uuid.uuid4())),  # stale id, valid pair
            _mm(_ref("B", entity_id=b.id)),
        ),
    )
    result = await link(db, _output(part), project_id=project.id, pair_fallback_after_id_miss=True)
    assert result.created == 1
    edges = await _live_link_edges(db, project)
    assert {edges[0].src_id, edges[0].dst_id} == {a.id, b.id}


async def test_stale_id_is_refused_by_default(db: AsyncSession) -> None:
    # WRITE-SAFE default (FP-02's write-path rule): a dead graph_entity_id must
    # not fall back to the pair — a re-synced row with the same external_ref can
    # be a physically different component, and a stale ref must never stamp an
    # identity assertion computed from old data onto it.
    project = await _project(db, "lnk-staleid")
    await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    part = _part(
        "P",
        (
            _mm(_ref("A", entity_id=uuid.uuid4())),  # dead id, pair exists
            _mm(_ref("B", entity_id=b.id)),
        ),
    )
    result = await link(db, _output(part), project_id=project.id)
    assert result.unresolved == 1
    assert result.created == 0


async def test_relink_is_idempotent_across_commit(db: AsyncSession) -> None:
    # JSONB and Float round-trip equality must hold against rows REREAD from
    # the database, not just objects still sitting in the session.
    project = await _project(db, "lnk-idem-commit")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    output = _output(
        _part(
            "P",
            (
                _mm(_ref("A", entity_id=a.id), confidence=0.93),
                _mm(_ref("B", entity_id=b.id), confidence=0.87),
            ),
            confidence=0.91,
        )
    )
    project_id = project.id
    first = await link(db, output, project_id=project_id)
    await db.commit()  # expires all ORM state; the re-link rereads from the DB
    second = await link(db, output, project_id=project_id)

    assert first.created == 1
    assert second == LinkResult()
    edges = (
        (
            await db.execute(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.origin == LINK_ORIGIN,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(edges) == 1


async def test_pairwise_fanout_is_capped(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_api.linking import linker as linker_module

    monkeypatch.setattr(linker_module, "MAX_LINKED_OBSERVATIONS_PER_PART", 4)
    project = await _project(db, "lnk-fanout")
    rows = [await _entity(db, project, external_ref=f"F{i}") for i in range(6)]
    part = _part(
        "FLOOD",
        tuple(_mm(_ref(r.external_ref or "", entity_id=r.id)) for r in rows),
    )
    result = await link(db, _output(part), project_id=project.id)

    assert result.capped_parts == 1
    assert result.created == 6  # C(4,2), not C(6,2)=15
    assert len(await _live_link_edges(db, project)) == 6


async def test_cross_project_refs_never_resolve(db: AsyncSession) -> None:
    project_a = await _project(db, "lnk-iso-a")
    project_b = await _project(db, "lnk-iso-b")
    ours = await _entity(db, project_a, external_ref="A")
    theirs = await _entity(db, project_b, external_ref="B")
    part = _part(
        "P",
        (
            _mm(_ref("A", entity_id=ours.id)),
            _mm(_ref("B", entity_id=theirs.id)),  # other tenant's entity
        ),
    )
    result = await link(db, _output(part), project_id=project_a.id)
    assert result.unresolved == 1
    assert result.created == 0
    assert await _live_link_edges(db, project_b) == []


# --- The committed mock, end to end ------------------------------------------------


async def test_link_from_mock_end_to_end(db: AsyncSession) -> None:
    """The LNK-01 acceptance path: seed connector entities for every mock source_ref,
    link from the committed W0-06 mock, and get the known cross-domain graph."""
    project = await _project(db, "lnk-mock")
    output = load_mock_output()
    seen: set[uuid.UUID] = set()
    for part in output.canonical_parts:
        for m in part.modalities:
            assert m.source_ref.graph_entity_id is not None
            if m.source_ref.graph_entity_id in seen:
                continue
            seen.add(m.source_ref.graph_entity_id)
            connector = m.source_ref.source_connector or "kicad"
            await _entity(
                db,
                project,
                external_ref=m.source_ref.external_ref or "",
                connector=connector,
                domain=_CONNECTOR_DOMAIN[connector],
                entity_id=m.source_ref.graph_entity_id,
            )
    for obs in output.ambiguous:
        assert obs.source_ref.graph_entity_id is not None
        await _entity(
            db,
            project,
            external_ref=obs.source_ref.external_ref or "",
            entity_id=obs.source_ref.graph_entity_id,
        )

    result = await link_from_mock(db, project_id=project.id)

    # 10 parts: 3 tri-modality (3 edges each) + 7 bi-modality (1 edge each) = 16
    edges = await _live_link_edges(db, project)
    assert len(edges) == 16
    assert result.created == 16
    assert result.ambiguous == 1
    assert result.unresolved == 0
    # NE555's OCR-uncertain symbol: the edge exists but carries the honest 0.55
    ne555 = [e for e in edges if e.attrs.get("part_number") == "NE555"]
    assert len(ne555) == 1
    assert ne555[0].confidence == pytest.approx(0.55)
    assert ne555[0].attrs["matched"] is False
    # cross-domain: onshape CAD entities produced electrical<->mechanical edges
    cross = {e.domain_pair for e in edges}
    assert "electrical<->mechanical" in cross or "mechanical<->electrical" in cross
    # the ambiguous U12 entity got no edges
    amb_id = output.ambiguous[0].source_ref.graph_entity_id
    assert all(amb_id not in {e.src_id, e.dst_id} for e in edges)
    # idempotent re-link of the same mock
    again = await link_from_mock(db, project_id=project.id)
    assert again == LinkResult(ambiguous=1)


# --- LNK-02: conflicts, ties, and the real-fingerprint swap ------------------------


def _two_obs_part(
    base: str,
    a: GraphEntity,
    b: GraphEntity,
    *,
    confidence: float,
    obs_confidence: float = 0.99,
) -> CanonicalPart:
    return _part(
        base,
        (
            _mm(_ref(a.external_ref or "", entity_id=a.id), confidence=obs_confidence),
            _mm(_ref(b.external_ref or "", entity_id=b.id), confidence=obs_confidence),
        ),
        confidence=confidence,
    )


async def test_conflict_between_parts_resolved_by_confidence(db: AsyncSession) -> None:
    project = await _project(db, "lnk2-conf")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    strong = _two_obs_part("LM358", a, b, confidence=0.9)
    weak = _two_obs_part("TL072", a, b, confidence=0.7)
    result = await link(db, _output(strong, weak), project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert result.created == 1 and result.ties == 0
    assert len(edges) == 1
    assert edges[0].confidence == pytest.approx(0.9)
    assert edges[0].attrs["part_number"] == "LM358"


async def test_tied_conflict_is_flagged_never_guessed(db: AsyncSession) -> None:
    project = await _project(db, "lnk2-tie")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    p1 = _two_obs_part("LM358", a, b, confidence=0.8)
    p2 = _two_obs_part("TL072", a, b, confidence=0.8)
    result = await link(db, _output(p1, p2), project_id=project.id)

    assert result.ties == 1
    assert result.created == 0
    assert await _live_link_edges(db, project) == []


async def test_tie_cleared_by_strictly_better_support(db: AsyncSession) -> None:
    project = await _project(db, "lnk2-tieclear")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    p1 = _two_obs_part("LM358", a, b, confidence=0.7)
    p2 = _two_obs_part("TL072", a, b, confidence=0.7)
    p3 = _two_obs_part("NE555", a, b, confidence=0.85)
    result = await link(db, _output(p1, p2, p3), project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert result.ties == 0
    assert len(edges) == 1
    assert edges[0].attrs["part_number"] == "NE555"


async def test_tie_retracts_previously_supported_edge(db: AsyncSession) -> None:
    # A pair the linker asserted earlier stops being unambiguous: the edge is
    # retracted and the tie surfaced — reconciliation never keeps a guess alive.
    project = await _project(db, "lnk2-tieretract")
    a = await _entity(db, project, external_ref="A")
    b = await _entity(db, project, external_ref="B")
    await link(db, _output(_two_obs_part("LM358", a, b, confidence=0.8)), project_id=project.id)
    tied = _output(
        _two_obs_part("LM358", a, b, confidence=0.8),
        _two_obs_part("TL072", a, b, confidence=0.8),
    )
    result = await link(db, tied, project_id=project.id)

    assert result.ties == 1
    assert result.retracted == 1
    assert await _live_link_edges(db, project) == []


async def test_link_from_fingerprint_multi_instance_part(db: AsyncSession) -> None:
    """The swap: real matcher over modality_hints — two board positions of one
    MPN link to each other; an unrelated part forms no cross-part edge."""
    project = await _project(db, "lnk2-real")
    u1 = await _entity(db, project, external_ref="U1", hints={"part_number": "LM358"})
    u2 = await _entity(db, project, external_ref="U2", hints={"part_number": "LM358"})
    await _entity(db, project, external_ref="U3", hints={"part_number": "NE555"})

    result = await link_from_fingerprint(db, project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert result.created == 1
    assert len(edges) == 1
    assert {edges[0].src_id, edges[0].dst_id} == {u1.id, u2.id}
    assert edges[0].attrs["matched"] is True
    assert edges[0].attrs["part_number"] == "LM358"


async def test_link_from_fingerprint_datasheet_alone_never_links(db: AsyncSession) -> None:
    # "A datasheet alone is a family": the real matcher refuses to attach an
    # entity whose only signal is a datasheet (it lands in `unmatched`), so the
    # linker must produce NO edge for it — the fingerprint's refusal is
    # respected, never papered over. The LOW_CONFIDENCE edge path itself is
    # exercised through the contract in
    # test_low_confidence_edge_carries_honest_confidence and the mock e2e; the
    # v1 matcher emits LOW_CONFIDENCE only for same-entity corroboration.
    project = await _project(db, "lnk2-low")
    await _entity(db, project, external_ref="U1", hints={"part_number": "LM358"})
    await _entity(db, project, external_ref="U1d", hints={"datasheet": "lm358.pdf"})

    result = await link_from_fingerprint(db, project_id=project.id)

    assert await _live_link_edges(db, project) == []
    assert result.created == 0 and result.low_confidence_edges == 0


async def test_scan_then_link_full_real_pipeline(db: AsyncSession) -> None:
    """connector-shaped entities → FP-02 scan (canonical rows + FK stamps) →
    link_from_fingerprint. The linker's edges and FP's stamps must agree, and
    canonical rows themselves are never edge endpoints (they carry no hints)."""
    from solus_api.fingerprint.ingest import scan_project

    project = await _project(db, "lnk2-pipeline")
    u1 = await _entity(db, project, external_ref="U1", hints={"part_number": "LM358"})
    u2 = await _entity(db, project, external_ref="U2", hints={"part_number": "LM358"})

    await scan_project(db, project.id)
    result = await link_from_fingerprint(db, project_id=project.id)

    edges = await _live_link_edges(db, project)
    assert result.created == 1
    assert len(edges) == 1
    assert {edges[0].src_id, edges[0].dst_id} == {u1.id, u2.id}
    refreshed = [await db.get(GraphEntity, u1.id), await db.get(GraphEntity, u2.id)]
    canonical_ids = {row.canonical_part_id for row in refreshed if row is not None}
    assert len(canonical_ids) == 1 and None not in canonical_ids  # FP stamped both
    assert canonical_ids.pop() not in {edges[0].src_id, edges[0].dst_id}
    # the mock seam is untouched by the swap: re-linking from the mock on a
    # separate project still works (regression is the LNK-01 e2e test above)
