# Completion Report — SOLUSDEV-111 / SOLUS-LNK-06: Graph data plumbing for telemetry

**Branch:** `SOLUSDEV-111-graph-telemetry-plumbing` (branched from
`SOLUSDEV-115-compatibility-checkers-core` per instruction). **Status:** implemented, tests green,
type-checked, integrated on the feature branch, left uncommitted-to-remote for human review → MR.

---

## What was built

The bridge between Live Bench telemetry and the graph SOL reasons over — a sensor/actuator entity
now carries/streams its live values through a bounded recent-values buffer, queryable via the W0-07
`get_telemetry` shape and readable as a Foxglove-consumable feed. New package
`packages/api/src/solus_api/graph/`:

- **`packet.py`** — `TelemetryPacket` (the **proposed LB-06** wire shape), plus the read shapes
  `RecentSample` / `SignalSeries` / `RecentValuesView`. Untrusted device input is bounded at the
  boundary (device-id length, ≤256 signals, ≤128-char signal names, finite values only, `extra=forbid`).
- **`buffer.py`** — `TelemetryBuffer` Protocol with two interchangeable backends: `InMemoryTelemetryBuffer`
  (deque ring, default/dev/test) and `RedisTelemetryBuffer` (LIST + LTRIM bound + per-key TTL). Each
  `(project, entity, signal)` keeps only the last `capacity` samples → bounded, backpressure-friendly.
- **`resolver.py`** — `EntityResolver` Protocol with `DictEntityResolver` (tests) and `DbEntityResolver`
  (matches a packet's `device_id` to `graph_entity.external_ref`, **project-scoped**, live rows only).
- **`telemetry.py`** — `TelemetryPlumbing`: `ingest` (map packet → entity → buffer), `get_recent_values`
  (raw Foxglove feed), and `get_telemetry(project_id, window)` — the W0-07 shape, computed
  **deterministically** from the buffer (per-signal mean/min/max/last/count over equal sub-windows
  anchored to the latest sample; no LLM, no wall-clock).
- **Tests:** `tests/test_{packet,buffer,resolver,telemetry}.py` — 40 tests (unit + Redis-backend parity
  via an in-process fake + Postgres DB-resolver + tenant-isolation case).

## Governing docs consulted

CLAUDE.md §7 (untrusted telemetry ingestion + tenant isolation), §9 (contracts frozen), §3 (no
undocumented API routes). W0-07 `docs/contracts/sol-interface.md` + `agent/interfaces.py`
(`SolSystems.get_telemetry` → `TelemetrySummaryView`; `TelemetryWindow`/`TelemetryWindowSummary`
shapes, reused, never redefined). ADR-027 + `models.py` (`graph_entity`, `external_ref` as the
identity linchpin). `connectors/worker.py` (the Redis-optional / in-memory-fallback convention this
mirrors).

## Design decisions (delegated judgment — confirmed with the human at the Phase 1 gate)

1. **`get_telemetry` scope:** implement the buffer + raw read **and** a deterministic systems-side
   `get_telemetry` that folds the buffer into `TelemetryWindowSummary` windows (mean/min/max/last/count).
   No LLM narration and no S3 `raw_ref` — those are later SYS / Live Bench tickets. Signature matches
   the W0-07 Protocol so it composes behind the real `SolSystems` impl.
2. **LB-06 packet shape:** defined locally as `TelemetryPacket` **inside the api package, NOT in the
   frozen `packages/contracts/`.** See the flag below — this needs human ratification/extraction.
3. **Persistence:** Redis buffer + in-memory fallback, **no new Postgres table / no migration** (live
   ephemeral values only). Durable history / raw-sample S3 offload stays out of scope.
4. **File location:** the ticket's AI prompt named `backend/app/graph/telemetry.py`; the real backend
   is `packages/api/src/solus_api/`, so the code lives in a new `solus_api/graph/` subpackage.
5. **No API route added** — none is planned in `docs/api/`, and §3 forbids inventing surface. The
   plumbing is exercised at the module boundary; Live Bench/CON-03 wire the transport later.
6. **Determinism:** `get_telemetry` anchors "now" to the latest buffered sample (not wall-clock), so
   results are repeatable and testable.
7. **Ingest never raises on bad data:** an unresolved device → dropped (`accepted=0`); a malformed
   packet is rejected at the Pydantic boundary — a stray/hostile stream can't crash ingestion (§7).

## Security (CLAUDE.md §7)

- **Untrusted device input:** packet bounds + finite-value checks at the boundary; unresolved devices
  dropped, not raised; buffer bounded per signal (no unbounded growth); Redis keys carry a TTL.
- **Tenant isolation:** buffer keys are project-scoped; `DbEntityResolver` filters by `project_id`
  (derived from the request, never the packet); a dedicated test proves a device id in project A does
  not resolve under project B.
- **Prompt injection:** summary strings are deterministic Solus-authored text; ingested signal
  **names** flow through only as data (dict keys in `signals`), never emitted as instructions here.
  The reasoning layer remains responsible for delimiting them per the W0-07 contract.
- No `eval`/`exec`, no `shell=True`, no string-built SQL (ORM `select` with bound params).

## Verification

- `uv run pytest -q` → **434 passed** (40 new; no regressions).
- `uv run ruff check src/solus_api/graph/ tests/test_{packet,buffer,resolver,telemetry}.py` → clean.
- `uv run mypy src/solus_api/graph/` → `Success: no issues found in 5 source files`.
- Phase 4 review: `security-reviewer` + `python-reviewer` subagents run on the diff.

### Review findings & resolutions

**Security review — PASS, no findings.** Verified: untrusted-input bounds at the packet boundary,
project-scoped buffer keys + resolver (tenant isolation), no ingested content emitted as instructions,
no eval/exec, no string-built SQL, Redis key construction safe.

**Python review — two HIGH bugs found (verified by execution) and FIXED before handoff:**

| #   | Sev  | Finding                                                                                                                                                                            | Resolution                                                                                                                                                                             |
| --- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | HIGH | `_apply_since_limit` (`buffer.py`): `limit=0` returned the whole buffer (`samples[-0:]` == `samples[0:]`); negative limit silently unlimited.                                      | Fixed: `limit==0` → `[]`, negative → `ValueError`. Regression tests added (`test_buffer_limit_zero_returns_nothing`, `_negative_limit_is_rejected`, Redis equivalent).                 |
| 2   | HIGH | `TelemetryPacket.timestamp` had no tz-awareness validation; a naive/aware mix crashed `get_telemetry` with `TypeError`, taking down the whole project's summary on one bad packet. | Fixed: `field_validator` rejects naive timestamps at the boundary (§7 reject-don't-truncate). Regression test added (`test_packet_rejects_naive_timestamp`).                           |
| 3   | MED  | `RedisTelemetryBuffer` client typed `Any`.                                                                                                                                         | Fixed: added a narrow `RedisClient` Protocol (no hard `redis` import).                                                                                                                 |
| 4   | MED  | Redis `append` is 7 unpipelined round-trips — not atomic; concurrent writers/crash can transiently exceed capacity or skip a TTL.                                                  | **Deferred** (self-heals on next append; low risk at current bounded scale). Recommend a pipeline/Lua script when the deployed Redis path is hardened.                                 |
| 5   | MED  | Empty sub-windows are skipped, so `TelemetrySummaryView.windows` is sparse, not fixed-length.                                                                                      | **Intentional** — matches the W0-07 "progression of window-summaries" contract (`FakeSolSystems` likewise returns only non-empty windows). Documented here for the LB-06 ratification. |
| 6   | LOW  | Anchor-timestamp scoping under signal filters, float bucket-boundary rounding, unbatched `_collect` reads.                                                                         | Noted for awareness; non-blocking at current bounded capacity.                                                                                                                         |

