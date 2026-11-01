# Bench view — shared display, derived signals and SOL bench control (SOLUSDEV-319)

Governing decision: ADR-014 amendment 2026-10-31 (plus the 2026-10-30 teleoperation amendment),
ADR-037 live channels. Routes: [docs/api/bench-view.md](../api/bench-view.md). Schema:
[docs/schemas/bench-view.md](../schemas/bench-view.md). Wireflow:
[docs/wireflows/live-bench-view.md](../wireflows/live-bench-view.md).

## 1. Components

```
                    ┌──────────────── solus-api (FastAPI) ─────────────────────────┐
 Renderer           │ livebench/view/                                              │
 features/bench/    │   router.py   GET/PATCH /bench/view ──┐                      │
  view/             │   service.py  BenchViewService ◀──────┤◀── agent/tools/      │
   viewStore.ts ◀── │      lock project row, version check, │    bench_view.py     │
   expression.ts    │      apply ops, inverse ops, events   │    (read / display / │
   (live eval)      │   expression.py  parse + bound + eval │     upsert / delete) │
       ▲            │   ops.py         op + inverse logic   │                      │
       │ SSE hint   │ models.BenchView ── ORM listener ──▶ LiveHub project:{id}    │
       └────────────┤                     bench.view_changed{project_id,version,at}│
                    │ livebench/setpoint.py  SetpointManager ◀── agent/tools/      │
                    │   one move per robot, refusals          bench_control.py     │
                    │        │ (only when app.state.bench_local is not None)       │
                    └────────┼─────────────────────────────────────────────────────┘
                             ▼ optional import (livebench → solus-api arrow)
                    livebench/local.py  setpoint_move(conn, joint, target)
                      └─ Actuator.to_goal (clamp) · step_goals (per-tick limit) · write_goals
```

## 2. Evaluation split

There are exactly two evaluators of the closed grammar (bench-view.md §4), and both are plain
tree-walkers over a parsed AST. **Neither uses `eval`, `exec`, `Function`, `new Function`,
`compile` or any dynamic code path**, and neither accepts anything but the grammar's tokens.

|        | Python — `packages/api/src/solus_api/livebench/view/expression.py`                                                                                                                                                | TypeScript — `apps/desktop/src/renderer/src/features/bench/view/expression.ts`                                             |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Role   | **Write-time authority**: every `upsert_derived` is parsed and bounded here before it is stored; computes `node_count` and `refs`. Evaluates derived values for `bench_view.read` (SOL) over the telemetry buffer | **Live evaluation** of derived signals on the streams the Live Bench already holds; the editor's inline errors and preview |
| Input  | Expression text; per-reference sample arrays from `TelemetryPlumbing` recent buffers (project-scoped)                                                                                                             | Expression text from `GET /view`; the retained device series (`retainedSignals.ts`)                                        |
| Output | AST or `ExpressionError{code, position, length}`; `[(t, value)]`                                                                                                                                                  | Same shapes, camelCase locally                                                                                             |
| Purity | Pure module: no I/O, no globals; filter state lives in an explicit per-evaluation object                                                                                                                          | Pure module: no React, no store access                                                                                     |

**Conformance.** `packages/shared-types/fixtures/bench-expression-vectors.json` holds the shared
vectors: `parse` cases (expression → node count, depth, refs, or error code + position) and
`evaluate` cases (expression + input sample arrays → output samples, including NaN, divide by
zero, hold expiry, out-of-order samples, gaps resetting filters, window caps). The Python suite
and the TypeScript suite both run every vector; a vector added for one evaluator is therefore a
test for both. Outputs compare with relative tolerance 1e-9 and NaN == NaN. The renderer's parser
may be used for early feedback, but **the server's verdict wins**: a client that accepts what the
server refuses shows the server's error.

**Bounded work.** Parse is O(length) with length ≤ 512, the AST is ≤ 64 nodes and ≤ 12 deep
(recursion is bounded by the depth check, applied while parsing, so a hostile `((((…` fails at
depth 13 rather than exhausting the stack). Evaluation per output sample is O(nodes × window) with
window ≤ 2000 samples; ≤ 32 derived signals × ≤ 8 references bounds the renderer's per-frame work.
The server evaluates only on a SOL read, over the buffer's bounded recent window.

**Trust.** Expressions, names and signal names are team-authored data. They are escaped in the
renderer, fenced as data in prompts, and never logged or put in data events. A derived signal can
only reference `(device_id, signal)` pairs; there is no syntax for a derived signal, a file, a
URL or a function outside §4.3.

## 3. Writes, versions and live delivery

`BenchViewService.apply(project_id, actor, role, ops, expected_version | None, undo)` is the only
writer; the router and the SOL tools both call it.

1. Require MEMBER for the acting user (the SOL tools pass the requesting user's role; a viewer's
   SOL turn is refused `unauthorized`).
2. Lock the live `projects` row `FOR UPDATE` (as `save_workspace_layout`), then read the optional
   `bench_views` row; absent = version 0, empty view.
3. If `expected_version` is given and differs: 409 `conflict` with `current_version`. The SOL
   direct tools pass `None` and apply onto whatever is current, under the same lock.
