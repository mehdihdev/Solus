# SOLUSDEV-319 — team-shared bench view, derived signals and SOL bench control

**Last updated:** 2026-10-31. Tier-1 route plan (ADR-032). Target design; the completion report
records implementation status.

Authority: ADR-014 amendment 2026-10-31 ("SOL changes Live Bench") and the 2026-10-30
teleoperation amendment, ADR-037 (live channels), ADR-011 (events), ADR-019/026 (budgets).
Architecture: [bench-view.md](../architecture/bench-view.md). Schema:
[bench-view.md](../schemas/bench-view.md). Wireflow:
[live-bench-view.md](../wireflows/live-bench-view.md). Live frame: `bench.view_changed
{project_id, version, at}` in [live-events.md](../contracts/live-events.md). Confirmation cards:
[action-gate.md](../contracts/action-gate.md). Pattern mirrored: the workspace layout
([workspace.md](workspace.md) Phase 1) — one versioned project row, 409 on a stale version, the
project row locked during a save.

All routes use `/api/v1/projects/{project_id}/bench`, the standard envelope and centralized
`ProjectCtx`. No token: 401 `unauthorized`. Not a member of the project's team, or another team's
project: 404 `not_found` (no existence oracle). Reads need any role (viewer included); writes need
MEMBER (viewer: 403 `forbidden`). Client errors are 422 `validation_error`, as for every bench
route; there is no 400.

## 1. Signal identity

A telemetry signal is the pair **(`device_id`, `signal`)** exactly as the packet carries them
(telemetry-packet.md §2: `device_id` 1–512 chars, signal name 1–128 chars). A configured robot's
`device_id` is `<device ref>/<address>` and a ROS `device_id` is a topic name, so **both may
contain `/`**: a single `"device_id/signal"` string cannot be split back unambiguously. Every shape
below therefore carries the pair as two fields, never one joined string.

```
SignalTarget  = {"kind": "signal", "device_id": str, "signal": str}
DerivedTarget = {"kind": "derived", "id": UUID}
Target        = SignalTarget | DerivedTarget
```

Strings in a target or an expression use the **reference charset**: printable ASCII 0x20–0x7E
except `"` and `\`. A signal outside it cannot be referenced (422 `bad_ref`); it still streams and
shows as before. A target naming a signal that is not streaming now is accepted (signals come and
go with sessions); it renders as "no data".

## 2. Read — `GET /view`

Returns the project's view. Before the first write: `{version: 0, display: [], derived: [],
updated_at: null}`.

```json
{
  "data": {
    "version": 7,
    "display": [
      {
        "target": {
          "kind": "signal",
          "device_id": "usb:5A7A/3",
          "signal": "shoulder_lift.position"
        },
        "pinned": true,
        "hidden": false,
        "order": 0,
        "unit": "rad",
        "limits": { "min": -1.6, "max": 1.6 },
        "plot_group": "Shoulder"
      }
    ],
    "derived": [
      {
        "id": "0b9f…",
        "name": "Lift error",
        "expression": "sig(\"usb:5A7A/3\", \"shoulder_lift.goal\") - sig(\"usb:5A7A/3\", \"shoulder_lift.position\")",
        "unit": "deg",
        "node_count": 3,
        "refs": [
          { "device_id": "usb:5A7A/3", "signal": "shoulder_lift.goal" },
          { "device_id": "usb:5A7A/3", "signal": "shoulder_lift.position" }
        ],
        "created_at": "…",
        "updated_at": "…"
      }
    ],
    "updated_at": "2026-10-31T21:04:11Z"
  }
}
```

- `display[]` (≤ 512) holds only targets with a non-default setting; a target absent from it
  shows with defaults (not pinned, not hidden, natural order, packet unit, autoscaled axis, no
  group). Field meanings:
  - `pinned` — shown in the pinned strip above the robot panels.
  - `hidden` — not shown as a card; listed under "Hidden signals".
  - `order` — integer 0–1023; cards sort pinned first, then by `order`, then natural order.
  - `unit` — display unit (≤ 32 chars). The renderer converts only within a unit family
    (`signalUnits.ts`); a unit the packet's unit cannot convert to falls back to the packet unit.
  - `limits` — `{min, max}` fixed y-axis range, both finite, `min < max`, |value| ≤ 1e12.
    Display only: not an alarm, not an actuation bound.
  - `plot_group` — 1–64 chars of the reference charset, or null. Targets sharing a group are
    overlaid on one chart. At most 16 distinct groups, at most 8 targets per group.
- `derived[]` (≤ 32) — `refs` and `node_count` are computed by the server from the parsed
  expression; a client never supplies them. `name` is 1–64 printable chars, unique in the project
  (case-insensitive). `unit` is ≤ 32 chars or null.
- Display strings, names and expressions are team-authored data: the renderer escapes them and
  SOL reads them fenced as data (CLAUDE.md §7).

## 3. Write — `PATCH /view`

Body (strict, unknown fields rejected at every level):

```
{ "version": int >= 0,          // the version the client last saw
  "ops": Op[1..32],
  "undo": bool = false }        // true only when ops are a returned inverse_ops (Undo)