Signature of `TelemetryPlumbing.get_telemetry` confirmed to match the W0-07 `SolSystems` Protocol
exactly (param names/order/types + return type).

## Flags for the human

1. **LB-06 not yet a ratified contract.** `TelemetryPacket` is defined locally as the _proposed_ LB-06
   packet format. Per CLAUDE.md §9 the telemetry packet format is a shared contract; it does not yet
   exist in `packages/contracts/`. Recommend a human ratifies the shape and extracts it into the frozen
   contracts (coordinated with Live Bench, per the ticket's "coordinate the packet schema" note).
2. **LNK-03 (ingestion) not present.** This ticket builds the plumbing that ingestion will call
   (`TelemetryPlumbing.ingest`); the actual transport/ingestion entrypoint is a separate ticket.
3. **`external_ref`-only resolution.** Device→entity matching keys on `graph_entity.external_ref`.
   If devices/topics should also match on an `attrs`/`modality_hints` field, that is a small extension
   to `DbEntityResolver`.

## Files

```
packages/api/src/solus_api/graph/__init__.py
packages/api/src/solus_api/graph/packet.py
packages/api/src/solus_api/graph/buffer.py
packages/api/src/solus_api/graph/resolver.py
packages/api/src/solus_api/graph/telemetry.py
packages/api/tests/test_packet.py
packages/api/tests/test_buffer.py
packages/api/tests/test_resolver.py
packages/api/tests/test_telemetry.py
docs/qa/COWORK_QA_SOLUSDEV-111-telemetry-plumbing.md
docs/qa/COMPLETION_SOLUSDEV-111.md
```
