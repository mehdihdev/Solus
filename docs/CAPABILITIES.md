# Capability audit — what this repo actually does

**Date:** 2026-08-15 · **Branch:** `SOLUSDEV-69-integration-lane-orgy` · **Box:** `bee-dgx`, aarch64

Every line below is classified from something I ran on this machine. Completion reports, ticket
text and green tests are **not** evidence here — three shipped bugs in this repo were green on all
three while the product was broken. Where I could not execute, the entry says UNVERIFIED and names
the missing piece.

|                      | Meaning                                               |
| -------------------- | ----------------------------------------------------- |
| **WORKS**            | Ran it; evidence pasted                               |
| **WORKS-WITH-SETUP** | Runs after specific steps, given in `RUNBOOK.md`      |
| **BUILT-UNVERIFIED** | Code exists, could not execute — the blocker is named |
| **BROKEN**           | Ran it, it failed; error pasted                       |
| **NOT BUILT**        | No implementation                                     |

---

## Headline: SOL answers from your project — grounding FIXED (SYS-04, 2026-08-15)

**Classification: WORKS (grounding fixed by `agent/feeds.py` — see the end of this section)**

The findings below are the 2026-08-14 snapshot that motivated the fix, kept for the record.

The provider error you hit was a missing step, not a bug — `scripts/seed-provider-keys.py` exists
and nothing had ever run it. After seeding, a real turn completes:

```
$ uv run python scripts/seed-provider-keys.py --only anthropic
backend: LocalEncryptedSecretStore
  anthropic_api_key    stored (108 chars)
```

A live turn against project `01a0055b-…` streamed 13 SSE `token` events, a `message` and a `done`,
in Guide mode, with citations. But look at **what it said**:

> **LM358** — a dual op-amp… Its datasheet notes it runs on a single supply between 3–32V
> `[datasheet:lm358.pdf#p1]`. **C1** — a 100nF capacitor… The graph explicitly records that
> relationship: `LM358 -[soldered_to]-> C1`. A **ROS node called `camera_node`**, which publishes
> an `/image_raw` topic at 30Hz `[ros:camera_node]`.

None of that is in your database:

```sql
select count(*) from graph_entity where name ilike '%lm358%' or name ilike '%camera_node%';
 0
```

Your project's 243 entities are a **Kinova Gen3 arm** from Onshape:

```
part | GEN3_6DOF_SPHERICAL_VISION_V01 <1>
part | GEN3 SIMPLIFIED BASE
part | GEN3 SIMPLIFIED SHOULDER
part | KR10643
```

The source was `agent/fake_systems.py` — it contained `relation_type="soldered_to"` and
`chunk="camera_node publishes /image_raw at 30Hz"` verbatim, wired as `app.state.sol_systems`
in production. A real Anthropic model reasoned fluently over **fabricated project context** and
presented it as yours, with citations to documents that did not exist — the
confident-wrong-answer failure class, invisible from the outside: the stream, the citations and
the mode-switching all looked right.

**The fix (SYS-04, SOLUSDEV-138).** `agent/feeds.py` (`DbSolSystems`) implements the W0-07
`SolSystems` Protocol against the real subsystems — `load_neighborhood`/`to_graph_context` for
graph context (degree clamped to 2, `domains` filtered in-query), `TelemetryPlumbing` for
telemetry, SYS-02 `rag/retrieval.py` for RAG/error history/the flywheel — and `main.py` wires it
in production. The fake now lives in `tests/fixtures/`, and a ratchet
(`test_feeds.py::test_fake_sol_systems_is_banished_from_production`) keeps every reference out of
`src/` forever. Every feed is project-scoped in the query; a feed with no data returns an honest
empty, never invented content.

**Verified live (2026-08-15)**, same project, same question class: the turn streamed 4 real tool
calls (`onshape.list_documents`, `onshape.list_elements` ×2, `onshape.get_assembly_definition`,
all `ok`) and the answer described the actual Kinova Gen3 assembly — `Base_assembly`,
`GEN3_SIMPLIFIED_SHOULDER-86587__ASM`, `Kinova_link1–4`, the Robotiq 2F-85 gripper — with zero
mentions of the LM358/`camera_node` fictions. Turns persisted; no `error` frames.

---

## Live Bench — telemetry · **WORKS**

Ingest, resolution to a graph entity, read-back, windowed summary, observer events, and tenant
isolation all verified against the running API.