```

### 3.1 Op schema (frozen)

```
SetDisplay = {"kind": "set_display", "target": Target,
              "patch": {"pinned"?: bool, "hidden"?: bool, "order"?: int 0..1023|null,
                        "unit"?: str|null, "limits"?: {"min": float, "max": float}|null,
                        "plot_group"?: str|null}}          // patch has >= 1 field
UpsertDerived = {"kind": "upsert_derived", "id"?: UUID, "name": str, "expression": str,
                 "unit"?: str|null}
DeleteDerived = {"kind": "delete_derived", "id": UUID}
```

- `set_display` merges `patch` into the target's entry; `null` resets that field to its default (every patch field accepts `null`; for `pinned`/`hidden` that is `false`).
  An entry left all-default is removed. A `DerivedTarget` must name a derived signal that exists
  after the preceding ops of the same request (404 `not_found` otherwise).
- `upsert_derived` with no `id`, or with an `id` not in the view, **creates** (the server
  generates the id when absent; a supplied id is how Undo restores a deleted signal under its old
  identity). With an existing `id` it **replaces** name, expression and unit. The expression is
  parsed and bounded (§4) before anything is stored.
- `delete_derived` removes the signal and every display entry targeting it. Unknown id: 404.
- Ops apply in order, atomically: any failure leaves the view unchanged and returns the error for
  the first failing op. One request increments `version` by exactly 1.

### 3.2 Response

```
{ "version": int, "view": <GET /view data>, "inverse_ops": Op[] }
```

`inverse_ops` restore the prior state when sent back as `PATCH {version: <returned version>,
ops: inverse_ops, undo: true}`: a `set_display` with the prior value of each patched field (null
where it was default); `delete_derived` for a creation; `upsert_derived` with the prior id, name,
expression and unit for a replacement or a deletion, followed by the `set_display` ops that
restore the deleted signal's display entries. Inverse ops are listed in reverse application order
and never exceed 64 (a request that would need more is refused 422 `too_many_ops`).

### 3.3 Errors (in check order)

| Status | code                                                        | When                                                                                            |
| ------ | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 401    | `unauthorized`                                              | No or invalid token                                                                             |
| 404    | `not_found`                                                 | Not a member / another team's project                                                           |
| 403    | `forbidden`                                                 | Viewer                                                                                          |
| 429    | `rate_limited`                                              | Over 120 PATCH requests a minute per user                                                       |
| 422    | `validation_error`                                          | Body shape: unknown field, > 32 ops, empty patch, bad target, bound exceeded                    |
| 409    | `conflict`                                                  | `version` is not the current version. `details: [{"current_version": int}]`. Nothing is written |
| 422    | `expression_error`                                          | An expression failed to parse or exceeded a bound (§4.4)                                        |
| 422    | `too_many_derived` / `too_many_entries` / `too_many_groups` | The result would exceed 32 derived, 512 display entries, 16 groups or 8 targets in a group      |
| 422    | `duplicate_name`                                            | Two derived signals would share a name                                                          |
| 404    | `not_found`                                                 | An op names a derived id that does not exist (checked as ops apply)                             |

`expression_error` details: `[{"op_index": int, "code": str, "position": int, "length": int,
"message": str}]`. `position` is a 0-based character offset into that op's `expression`, `length`
≥ 0 the span; `message` is a fixed sentence per code and never echoes the expression.

### 3.4 Transaction, live frame and rate limit

The service locks the live project row (`SELECT … FOR UPDATE`, as `save_workspace_layout`) before
reading the optional `bench_views` row, so two first writes cannot both succeed; it compares the
version, applies the ops, flushes and commits. The `bench.view_changed {project_id, version, at}`
hint on `project:{id}` is derived by the live publisher's ORM listener from the committed row
(as `layout.changed`), queued on the session and flushed only after commit; a rollback discards
it and a publish failure never fails the request. The frame carries no content: clients refetch
`GET /view` when its `version` is newer than theirs. Rate limit: per user, 120 PATCH a minute
(drag-reorder sends one PATCH per drop); GET is unlimited beyond the global limiter.

## 4. Expression grammar

### 4.1 Choice of the signal reference form

`sig("<device_id>", "<signal>")` — a call with two string literals. A single joined string fails
on `/` inside `device_id` (§1); a bracket form (`[device/signal]`) has the same split problem
plus a second quoting scheme. The call form reuses the grammar's one call production, keeps the
pair explicit, and needs no escape sequences because the reference charset excludes `"` and `\`.

