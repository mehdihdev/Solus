"""SOL reasoning↔systems interface conformance (SOLUS-W0-07).

Proves the mock-and-swap seam: `FakeSolSystems` satisfies the `SolSystems` Protocol and every method
returns a well-formed, model-consumable shape — so reasoning can build against the fake now and swap
in the real systems impl later with no change. Pure unit — no DB.
"""

from uuid import UUID, uuid4

from solus_api.agent.fake_systems import FakeSolSystems
from solus_api.agent.interfaces import (
    ContextBudget,
    GraphContext,
    GraphScope,
    RetrievalFilter,
    SolSystems,
    TelemetrySummaryView,
    TelemetryWindow,
)
from solus_api.agent.tools import ArtifactRef
from solus_api.fingerprint.contract import SourceRef

# Structural conformance proven at TYPE-CHECK time: mypy verifies FakeSolSystems satisfies the
# SolSystems Protocol — the method set, parameter types/order/count, and return types (NOT param
# names, since the params are positional-or-keyword). Stronger than a runtime isinstance.
_STRUCTURAL: SolSystems = FakeSolSystems()


async def _assert_conforms(systems: SolSystems, project_id: UUID) -> None:
    """The reusable shape of a conformance check — every method returns a well-formed result.
    Systems (Mehdi) can run the same against the real impl, and MUST additionally add a cross-tenant
    ISOLATION case (write under team A, then read under team B returns none of A's data) — the fake
    is exempt because it ignores `project_id` by design and cannot model isolation (§7)."""
    ctx = await systems.get_graph_context(
        project_id, GraphScope(anchor_entity_ids=[uuid4()], degree=2)
    )
    assert isinstance(ctx, GraphContext)
    entity_ids = {e.id for e in ctx.entities}
    assert all(e.kind and e.name for e in ctx.entities)
    for edge in ctx.edges:  # intra-context: edges reference only entities that were returned
        assert edge.src_id in entity_ids and edge.dst_id in entity_ids

    telemetry = await systems.get_telemetry(project_id, TelemetryWindow(duration_seconds=10))
    assert isinstance(telemetry, TelemetrySummaryView)
    assert telemetry.windows  # a SEQUENCE, not one static snapshot
    for window in telemetry.windows:
        assert window.window_start <= window.window_end and window.summary
    assert any(isinstance(w.raw_ref, ArtifactRef) for w in telemetry.windows)  # reused W0-04 shape

    errors = await systems.get_error_history("brownout", k=1)
    assert len(errors) <= 1
    for error_hit in errors:
        assert isinstance(error_hit.source_ref, SourceRef) and isinstance(error_hit.score, float)

    rag = await systems.rag_query("lm358", k=2)
    assert len(rag) <= 2
    for rag_hit in rag:
        assert rag_hit.chunk and isinstance(
            rag_hit.source_ref, SourceRef
        )  # reused W0-06 provenance

    recorded = await systems.record_error_solution(project_id, "err", "fix", "electrical")
    assert isinstance(recorded, UUID)  # the flywheel returns the stored error_solution id


async def test_fake_sol_systems_conforms() -> None:
    await _assert_conforms(FakeSolSystems(), uuid4())


async def test_graph_budget_forces_truncation() -> None:
    ctx = await FakeSolSystems().get_graph_context(
        uuid4(),
        GraphScope(anchor_entity_ids=[uuid4()], degree=2),
        ContextBudget(max_entities=1),  # SYS-05 hook: constrain, systems sub-samples
    )
    assert ctx.truncated is True
    assert len(ctx.entities) <= 1
    kept = {e.id for e in ctx.entities}
    assert all(e.src_id in kept and e.dst_id in kept for e in ctx.edges)  # no dangling edges


async def test_telemetry_is_a_progression_with_a_lazy_raw_ref() -> None:
    view = await FakeSolSystems().get_telemetry(uuid4(), TelemetryWindow(duration_seconds=20))
    assert len(view.windows) >= 2  # progression across windows, not a single summary
    spiking = [w for w in view.windows if w.anomalies]
    assert spiking
    raw = spiking[0].raw_ref
    assert isinstance(raw, ArtifactRef)  # raw data is REFERENCED, not inlined
    assert raw.summary  # reasoning reasons on the summary WITHOUT fetching the bytes


async def test_error_and_rag_hits_carry_provenance_and_solutions() -> None:
    systems = FakeSolSystems()
    errors = await systems.get_error_history("i2c", k=5)
    assert errors and all(e.solution_text for e in errors)  # error-scoped adds the recorded fix
    rag = await systems.rag_query("op-amp", k=1)
    assert len(rag) == 1  # k is honored
    # SourceRef enforces resolvability at construction, so every hit is traceable/citable.
    hit_ref = rag[0].source_ref
    assert hit_ref.external_ref is not None or hit_ref.graph_entity_id is not None


async def test_retrieval_filter_is_optional() -> None:
    systems = FakeSolSystems()
    unfiltered = await systems.rag_query("x", k=2)
    filtered = await systems.get_error_history(
        "x", k=2, filter=RetrievalFilter(project_id=uuid4(), source_types=["error"])
    )
    assert isinstance(unfiltered, list) and isinstance(filtered, list)