```
POST /bench/telemetry   -> {"data":{"accepted":1,"unresolved":0,"rejected":0}}

GET  /bench/recent/{id} -> {"entity_id":"01a0055e-…","signals":[
      {"signal":"temp_c","points":[{"timestamp":"2026-08-15T15:00:00Z","value":41.5}]},
      {"signal":"rpm","points":[{"timestamp":"2026-08-15T15:00:00Z","value":120.0}]}]}

GET  /bench/summary?duration_seconds=3600 ->
      {"windows":[{"window_start":"2026-08-15T14:50:00Z","summary":"2 signal(s), 2 sample(s)",
       "signals":{"temp_c":{"mean":41.5,"min":41.5,"max":41.5,"last":41.5,"count":1.0},
                  "rpm":{"mean":120.0,…}}}]}

POST events + GET /bench/events ->
      [{"kind":"threshold_breach","signal":"temp_c","at":"2026-08-15T15:01:00Z",
        "value":95.0,"detail":{"limit":80}}]
```

**Cross-tenant isolation — verified.** A second, freshly provisioned user asking for user 1's
project gets 404 on both the telemetry summary and the project itself:

```
recent  -> HTTP 404
project -> HTTP 404   {"error":{"code":"not_found","message":"Project not found"}}
```

Not a 403 (which would confirm the project exists) and no leak.

**Trap for the runbook:** the HTTP body takes the **wire** shape, not the model shape. `timestamp`
is rejected; the field is `ts_us` (microseconds). My first two attempts returned `"rejected":1`
with no explanation. `duration_seconds` is also capped at 3600.

---

## Live Bench — sim (MuJoCo) · **WORKS**

Not "it passes headless in tests" — a real stepped model, streaming LB-06 packets, integrating
real physics. A rod hinged horizontally under gravity:

```
mujoco 3.11.0
t=00.000  qpos=      0.0  qvel=      0.0
t=00.020  qpos=  0.00629  qvel=   0.5721
t=00.040  qpos=  0.02403  qvel=   1.1442
t=00.060  qpos=   0.0532  qvel=   1.7159
... 25 packets; qpos moved 0.0 -> 2.50559
```

qvel climbing linearly from rest is gravity actually being integrated, and the device id
(`pendulum/hinge`) and 50 Hz cadence match the packet contract.

## Live Bench — sim (Isaac, Gazebo) · **BUILT-UNVERIFIED / NOT BUILT**

**Isaac Sim 6.0.1-rc.7 is built and importable on this box** (I found it; you did not need to
point me at it):

```
$ /home/beeboss/isaacsim/IsaacSim/_build/linux-aarch64/release/python.sh -c "import isaacsim"
isaacsim import OK
3.12.13
```