### 4.2 EBNF (frozen)

```ebnf
expression = ws, sum, ws ;
sum        = product, { ws, ( "+" | "-" ), ws, product } ;
product    = unary,   { ws, ( "*" | "/" ), ws, unary } ;
unary      = "-", ws, unary | primary ;
primary    = number | reference | call | "(", ws, sum, ws, ")" ;
reference  = "sig", ws, "(", ws, string, ws, ",", ws, string, ws, ")" ;
call       = function, ws, "(", ws, sum, { ws, ",", ws, sum }, ws, ")" ;
function   = "abs" | "min" | "max" | "clamp" | "scale"
           | "ma" | "lowpass" | "deriv" | "integ" ;
number     = ( digits, [ ".", [ digits ] ] | ".", digits ), [ exponent ] ;
exponent   = ( "e" | "E" ), [ "+" | "-" ], digits ;
digits     = digit, { digit } ;
string     = '"', strchar, { strchar }, '"' ;
strchar    = ? printable ASCII 0x20–0x7E except '"' and '\' ? ;
ws         = { " " | "\t" | "\n" } ;
```

Operator precedence and associativity follow the productions: unary minus binds tightest, then
`*` `/`, then `+` `-`, all binary operators left-associative. There are no variables, no strings
outside `sig`, no comparison or boolean operators, no user-defined functions, no reference to a
derived signal (there is no syntax for one, so derived-of-derived cannot be written in v1), and no
`eval`/`Function`/`exec` anywhere.

### 4.3 Functions (frozen)

| Function                                 | Arity | Meaning                                                                         |
| ---------------------------------------- | ----- | ------------------------------------------------------------------------------- |
| `abs(x)`                                 | 1     | absolute value                                                                  |
| `min(a, b, …)` / `max(a, b, …)`          | 2–8   | smallest / largest argument                                                     |
| `clamp(x, lo, hi)`                       | 3     | `min(max(x, lo), hi)`; NaN when `lo > hi`                                       |
| `scale(x, in_lo, in_hi, out_lo, out_hi)` | 5     | linear map, not clamped; the four range args are **constants**, `in_lo ≠ in_hi` |
| `ma(x, window_s)`                        | 2     | moving average over the trailing window                                         |
| `lowpass(x, cutoff_hz)`                  | 2     | first-order low-pass                                                            |
| `deriv(x)`                               | 1     | first derivative per second                                                     |
| `integ(x, window_s)`                     | 2     | trapezoidal integral over the trailing window (unit·s)                          |

A **constant** is a number literal optionally preceded by unary minus. `window_s` is a constant in
(0, 10]; `cutoff_hz` a constant in (0, 1000]. Filters keep per-node state; filter arguments may
themselves contain filters (bounded by §4.4).

### 4.4 Bounds and error codes (frozen)

