# LiveConnection — Design Contract (MCP-02)

> **Final home: `docs/contracts/live-connection.md`** — this temp file is the paste source; a human moves it there.

**Status:** Design contract + `LiveConnection` ABC + a `NoopLiveConnection` roster placeholder + a
reusable conformance suite. Formalizes the streaming sibling that W0-05 §1 documented but did not
build. The real live sources (ROS, serial, Foxglove, sim), the transport plumbing, and the Live
Bench UI are separate tickets.
**Authority:** CLAUDE.md §1 (Live Bench is the runtime surface) + §7 (telemetry-untrusted +
prompt-injection security), ADR-014/ADR-029 (Live Bench, runtime data is untrusted input to the
model layer), ADR-030 (the boundary clause: live runtime data flows through `LiveConnection`,
never the `Connector` sync path — parsing exports ≠ streaming runtime), W0-05
(`docs/contracts/connector-interface.md` §1 — the sibling hierarchy), W0-07
(`docs/contracts/sol-interface.md` §4 — the windowed telemetry shapes, reused as-is). Code:
`packages/api/src/solus_api/connectors/live.py`, `live_conformance.py`.

Consumers: **CON-03** (the live transport/Foxglove bridge wiring), **LB-01/LB-02** (Live Bench
Sim/Real modes consuming the stream), **LNK-06** (graph telemetry plumbing — buffers/summarizes
what a `LiveConnection` delivers), **LB-06** (the telemetry packet-format contract upstream of
window summarization). This contract is what those tickets implement against.

---

## 1. Position in the hierarchy — the DISTINCT sibling

```
Integration (conceptual parent, W0-05 §1)
  Connector        — design-artifact branch: SYNCS committed exports into the graph
  LiveConnection   — THIS contract: STREAMS live runtime data (telemetry, sim state)
```

`LiveConnection` is an `abc.ABC`, **distinct from `Connector`** — it has no `sync`, no
`detect_changes`, and never ingests design artifacts. The ADR-030 boundary clause is binding both
ways: design artifacts ride the `Connector` sync path; live runtime data (telemetry, Sim/Real
scene state) rides a `LiveConnection`. Gazebo, Isaac Sim, Foxglove, and a real-robot serial/ROS
link are `LiveConnection`s, not `Connector`s.

Like `Connector`, each implementation carries a `provider: ClassVar[str]` roster identity
(e.g. `"ros"`, `"serial"`, `"foxglove"`, `"noop"`).

---

## 2. The four operations — the complete surface

```python
LiveConnection(abc.ABC):                 # packages/api/src/solus_api/connectors/live.py
    provider: ClassVar[str]

    async def subscribe(self, window: TelemetryWindow) -> str: ...
    def on_batch(self, handle: str, callback: BatchCallback) -> None: ...
    async def unsubscribe(self, handle: str) -> None: ...
    def status(self) -> LiveStatus: ...
```

- **`subscribe(window)`** starts a subscription batching the stream per `window` (the W0-07
  `TelemetryWindow`: `duration_seconds` + optional `signals` narrowing) and returns an **opaque
  `str` handle**.
- **`on_batch(handle, callback)`** registers the consumer's async callback for the subscription's
  completed windows. **One callback per handle** — registering again replaces it; a second
  consumer makes a second subscription. Unknown handle → `KeyError`.
- **`unsubscribe(handle)`** stops the subscription: no delivery to its callback after it returns.
  Unknown handle → `KeyError`.
- **`status()`** reports the lifecycle state (§5).

`BatchCallback = Callable[[TelemetryWindowSummary], Awaitable[None]]` — called once per
**completed** window.

---

## 3. Emissions — batch-summarized windows, NEVER a raw-sample firehose

The W0-07 shapes are **reused as-is from `solus_api.agent.interfaces`, never redefined**:

| shape                    | role here                                                                    |
| ------------------------ | ---------------------------------------------------------------------------- |
| `TelemetryWindow`        | the subscription's window spec (`duration_seconds > 0`, optional `signals`)  |
| `TelemetryWindowSummary` | the emitted payload — one per completed window                               |
| `raw_ref: ArtifactRef`   | the ONLY path to raw data (W0-04 `ArtifactRef`, referenced — fetched lazily) |

