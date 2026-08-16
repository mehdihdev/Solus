"""The W0-07 core-contract assertions, shared by fake and real `SolSystems` suites.

Shared by `test_sol_interface.py` (fake) and `test_feeds.py` (real impl). This
asserts only what `docs/contracts/sol-interface.md` genuinely requires of ANY
implementation: well-formed shapes, intra-context edge integrity, provenance on
hits, k honored, and the flywheel returning the stored id. Deliberately absent —
because they are behaviors of specific implementations, not the contract:
non-empty telemetry windows, a present `raw_ref` (Optional in the contract), and
tolerance of unfiltered tenant retrieval (a real impl correctly REFUSES that).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from solus_api.agent.interfaces import (
    GraphContext,
    GraphScope,
    RetrievalFilter,
    SolSystems,
    TelemetrySummaryView,
    TelemetryWindow,
)
from solus_api.fingerprint.contract import SourceRef


async def assert_core_contract(
    systems: SolSystems,
    project_id: UUID,
    *,
    anchors: list[UUID] | None = None,
) -> None:
    """Every method returns a well-formed, model-consumable result. Universally
    quantified over whatever data the implementation holds — an empty project
    passes (empty is honest), a populated one is validated shape-by-shape.
    Real-impl suites must ADDITIONALLY cover cross-tenant isolation (§7)."""
    ctx = await systems.get_graph_context(
        project_id, GraphScope(anchor_entity_ids=anchors or [uuid4()], degree=2)
    )
    assert isinstance(ctx, GraphContext)
    entity_ids = {e.id for e in ctx.entities}
    assert all(e.kind and e.name for e in ctx.entities)
    for edge in ctx.edges:  # intra-context: edges reference only entities that were returned
        assert edge.src_id in entity_ids and edge.dst_id in entity_ids

    telemetry = await systems.get_telemetry(project_id, TelemetryWindow(duration_seconds=10))
    assert isinstance(telemetry, TelemetrySummaryView)
    for window in telemetry.windows:
        assert window.window_start <= window.window_end and window.summary

    tenant_filter = RetrievalFilter(project_id=project_id)
    errors = await systems.get_error_history("brownout", k=1, filter=tenant_filter)
    assert len(errors) <= 1
    for error_hit in errors:
        assert isinstance(error_hit.source_ref, SourceRef) and isinstance(error_hit.score, float)

    rag = await systems.rag_query("lm358", k=2, filter=tenant_filter)
    assert len(rag) <= 2
    for rag_hit in rag:
        assert rag_hit.chunk and isinstance(
            rag_hit.source_ref, SourceRef
        )  # reused W0-06 provenance

    recorded = await systems.record_error_solution(project_id, "err", "fix", "electrical")
    assert isinstance(recorded, UUID)  # the flywheel returns the stored error_solution id