| Bound                                                                                    | Limit                                                           | `code`                                              |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| Expression length                                                                        | ≤ 512 characters                                                | `too_long`                                          |
| Nodes (each number, reference, unary op, binary op and call is one; parentheses are not) | ≤ 64                                                            | `too_many_nodes`                                    |
| Depth (root = 1)                                                                         | ≤ 12                                                            | `too_deep`                                          |
| Distinct `(device_id, signal)` references                                                | 0–8 (0 = a constant signal, §4.6)                               | `too_many_refs`                                     |
| Number literal                                                                           | ≤ 32 chars, finite after parsing                                | `non_finite_literal`                                |
| Filter window                                                                            | ≤ 10 s and ≤ 2000 samples (the evaluator keeps the newest 2000) | `param_range`                                       |
| Reference strings                                                                        | reference charset; `device_id` 1–512, `signal` 1–128            | `bad_ref`                                           |
| Function name / arity / constant-only argument                                           | §4.3                                                            | `unknown_function` / `arity` / `non_constant_param` |
| Anything else that does not match §4.2                                                   | —                                                               | `syntax`                                            |
| Derived signals per project                                                              | ≤ 32                                                            | `too_many_derived` (§3.3)                           |

### 4.5 Evaluation semantics (frozen; both evaluators)

- **Numbers.** IEEE-754 double. Any operation whose result is not finite yields NaN; `x / 0`
  (including `0 / 0`) is NaN. Arithmetic, `abs`, `min`, `max`, `clamp` and `scale` propagate NaN:
  any NaN argument gives NaN.
- **Time base.** Output samples are taken at the timestamps of the **first reference in source
  order** (the primary input). Primary samples are ordered by timestamp; a sample whose timestamp
  is not strictly greater than the previous one is dropped. Every other reference is read by
  **sample-and-hold**: its latest sample with timestamp ≤ t, or NaN when it has none, or when that
  sample is more than 1.0 s older than t. Timestamps are seconds (float) on the packet's wall clock.
- **Filters** run over their argument evaluated at the output timestamps. NaN samples are skipped
  by `ma` and `integ` (not counted); `lowpass` outputs NaN for a NaN sample and keeps its state;
  `deriv` uses the previous finite sample.
  - `ma(x, w)`: arithmetic mean of finite samples with timestamp in (t − w, t], newest 2000 at
    most, summed oldest→newest; NaN when there are none.
  - `lowpass(x, fc)`: RC = 1/(2π·fc); first sample y = x; then α = dt/(RC + dt),
    y = y_prev + α·(x − y_prev).
  - `deriv(x)`: (x − x_prev)/(t − t_prev); NaN on the first sample.
  - `integ(x, w)`: trapezoid sum over consecutive finite samples in (t − w, t], oldest→newest;
    0.0 with fewer than two.
- **Gaps.** When consecutive output timestamps are more than a filter's reset window apart, that
  filter's state is cleared and the sample is treated as its first. Reset window: `w` for `ma` and
  `integ`; min(10 s, 5·RC) for `lowpass`; 1.0 s for `deriv`.
- **Determinism.** Windowed sums are recomputed per output sample in the stated order (no running
  sums), so a batch evaluation and an incremental evaluation over the same samples give identical
  results. The shared vectors (`packages/shared-types/fixtures/bench-expression-vectors.json`)
  are compared with relative tolerance 1e-9; NaN must equal NaN.
- **Output** NaN renders as a gap, never as zero.

### 4.6 Constant derived signals (SOLUSDEV-319 amendment: constant derived signals)

An expression with **zero** references — a literal such as `10` or `-2.5`, or constant
arithmetic such as `2*5` or `(1+2)/3` — is valid and defines a **constant signal**. Its `refs` is
`[]`; `node_count` and `depth` count as usual. The former `no_signal` error code is **removed**:
no input is rejected for having no reference.

- **Time base.** With no primary reference, the output timestamps come from the evaluator's
  caller instead. The batch evaluators (Python `evaluate`, TypeScript `evaluateExpression`) take
  an optional time base `timestamps`: one output sample per timestamp, with the primary drop rule
  (non-finite or not strictly greater than the previous accepted timestamp is dropped). Without a
  time base they return a single sample at the evaluation time `at` (default: the current wall
  clock, in seconds). The incremental evaluators take time-base timestamps through `tick(…)`. A
  time base passed for an expression that has references is ignored (the primary reference is
  the time base, §4.5).