This is the edge-observer principle (`sol-interface.md` §4): telemetry is high-volume, so
consumers get bounded, batch-summarized windows — a progression of `TelemetryWindowSummary`, not
instants. **No API on this interface exposes per-sample or raw streaming.** Raw bytes are only
ever REFERENCED via `raw_ref` and fetched when a step genuinely needs them. The streaming
extension W0-07 designed for ("a continuous stream of `TelemetryWindowSummary` as windows
complete") is exactly what `on_batch` delivers — same shape, no contract change.

---

## 4. HARD RULE (Pattern 2) — telemetry is NEVER forced through an MCP tool interface

A `LiveConnection` is a streaming seam, **not a tool**. It must not satisfy the W0-04 `Tool`
protocol (`descriptor` property + `invoke` coroutine), and `live.py` imports nothing MCP. High-
frequency runtime data through a request/response tool interface would recreate the raw-firehose
problem inside the agent loop and hand stream contents a tool-shaped path into orchestration.

This is enforced **mechanically**: `assert_live_connection_contract` asserts the instance does
NOT have the `Tool` surface, and the test suite proves the check catches a violating
implementation. SOL reaches summarized telemetry through the W0-07 `SolSystems.get_telemetry`
seam — never by invoking a live connection as a tool.

---

## 5. Status — the `LiveStatus` lifecycle

```python
LiveStatus(enum.StrEnum):
    DISCONNECTED = "disconnected"  # no live link to the runtime source
    CONNECTED = "connected"        # link established / subscriptions active, no windows yet
    STREAMING = "streaming"        # completed windows are being delivered
```

Sanity invariants (conformance-checked): `status()` always returns a `LiveStatus`; an active
subscription implies the status is not `DISCONNECTED`; delivery is reflected as `STREAMING`.

---

## 6. Credentials (real implementations)

Exactly the W0-05 channel and nothing else: a **`secret_ref` resolved through the secret store**
is the ONLY way a live source obtains credentials — never plaintext config, never code, never
logs, never any API response (CLAUDE.md §7, `connector-interface.md` §2). The `NoopLiveConnection`
needs none; this ticket builds no credential code.

---

## 7. Security (binds this contract — ADR-029, CLAUDE.md §7)

- **Telemetry is UNTRUSTED input to the model layer.** Every string a `TelemetryWindowSummary`
  carries (`summary`, `anomalies`, signal names/values) is device- or sim-influenced. Downstream
  prompt assembly wraps it as delimited DATA to be analyzed, never as instructions to follow.
- **Device input is parsed defensively upstream** (LNK-06/LB-06): bounded message sizes, bounded
  signal counts, finite values — a malformed or hostile stream never crashes the service.
- **No elevation:** a live connection is team-scoped like every other source; its data enters
  model context only through the same team-scoping layer as every query.

---

## 8. The `NoopLiveConnection` + the conformance suite

`NoopLiveConnection` is the roster placeholder and conformance target: connects to nothing,
accepts subscriptions, emits nothing on its own. Its test-only `feed(summary)` injects a
completed window so delivery is provable; real implementations produce windows from their own
stream and do not expose it.

`assert_live_connection_contract(conn, *, emit, window=None)` is the package-importable suite
every implementation's test runs (mirroring `assert_connector_contract`). `emit` is the
test-side driver that causes one window to complete. The suite asserts: the Pattern-2
not-a-Tool rule (§4); `subscribe` returns a non-empty `str` handle; delivered payloads are
`TelemetryWindowSummary` instances (never raw samples); no delivery after `unsubscribe`; and the
§5 status invariants. Deliberately-broken implementations (a Tool-shaped one, a leaky
unsubscribe, a raw-sample emitter) FAIL it — the suite is not a rubber stamp.

---

## 9. Functional vs. future in MCP-02

| Component                                                        | MCP-02 status                    |
| ---------------------------------------------------------------- | -------------------------------- |
| `LiveConnection` ABC (subscribe/on_batch/unsubscribe/status)     | **Functional**                   |
| `LiveStatus` + `BatchCallback`                                   | **Functional**                   |
| `NoopLiveConnection` + `assert_live_connection_contract`         | **Functional**                   |
| Real live sources (ROS, serial, Foxglove, sim)                   | **Separate tickets (CON-03, …)** |
| Transport plumbing / Live Bench UI consumption                   | **LB-01 / LB-02**                |
| Raw-sample → window summarization upstream                       | **LNK-06 (shipped) / LB-06**     |
| Credential wiring (`secret_ref` → secret store) for live sources | **With the first real source**   |

---

**Cross-references:** CLAUDE.md §1 + §7, ADR-014/ADR-029 (Live Bench; telemetry untrusted),
ADR-030 (boundary clause), W0-04 (`ArtifactRef` reuse; the `Tool` protocol this must NOT
satisfy), W0-05 (`docs/contracts/connector-interface.md` — the sibling hierarchy + the
`secret_ref` credential channel), W0-06 (`SourceRef` — not referenced by this contract; signal→
entity identity is LNK-06's resolver, keyed on `graph_entity.external_ref`), W0-07
(`docs/contracts/sol-interface.md` §4 — `TelemetryWindow`/`TelemetryWindowSummary` reused as-is).
Code: `packages/api/src/solus_api/connectors/live.py`, `live_conformance.py`,
`packages/api/tests/test_live_connection.py`. Downstream: CON-03, LB-01, LB-02, LNK-06, LB-06.