But **Solus has no Isaac adapter** — `livebench/sim/` holds `mujoco_source`, `gazebo_source`,
`mcap_replay` and nothing else. By ADR-014 that is deliberate: Isaac and Gazebo are "integration
targets (read their data), never competitors", and the Isaac path is **MCAP replay**
(`mcap_replay.py`: _"Isaac Sim logs to MCAP… the live-Isaac decision is taken when Isaac Sim
[is available]"_). The `mcap` library is installed (1.4.0) but there is **no `.mcap` file anywhere
in the repo**, so I could not prove the Isaac→MCAP→packets path on real data.

**Unblocker:** one MCAP recording produced by Isaac. Gazebo is simply absent from this machine
(`gz`/`gazebo` not on PATH).

---

## Live Bench — robot (RBT-01) · **WORKS, on real hardware**

There _is_ a device on this bench — `1a86:55d3` at `/dev/ttyACM0` — and the passive recogniser
identifies it correctly, including the part it honestly cannot know:

```
PortIdentity(device='/dev/ttyACM0', vid=6790, pid=21971, serial='5B42135040',
  board=Board(name='WCH CH343/CH9102 USB-serial bridge', kind=USB_BRIDGE),
  mcu_known=False,
  evidence=ModalityMatch(modality=BUS_ENUMERATION, confidence=0.3, state=LOW_CONFIDENCE,
    evidence={'matched_on':'usb_vid_pid','value':'1a86:55d3',
      'note':'the bridge chip is identified, but the MCU behind it is unknown —
              a bridge carries no identity for what it fronts'}))
```

`mcu_known=False` at confidence 0.3 is the right answer, not a limitation: a USB-serial bridge
carries no identity for the microcontroller behind it. **RBT-02/03/04 were not exercised** — they
need a board that actually talks a protocol (a Dynamixel servo chain or an MCU running firmware),
and nothing here answers on that port.

---

## The bridge and the vendored forks · **WORKS-WITH-SETUP**

Verified live earlier today, after `make mcp-forks`:

```
WebSocket /api/v1/projects/01a0055b-…/bridge   [accepted]
connection open
solus.companion INFO discovered 3 server(s) under …/integrations/mcp
kicad overlay: registered ['analyze_bom','analyze_schematic_connections','export_netlist',
  'extract_project_netlist','get_project_structure','list_projects','set_symbol_property'],
  trimmed 4 upstream tools
```

Handshake **101, not 403**. KiCad launches with 7 tools.

- **kicad — WORKS.**
- **altium — wiring landed (SOLUSDEV-166), pending a live re-verify.** The historical failure was
  `refusing to start: SOLUS_MCP_WORKSPACE is not set; refusing rather than confining to the
process cwd`: the companion only passes that variable when `SOLUS_COMPANION_WORKSPACE` is
  configured, and the desktop never set it. The desktop main process now derives it at companion
  spawn from the `~/.solus/projects.json` registry (ADR-034) and respawns the companion when the
  active project's folder link changes. Failing closed with no linked folder remains the correct
  behaviour.
- **fusion — correctly not a fork.** Its `allowlist.yaml` says so: Autodesk ships it and it runs on
  the customer's machine at `127.0.0.1:27182`. It fails here because no Fusion is running, and its
  tool list is deliberately empty pending a live `tools/list` capture.
- **autocad, solidworks — correctly refused:** `launch command …/bin/launch does not exist`.
  Windows-only, no POSIX launcher.

---

## Onshape · **WORKS (connect + sync)** / **UNVERIFIED (write)**

Better than expected — you had already completed the grant, and the sync is real:

```
sources:  type=onshape  status=connected  created_at=2026-08-15 12:18:27
graph_entity: 243 rows, all domain=mechanical kind=part
properties: {"element_id":"…","document_id":"…","is_assembly":true}
```

So **grant → sync → entities in `graph_entity`** is proven end to end. Of the three gates you
named, I exercised **grant and sync**; I did **not** exercise the write path — no confirmation card
was raised and nothing was approved, so nothing of yours was modified. The Onshape **panel** was
not exercised either (it needs the desktop panel UI and a bound session).

---

## The graph, linking, impact · **PARTLY WORKS / NOT EXPOSED**

The live graph reads correctly over HTTP against real data:

```
GET /projects/{id}/graph?root={entity}&depth=1
 -> entities[0]: type=part domain=mechanical name=69065a8ddecb0f8bec6934a4
    properties={"element_id":…,"document_id":…,"is_assembly":true}
```

`GET /entities`, `/entities/{id}`, `/entities/{id}/relations` and `/graph` all exist and answer.

The integration tests pass — `test_integrations_stack.py` + `test_kicad_ingest_e2e.py`, 6 passed in
6.07s — but **per your own rule I am not classifying the cross-domain story from that.** The
four-connector → fingerprint → `same_as` → MPU-6050 Nyquist scenario lives in test fixtures, and
this project's graph is single-source (Onshape only), so there is nothing cross-domain in it to
traverse.

**`impact/` exists as a module** (`solus_api/impact/`, `contracts/impact.py`) but is **exposed by no
HTTP route** — there is no `/impact` path in the live OpenAPI. So impact traversal is
BUILT-UNVERIFIED from a product standpoint: reachable from Python, not from the app.

---

## The workspace shell — the canvas does not exist · **NOT BUILT**

This is the one you asked me to check carefully, and it is the difference between a product and a
set of working backends.

- `discoverWidgets()` is defined in `widgets/discover.ts` and **called nowhere** in production code.
- `WidgetHost` appears exactly once outside its own file — **inside a comment**.
- Neither `AppRoutes.tsx` nor `WorkspaceShell.tsx` references either.

Two widgets ship manifests (`widgets/livebench/`, `widgets/_reference/`), the CTR-01 glob registry
works, and **nothing mounts them**. The Live Bench widget is unreachable in the running app. LANE
H's QA hedge — "if the canvas isn't wired in your build, this flow is UI-pending" — resolves to:
it isn't. LANE B is not in the merged set.

## Guide side panel (TU-09) · **WORKS-WITH-SETUP, KB empty**

The panel and routes are built and the KB is queryable, but after the database rebuild it holds
nothing:

```sql
select count(*) from tool_knowledge;   -- 0
```

With an empty KB every step resolves `available:false` and renders its authored narration with an
honest "isn't in the knowledge base yet" note — correct degradation, but SOL cannot walk anyone
through a real task until TU-02 ingestion runs. **Unblocker:** run the KiCad docs ingestion.

## ROS connector · **NOT BUILT**

`SourceType.ROS` exists in the model, but `build_default_registry` registers only github, gitlab,
altium, kicad, onshape. The docstring still says "the rest of the roster (KiCad, Onshape, ROS)
registers here as each connector lands" — ROS has not landed.

---

## Read-but-never-written `SOLUS_*` variables

You were right that this is a pattern, not three accidents. **40 variables are read by code and
written by no `.env`, `env.example`, launch script, Makefile, compose file or desktop path.**

Most are tunables with defaults and are fine unset (`SOLUS_BRIDGE_*` rate limits and timeouts,
`SOLUS_ARTIFACT_*` caps, `SOLUS_MIGRATE_TIMEOUT_SECONDS`) or deploy-time
(`SOLUS_ECS_*`, `SOLUS_VPC`, `SOLUS_TG_NAME`, `SOLUS_SENTRY_DSN`). These are the ones that **gate
functionality**:

| Variable                                                 | Consequence of being unset                                                                                                                                                                                                                            |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SOLUS_COMPANION_WORKSPACE`                              | Without it the companion omits `SOLUS_MCP_WORKSPACE` and workspace-gated forks (Altium) fail closed. Since SOLUSDEV-166 the desktop derives it from the `~/.solus/projects.json` registry at spawn; unset only when the project has no linked folder. |
| `SOLUS_MCP_WORKSPACE`                                    | The fork-side half of the same gap                                                                                                                                                                                                                    |
| `SOLUS_ARTIFACT_LOCAL_ROOT` / `SOLUS_ARTIFACT_S3_BUCKET` | Artifact store falls back to a process-local tmp dir; uploaded bytes are lost on cleanup. Warned on every boot                                                                                                                                        |
| `SOLUS_BRIDGE_ALLOWLIST_ROOT`, `SOLUS_MCP_PYTHON`        | Fork launch paths; defaults happen to work here                                                                                                                                                                                                       |
| `SOLUS_TOOLKB_VOTE_SALT`                                 | Ephemeral per-process salt ⇒ vote de-dup does not survive a restart. Warned on every boot                                                                                                                                                             |

---

## Gap list — what is unbuilt or unproven, and what unblocks it

| Gap                                   | Unblocker                                                                                                                                                                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **SOL reads fake context**            | Implement the `SolSystems` protocol against the real graph. The parts exist (`to_graph_context`, `get_telemetry`); nothing assembles them. This is the single highest-value fix in the repo — until it lands, every SOL answer is fiction. |
| **No workspace canvas**               | LANE B, or wire `discoverWidgets()` + `WidgetHost` into a route. Until then every widget is unreachable.                                                                                                                                   |
| **Impact not exposed**                | An HTTP route over the existing `impact/` module                                                                                                                                                                                           |
| **Altium fork**                       | Wiring landed (SOLUSDEV-166: `~/.solus/projects.json` → `SOLUS_COMPANION_WORKSPACE` at spawn). Remaining: link a folder to a project in the desktop app and re-verify the fork starts                                                      |
| **Isaac telemetry**                   | One Isaac-produced `.mcap` recording                                                                                                                                                                                                       |
| **Gazebo**                            | Not installed on this machine                                                                                                                                                                                                              |
| **RBT-02/03/04**                      | A board that answers a protocol on `/dev/ttyACM0` (Dynamixel chain, or an MCU running firmware)                                                                                                                                            |
| **Guide KB**                          | Run TU-02 KiCad docs ingestion                                                                                                                                                                                                             |
| **Onshape write path**                | A deliberate write + confirmation approval against a document you nominate                                                                                                                                                                 |
| **Onshape panel**                     | Desktop panel UI with a bound session                                                                                                                                                                                                      |
| **ROS connector**                     | Not implemented                                                                                                                                                                                                                            |
| **Cross-domain linking on real data** | A second connector on the same project — today it is Onshape-only, so there is nothing to link across                                                                                                                                      |

## What I changed

Nothing but this file and `RUNBOOK.md`. The Anthropic key was seeded into the SecretStore via the
existing script — a data operation, not a code change. Two test users now exist in the dev database
(`intruder@example.com` from the isolation test) and one telemetry packet plus one observer event
were written to your project.