- **Filters** over a constant are allowed and follow §4.5 unchanged on that time base (so
  `ma(10, 1)` is 10, `deriv(5)` is NaN then 0, and gaps reset filters as usual).
- **Where it is evaluated.** The renderer evaluates a constant once per poll on the bench clock
  (architecture/bench-view.md §2), giving a flat line and a current value; `bench_view.read`
  evaluates it at read time, so `latest` is `{value: <constant>, at: <read time>}`.
- The shared vectors pin these rules (`evaluate` cases carry `timestamps` or `at`).

## 5. Setpoint move state — `GET /setpoint`, `POST /setpoint/stop`

A setpoint is only ever started through the SOL confirmation gate (§6); these two routes let the
Live Bench show it and stop it.

- `GET /setpoint` (any role): `null`, or `{id, session_id, robot, joint, unit, target, state:
"moving"|"reached"|"timed_out"|"stopped"|"failed", started_at, ended_at}` for the project's most
  recent move. Live Bench polls it while a move is in flight.
- `POST /setpoint/stop` (MEMBER, never rate-limited — it is a safety control): stops the in-flight
  move; the joint holds its last goal with torque on. Idempotent; returns the state. No local
  bench on this server: 503 `source_unavailable`.

## 6. SOL tools

Every tool is an in-process tool built per turn with the requesting user's identity and role; a
tool run by a viewer returns `unauthorized` before touching anything. Arguments are validated
against the descriptor schema before preview, park or execution (confirmations.py SEC-H3).
Results, names and expressions reach the model as fenced data. Guide action mode refuses every
tool below except `bench_view.read` (the direct writes are not `requires_confirmation`, so the
mode wrapper's mutating set must name them explicitly; see the architecture doc).

| Tool                        | Args                                                  | Confirmation | Result                                                                                                                                  |
| --------------------------- | ----------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `bench_view.read`           | `{include_values?: bool = true}`                      | no           | GET /view data; with values, each derived entry adds `latest: {value: float\|null, at}` evaluated server-side over the telemetry buffer |
| `bench_view.update_display` | `{ops: SetDisplay[1..32]}`                            | no (direct)  | `{version, inverse_ops, summary}`                                                                                                       |
| `bench_view.upsert_derived` | `{id?, name, expression, unit?}`                      | no (direct)  | `{version, id, node_count, inverse_ops, summary}`; `expression_error` → `invalid_args` with the codes and positions                     |
| `bench_view.delete_derived` | `{id}`                                                | **yes**      | `{version, inverse_ops}`                                                                                                                |
| `bench.session_start`       | `BenchSessionIn` (the exact body of `POST /sessions`) | **yes**      | the session record                                                                                                                      |
| `bench.session_stop`        | `{session_id}`                                        | **yes**      | the session record                                                                                                                      |
| `bench.setpoint`            | `{session_id, joint, target}`                         | **yes**      | `{id, state, target, clamped}`                                                                                                          |

Direct writes apply against the current version under the project lock (SOL does not pass a
version), so they never 409; the returned `version` + `inverse_ops` are what the turn's change
chip uses for Undo (§7). `summary` is a Solus-composed one-line description for the chip ("Pinned
2 signals", "Created derived signal ‹name›").

### 6.1 Card rows (`preview`, label → before / after)

- `bench_view.delete_derived`: **Derived signal** ‹name› → —; **Expression** ‹expression, single
  line, capped› → —; **Shown in** "‹n› display settings" → "removed".
- `bench.session_start`: **Action** — → "Start session"; **Source** — → provider; **Mode** — →
  sim/real; **Robot** or **Device** or **Simulator** — → the same label `POST /sessions` would
  give; **Window** — → "‹n› s". Refused before parking with the route's own errors
  (`source_unavailable`, `not_found`, `validation_error`, `too_many_sessions`).
- `bench.session_stop`: **Action** — → "Stop session"; **Session** ‹label› → "stopped";
  **Provider** ‹provider› → —. Refused: `not_found`, `session_starting`.
- `bench.setpoint`:

  | label         | before | after                                                                             |
  | ------------- | ------ | --------------------------------------------------------------------------------- |
  | Robot         | —      | session label (robot name)                                                        |
  | Joint         | —      | the joint's signal name, e.g. `shoulder_lift.position`                            |
  | Current value | —      | e.g. "12.4 deg" — **informational**: excluded from the stale-divergence key       |
  | Target        | —      | e.g. "40.0 deg", or "95.0 deg (requested 120.0 deg, clamped to calibrated range)" |
  | Motion        | —      | "One move, at most ‹step› per tick; ends at the target or after 5 s"              |

  `joint` is the actuated joint's signal name (the `ActuatedJoint.signal` of that session's
  robot); `target` is a finite number in the joint's calibrated unit. The worker converts it with
  `Actuator.to_goal`, which clamps into the calibrated span; the card shows the clamped value back
  through `to_value`, so the Target row is what will be commanded. A change in calibration between
  park and approval changes the Target row and makes the card stale.

### 6.2 Setpoint refusals (frozen codes)

Checked at preview (nothing is parked) and again at decision time (nothing moves). The tool error
is `unavailable` (`invalid_args` for `uncalibrated`), and its message begins `setpoint refused
(<code>):` followed by a fixed sentence.

| code            | When                                                                                    |
| --------------- | --------------------------------------------------------------------------------------- |
| `unavailable`   | This API has no local bench (`app.state.bench_local is None`)                           |
| `not_connected` | The session is not active, or its robot's link is open but not attached right now       |
| `teleop_active` | A teleoperation is running or starting in this project                                  |
| `follower`      | The robot is the follower of a running teleoperation (any project; physical device key) |
| `uncalibrated`  | The joint has no calibrated span, or the session's driver has no actuator               |
| `torque_off`    | The joint's torque is off (the robot was released); SOL never turns torque on           |
| `in_flight`     | A setpoint move is already running on this robot                                        |

Unknown session or joint: `not_found`. The move itself: one bounded move from the present position
toward the goal, at most `DEFAULT_MAX_STEP_TICKS` (68 ticks) per 30 Hz tick, ending when the
present position is within 2 ticks of the goal (`reached`) or after 5 s (`timed_out`); the joint
holds its last goal either way. A teleop start, a session stop, a release or `POST
/setpoint/stop` ends the move (`stopped`). There is no teleop tool, no loop tool and no tool that
streams commands.

Rate limit: 30 setpoint executions a minute per user (shared limiter with teleop drives).

## 7. Undo

Undo is a user action over REST. The change chip holds the tool result's `version` and
`inverse_ops` and sends `PATCH /view {version, ops: inverse_ops, undo: true}`. A teammate's (or a
later SOL) edit in between makes it 409 `conflict`; the chip then reads "View changed since — Undo
unavailable" and nothing is written. Undo is offered for the direct SOL tools and for the user's
own last edit in the view editor; an Undo is itself a normal versioned write (its response carries
inverse ops, so Redo is possible but not surfaced in v1).

## 8. Data events (ADR-011)

Payloads never carry expressions, names, signal names, device ids or values.

| Event                                                    | Payload                                                                                                                                  | Emitted                                                                |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `bench.view_updated`                                     | `{actor: "user"\|"sol", op_kinds: str[] (distinct, sorted), version}`                                                                    | every successful non-undo write                                        |
| `bench.derived_signal_created` / `_updated` / `_deleted` | `{count, node_count}` — `count` = derived signals in the project after the write; `node_count` of the affected expression (0 for delete) | once per derived op                                                    |
| `bench.view_undo`                                        | `{version}`                                                                                                                              | a successful write with `undo: true` (instead of `bench.view_updated`) |
| `bench.setpoint_requested`                               | `{unit, clamped: bool, code: null}`                                                                                                      | a setpoint card parked                                                 |
| `bench.setpoint_applied`                                 | `{unit, clamped: bool, code: null}`                                                                                                      | the move started after approval                                        |
| `bench.setpoint_refused`                                 | `{unit: str\|null, clamped: bool\|null, code}`                                                                                           | any §6.2 refusal, at preview or decision                               |

`bench.session_started` / `bench.session_stopped` keep their payloads and add `actor: "sol"` when a
SOL tool started or stopped the session (additive field).
