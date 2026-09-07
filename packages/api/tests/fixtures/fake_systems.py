"""`FakeSolSystems` — the canned `SolSystems` TEST DOUBLE (SOLUS-W0-07).

Demoted from production wiring by SYS-04: `agent/feeds.py` (`DbSolSystems`) is the real
implementation behind the same Protocol, and a ratchet in `test_feeds.py` keeps this fake out
of `src/` forever — its LM358/`camera_node` fictions once shipped as SOL's "context". It stays
valuable HERE: deterministic (fixed timestamps, no `now()`), and it exercises corners of the
contract real data rarely hits — the SYS-05 budget sub-sampling, the telemetry window sequence
with a `raw_ref`, and resolvable `SourceRef` provenance on hits. Several suites subclass it to
inject hostile or recording behaviors.
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
from solus_api.corpus.retrieval import CorpusHit
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
        if filter is not None and filter.source_types == ["corpus"]:
            return self.corpus_hits(filter)[:k]
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

    def corpus_hits(self, filter: RetrievalFilter) -> list[RagHit]:
        """Two shipped-reference chunks (CORPUS C2): a confident principle and a
        low-confidence rule of thumb, both electrical. Honour the domain filter."""
        if filter.domains is not None and "electrical" not in filter.domains:
            return []
        return [
            CorpusHit(
                chunk=(
                    "Decoupling is about loop area\n\nA decoupling capacitor supplies transient "
                    "current; the loop inductance through its pins limits how fast."
                ),
                source_ref=SourceRef(
                    source_connector="corpus", external_ref="electrical/decoupling/loop-area"
                ),
                score=0.83,
                chunk_id="corpus:electrical/decoupling/loop-area",
                title="Decoupling is about loop area",
                domain="electrical",
                topic="decoupling",
                kind="principle",
                audience="fundamentals",
                confidence=0.9,
                attribution="",
                low_confidence=False,
            ),
            CorpusHit(
                chunk=(
                    "Bulk capacitance per rail\n\nA few hundred microfarads of bulk per motor "
                    "rail is a starting point, not a design."
                ),
                source_ref=SourceRef(
                    source_connector="corpus", external_ref="electrical/power_design/bulk-cap-rule"
                ),
                score=0.61,
                chunk_id="corpus:electrical/power_design/bulk-cap-rule",
                title="Bulk capacitance per rail",
                domain="electrical",
                topic="power_design",
                kind="rule_of_thumb",
                audience="reference",
                confidence=0.5,
                attribution="",
                low_confidence=True,
            ),
        ]

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