4. Apply ops in order to an immutable copy, collecting inverse ops; parse each expression through
   `expression.py`; enforce entry, group and derived bounds on the result.
5. Write `version + 1`, `updated_by`; emit data events (route doc §8); commit.
6. After commit the ORM listener in `graph/live_publisher.py` (a `_bench_view` derivation beside
   `_layout`) publishes `bench.view_changed`. Renderers with an older version refetch `GET /view`.

## 4. Undo

Undo is not a server-side history. Every write returns its `inverse_ops`; the client that wants to
undo sends them back as an ordinary versioned PATCH with `undo: true`, naming the version the
write produced. If anyone wrote since, the version check refuses (409) and nothing changes: an
Undo can never clobber a teammate's later edit. SOL's direct writes return the same pair in their
tool result; the turn renders it as the change chip, and the click is a **user** REST call with the
user's own auth, so SOL never undoes anything itself. An undo is evented as `bench.view_undo`, not
`bench.view_updated`.

## 5. SOL tools and the gates

- `agent/tools/bench_view.py` registers `bench_view.read`, `bench_view.update_display`,
  `bench_view.upsert_derived` (direct) and `bench_view.delete_derived`
  (`requires_confirmation=True`, preview rows per route doc §6.1).
- `agent/tools/bench_control.py` registers `bench.session_start`, `bench.session_stop` and
  `bench.setpoint`, all `requires_confirmation=True` with `requires_complete_preview` so a card is
  never parked without its rows. `bench.session_start` validates its args with the same
  `BenchSessionIn` model and opens through the same opener path as `POST /sessions` (the model and
  opener move from `bench_router.py` into a shared module both import, so the two can never drift).
- **Guide mode.** `modes.build_mode_dispatch` refuses tools whose descriptor sets
  `requires_confirmation`. The two direct view writes do not, so the bench-view module exports a
  Solus-owned `DIRECT_WRITE_TOOLS` frozenset that the mode wrapper adds to its refused set. No
  model- or fork-supplied metadata can add to it.
- **Stale key.** The confirmation gate compares card rows at park and at decision
  (`confirmations._diverged`). The setpoint's **Current value** row is informational and moves
  constantly; `_diverged` excludes it by exact label, beside the existing `Simulate first`
  exclusion, through a Solus-owned constant set of informational labels. Every other row,
  including the clamped Target, stays in the key.
- No tool starts, steers or stops teleoperation; no tool runs a loop or a command stream.

## 6. Setpoint path

```
SOL proposes bench.setpoint{session_id, joint, target}
  → args validated → preview(): SetpointManager.preview
       resolve session (project-scoped) → refusal checks (§6.2) → read present ticks
       → to_value(present) = Current value; to_goal(target) clamps → to_value(goal) = Target
  → parked card (rows) → user approves → decide re-runs preview (stale if Target changed)
  → SetpointManager.start: reserve the robot (in_flight), re-check refusals under the
    teleop start lock, then local.setpoint_move(conn, address, goal_ticks) as one owned task
  → livebench: each 30 Hz tick write_goals(step_goals({addr: goal}, last, max_step=68))
       until |present − goal| ≤ 2 ticks or 5 s; then hold the last goal (torque stays on)
  → state readable at GET /setpoint; POST /setpoint/stop cancels the task
```

- `SetpointManager` lives in `solus_api/livebench/setpoint.py`, constructed in `main.py` beside
  `TeleopManager` and sharing its session manager, physical device keys and start lock, so
  "teleop running", "robot is a follower", "release in progress" and "setpoint in flight" are
  decided atomically against each other. Teleop start and release stop an in-flight move first;
  a session ending stops it.
- The move runs in the local worker that owns the bus, never in the request: the API request
  returns once the move has started.
- **Torque state.** The livebench `Actuator` protocol (`livebench/hardware/actuation.py`, not a
  `packages/contracts` interface) gains a read of each joint's torque-enable state so `torque_off`
  is decided from the bus, not guessed; drivers without it refuse as `uncalibrated` (no actuator).
- Clamping is the actuator's (`to_goal` clamps into the calibrated span; `write_goals` refuses a
  goal outside it), so a target can never leave the calibrated range even if the API's preview
  were wrong.

## 7. Topology

`app.state.bench_local` exists only where the API runs beside the hardware (the desktop app's
bundled local API). Elsewhere (the hosted API) it is `None`:

| Capability                                               | Local API (bench_local present)      | Hosted API (bench_local None)                                 |
| -------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------- |
| `GET/PATCH /bench/view`, `bench_view.*` tools            | yes                                  | yes (the view is team data, stored in Postgres)               |
| `bench_view.read` values                                 | from this process's telemetry buffer | from this process's buffer (often empty: `latest.value` null) |
| `bench.session_start` / `_stop`                          | yes                                  | refused `source_unavailable` before parking                   |
| `bench.setpoint`, `GET /setpoint`, `POST /setpoint/stop` | yes                                  | refused `unavailable` / 503 `source_unavailable`              |

The tools are always registered so SOL learns the reason instead of not knowing the capability
exists.

## 8. What this does not add

No new contract (the live frame is already in live-events.md), no bridge frame, no simulator or
training interface, no server-side Undo history, no per-user view, no teleop tool, no presence or
co-editing (ADR-037 §7).
