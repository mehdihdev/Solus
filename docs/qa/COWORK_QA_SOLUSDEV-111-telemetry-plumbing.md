# Cowork QA — SOLUSDEV-111 / SOLUS-LNK-06: Graph data plumbing for telemetry

**Feature:** Wire live telemetry into the graph — a sensor/actuator entity carries/streams its live
values through a bounded recent-values buffer, queryable via the W0-07 `get_telemetry` shape and
readable as a Foxglove-consumable feed.

> **Scope note for the tester.** This ticket is **backend plumbing with no HTTP route and no UI yet**
> (by design — CLAUDE.md §3 forbids adding undocumented API surface; Live Bench/CON-03 wire the
> transport later). There is nothing to click. QA is therefore exercised at the module boundary with
> the harness below, plus the automated test suite. Mark each path pass/fail.

---

## Setup state

- Repo checked out on branch `SOLUSDEV-111-graph-telemetry-plumbing`.
- `packages/api` deps installed: `cd packages/api && uv sync`.
- PostgreSQL + pgvector running for the DB-resolver paths: `make db-up` (from repo root). The pure
  in-memory/Redis paths need **no** services.
- No Redis required — the buffer falls back to an in-memory backend when `SOLUS_REDIS_URL` is unset.

---

## Automated suite (run first)

```
cd packages/api
uv run pytest -q tests/test_packet.py tests/test_buffer.py tests/test_resolver.py tests/test_telemetry.py
```

- [ ] All tests pass (40 tests).
- [ ] `uv run ruff check src/solus_api/graph/` → clean.
- [ ] `uv run mypy src/solus_api/graph/` → `Success: no issues found`.

---

## Flow 1 — Attach a sample stream to an entity and read it back (core acceptance)

Run this harness (`uv run python - <<'PY' ... PY`):

```python
import asyncio, uuid
from datetime import UTC, datetime, timedelta
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing

async def main():
    project, entity = uuid.uuid4(), uuid.uuid4()
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver({(project, "motor0"): entity}))
    t0 = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    for i in range(5):
        r = await plumbing.ingest(project, TelemetryPacket(device_id="motor0",
            timestamp=t0 + timedelta(seconds=i), values={"current_a": 1.0 + i}))
        print("ingested", r.entity_id == entity, r.accepted)
    view = await plumbing.get_recent_values(project, entity)
    print([p.value for s in view.signals for p in s.points])

asyncio.run(main())
```

**Expected:**

- [ ] Each ingest prints `ingested True 1` (packet attached to the resolved entity).
- [ ] Final line prints `[1.0, 2.0, 3.0, 4.0, 5.0]` (stream reads back in order).

## Flow 2 — Bounded buffer under backpressure (no unbounded growth)

- Construct `InMemoryTelemetryBuffer(capacity=4)`, append 50 samples to one signal, read back.
- [ ] Exactly 4 samples retained — the **last** 4 (values 46–49). No growth beyond capacity.

## Flow 3 — W0-07 `get_telemetry` window summary

- Ingest 10 samples over 10s (as in the automated `_seed_progression`), then
  `await plumbing.get_telemetry(project, TelemetryWindow(duration_seconds=10))`.
- [ ] Returns a `TelemetrySummaryView` with **≥2** windows (a progression, not one snapshot).
- [ ] Each window's `signals["current_a"]` carries `mean/min/max/last/count`.
- [ ] Calling it twice returns **identical** views (deterministic; anchored to the latest sample, no
      wall-clock).
- [ ] `TelemetryWindow(duration_seconds=10, signals=["nonexistent"])` → `windows == []`.

## Flow 4 — Foxglove-consumable feed (CON-03)

- `view = await plumbing.get_recent_values(project, entity); view.model_dump_json()`.
- [ ] Produces valid JSON containing the signal name and entity id; round-trips via
      `RecentValuesView.model_validate_json(...)` back to an equal object.

## Flow 5 — DB entity resolution + tenant isolation (needs Postgres)

Covered by `tests/test_resolver.py`:

- [ ] `test_db_resolver_finds_entity_by_external_ref` — a device id resolves to its entity by
      `external_ref`.
- [ ] `test_db_resolver_is_project_scoped` — a device id present in **project A never resolves under
      project B** (tenant isolation, §7).
- [ ] `test_db_resolver_returns_none_for_unknown_device` — unknown device → `None`.

---

## Edge cases & failure paths

- [ ] **Malformed / hostile packet rejected at the boundary** (`tests/test_packet.py`): empty values, >256 signals, signal-name >128 chars, empty `device_id`, `NaN`/`±inf` value, and unknown extra
      fields all raise `ValidationError` — ingestion never sees them.
- [ ] **Unresolved device dropped, not raised** (`test_ingest_drops_packet_for_unresolved_device`):
      ingesting a packet whose `device_id` matches no entity returns `entity_id=None, accepted=0` and
      does not throw — a stray/hostile stream can't crash ingestion.
- [ ] **Project isolation on the buffer** (`test_buffer_isolates_by_project`): reading team B's
      project returns none of team A's samples.
- [ ] **Empty buffer** → `get_telemetry` returns `windows == []` (no crash, no fabricated window).
- [ ] **Redis backend parity** (`test_redis_buffer_*`): LTRIM bounds the ring to capacity, `since`/
      `limit` honored, and every key gets a TTL so idle feeds expire.
- [ ] **Non-positive capacity / buckets** raise `ValueError` at construction.

## Cross-feature interactions to verify later (not in this ticket)

- Live Bench real-time seam subscribes to the same `TelemetryWindowSummary` shape (streaming
  extension — no contract change).
- CON-03 Foxglove bridge consumes `RecentValuesView` as the live feed.
- The full `SolSystems` real impl composes `TelemetryPlumbing.get_telemetry` behind the W0-07 Protocol
  alongside `get_graph_context` / RAG.
