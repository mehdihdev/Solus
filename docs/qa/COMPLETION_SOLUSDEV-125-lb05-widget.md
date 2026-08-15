# Completion report — SOLUS-LB-05 Live Bench widget + telemetry transport (SOLUSDEV-125)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified (backend integration
suite + widget suite green); honors the Aug 6 re-scope in full.

## What was built

**Backend — the first production wiring of LNK-06 + the bench transport**
(`packages/api/src/solus_api/livebench/bench_router.py`, registered in `main.py`; route plan
amended as §13 of `docs/api/API-implementation.md`, tier-1 per ADR-032):

- `POST /projects/{id}/bench/telemetry` — ≤500 LB-06 wire packets + ≤100 observer events per
  batch. Each packet decodes through the ratified `from_wire` (§7 trust boundary): hostile
  packets count `rejected`, unresolved devices count `unresolved`, the batch never 500s on
  content. Requires `member` role.
- `GET /bench/recent/{entity_id}` — `RecentValuesView` (entity verified project-scoped).
- `GET /bench/summary` — W0-07 `TelemetrySummaryView`, bounded duration.
- `GET /bench/events` — bounded per-project observer-event ring (in-memory, ephemeral, like
  the LNK-06 buffer by decision).
- `TelemetryPlumbing` (in-memory buffer + `DbEntityResolver`) + `BenchEventRing` constructed in
  the app lifespan; Redis buffer is a one-line swap when multi-process serving needs it.
- **Isolation proven**: `test_bench_router.py` (10 integration tests) covers auth-failure, both
  outsider directions, foreign-entity-id probes, same-device-id-different-project bleed, and
  hostile-batch survival. Full API suite: 1643 passed, no regressions. OpenAPI + desktop TS
  schema regenerated (`make gen-openapi`).

**Frontend — the self-registering widget** (`apps/desktop/src/renderer/src/widgets/livebench/`):

- `widget.manifest.ts` (`id: 'livebench'`, simulation+runtime, wide/standard) — discovery is
  the CTR-01 glob; no shared file edited. Validated by `collectManifests` in its test.
- `LiveBenchWidget.tsx` — **focused-part scoping** (`focus.entity` names project+entity; no
  global dashboard), live signal tiles, hand-rolled SVG rolling charts with **gap-broken
  polylines** (>3× median dt), observer-event anomaly markers, and a **data-derived stream
  state** (LIVE DATA/STALE/NO STREAM from sample age — never asserted, per SOLUSDEV-152's
  rule; the widget never prints "REAL"). All four CTR-01 render states; a widget-level poll
  (1 Hz) through the typed API client only.
- **Remount-safe** via effect cleanup (interval + in-flight guard) — proven by the
  unmount-stops-polling test; `WidgetLifecycle` hooks deliberately unused (the contract's
  stated default). React 19 strictness held: no setState-in-effect (render-time adjustment
  pattern), no impure render (`Date.now` only in the poll callback), react-refresh-clean.
- 14 widget tests (states, tiles, charts, markers, honesty guard, remount safety, pure helpers).
  Desktop suite: 709 passed. `typecheck:web` + eslint clean.

## Acceptance vs. delivered

Tiles ✅ · rolling charts ✅ · inline observer/anomaly markers ✅ · connection state ✅ (shown as
data freshness + device ids — a SIM/REAL badge would claim knowledge the stream doesn't carry;
judgment noted) · graceful stream gaps ✅ (chart breaks + STALE/NO STREAM) · focused-part
scoping ✅ · `confirmation_refusal` for robot control: no control surface ships in this ticket
(control arrives with RBT-04/LB-03, already gate-bound there).

## Flags for review

- **No wireflow existed** (docs/wireflows is empty) — layout is my judgment within
  `widget.md` + ADR-014; flagged per CLAUDE.md §3, not improvised silently: the STRUCTURE
  (tiles/charts/markers/state) follows the ticket's acceptance list.
- `features/bench/BenchScreen.tsx` deliberately untouched: its honest empty state and
  SOLUSDEV-152 guard test stay exactly as the humans left them; the widget is the live surface
  per the Aug 6 re-scope, and it lights up when the workspace canvas mounts widgets.
- `main.py` gained three lines (imports, two state lines, `include_router`) — the unavoidable
  registration edit, called out here since `main.py` is outside the lane's four paths.
- WS/SSE streaming upgrade deferred per the route plan's later-phases line (documented §13).
