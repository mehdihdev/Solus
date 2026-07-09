"""`FakeSolSystems` — a canned `SolSystems` reasoning builds against NOW (SOLUS-W0-07).

The mock-and-swap seam: reasoning (Pratham) develops and tests against this fake today; systems
(Mehdi) provides the real impl behind the SAME `SolSystems` Protocol; they swap with no change to
reasoning. The fake is deterministic (fixed timestamps, no `now()`) and exercises every corner of
the contract — the SYS-05 budget sub-sampling, the telemetry window sequence with a `raw_ref`, and
resolvable `SourceRef` provenance on hits.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from solus_api.agent.interfaces import (
    ContextBudget,
    EdgeRead,
    EntityRead,
    ErrorHit,
    GraphContext,
    GraphScope,
    RagHit,
    RetrievalFilter,
    TelemetrySummaryView,
    TelemetryWindow,
    TelemetryWindowSummary,
)
from solus_api.agent.tools import ArtifactRef
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import ArtifactStorage

# A fixed base so the fake is deterministic (window timestamps never depend on wall-clock).
_BASE = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


class FakeSolSystems:
    """Canned `SolSystems` for reasoning to build against (mock-and-swap). Structurally satisfies
    the Protocol — mypy verifies the method set + signature types via the typed assignment in the
    conformance test. It ignores `project_id` by design (a fake has no tenants to isolate)."""

    async def get_graph_context(
        self,
        project_id: UUID,
        scope: GraphScope,
        budget: ContextBudget | None = None,
    ) -> GraphContext:
        anchor = scope.anchor_entity_ids[0] if scope.anchor_entity_ids else uuid4()
        neighbor = uuid4()
        entities = [
            EntityRead(
                id=anchor,
                kind="component",
                domain="electrical",
                name="LM358",
                source_connector="kicad",
                external_ref="U1",
                attrs={"value": "LM358"},
            ),
            EntityRead(
                id=neighbor,
                kind="component",
                domain="electrical",
                name="C1",
                source_connector="kicad",
                external_ref="C1",
                attrs={"value": "100nF"},
            ),
        ]
        edges = [
            EdgeRead(
                src_id=anchor,
                dst_id=neighbor,
                relation_type="soldered_to",
                domain_pair="electrical<->electrical",
                confidence=0.9,
            )
        ]
        truncated = False
        if (
            budget is not None
            and budget.max_entities is not None
            and len(entities) > budget.max_entities
        ):
            entities = entities[: budget.max_entities]
            kept = {e.id for e in entities}  # drop edges whose ends were sub-sampled away
            edges = [e for e in edges if e.src_id in kept and e.dst_id in kept]
            truncated = True
        return GraphContext(entities=entities, edges=edges, truncated=truncated)

    async def get_telemetry(
        self,
        project_id: UUID,
        window: TelemetryWindow,
    ) -> TelemetrySummaryView:
        half = window.duration_seconds / 2
        mid = _BASE + timedelta(seconds=half)
        end = _BASE + timedelta(seconds=window.duration_seconds)
        # A SEQUENCE of window-summaries (a progression), the second carrying an anomaly + raw_ref.
        windows = [
            TelemetryWindowSummary(
                window_start=_BASE,
                window_end=mid,
                summary="nominal: motor current steady ~1.2A",
                signals={"motor_current_a": {"mean": 1.2, "max": 1.4}},
            ),
            TelemetryWindowSummary(
                window_start=mid,
                window_end=end,
                summary="motor current spiked to 3.1A, then recovered",
                signals={"motor_current_a": {"mean": 1.9, "max": 3.1}},
                anomalies=["motor_current_a exceeded 3A"],
                raw_ref=ArtifactRef(
                    artifact_id=uuid4(),
                    uri="s3://telemetry/window2.parquet",
                    media_type="application/octet-stream",
                    storage=ArtifactStorage.S3,
                    size_bytes=1_048_576,
                    summary="raw 1kHz samples for the spike window",
                ),
            ),
        ]
        return TelemetrySummaryView(windows=windows)

    async def get_error_history(
        self,
        query: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[ErrorHit]:
        hits = [
            ErrorHit(
                chunk="I2C address 0x68 conflicts with the IMU",
                source_ref=SourceRef(source_connector="error_store", external_ref="err-101"),
                score=0.92,
                solution_text="Re-strap AD0 high to move the IMU to 0x69",
            ),
            ErrorHit(
                chunk="undervoltage brownout on the 3v3 rail during motor spin-up",
                source_ref=SourceRef(graph_entity_id=uuid4()),
                score=0.81,
                solution_text="Add a 470uF bulk cap on 3v3",
            ),
        ]
        return hits[:k]

    async def rag_query(
        self,
        text: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[RagHit]:
        hits = [
            RagHit(
                chunk="The LM358 is a dual op-amp with a single-supply range of 3-32V.",
                source_ref=SourceRef(source_connector="datasheet", external_ref="lm358.pdf#p1"),
                score=0.88,
            ),
            RagHit(
                chunk="camera_node publishes /image_raw at 30Hz",
                source_ref=SourceRef(source_connector="ros", external_ref="camera_node"),
                score=0.74,
            ),
        ]
        return hits[:k]

    async def record_error_solution(
        self,
        project_id: UUID,
        error_text: str,
        solution_text: str,
        domain: str,
        attrs: dict[str, Any] | None = None,
    ) -> UUID:
        # The real impl writes an error_solution row (the flywheel); the fake just mints its id.
        return uuid4()
