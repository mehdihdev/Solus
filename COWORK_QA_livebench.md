# Cowork QA — Live Bench & Streaming Telemetry (LANE H, SOLUSDEV-66)

End-to-end test plan for the Live Bench lane. Written for a tester who has the running Solus
application and this file — no implementation context assumed. Mark each step ☐ pass / ☐ fail.

## Scope

This lane delivers: the telemetry packet format (LB-06, merged from LANE A), Foxglove/MCAP
ingest (CON-03), sim connectors (LB-01), robot connection + edge observers (LB-02), the Live
Bench widget + bench API routes (LB-05), robot identification (RBT-01..05), deployment (LB-03),
and fault-induction drills (LB-04). Much of it is streaming/hardware code exercised by automated
tests; this file covers what a human/Cowork tester can drive through the running app + API.

## Required setup

1. **Services running**: the FastAPI backend (`packages/api`) against a Postgres+pgvector DB with
   migrations applied (`alembic upgrade head`); the desktop app (`apps/desktop`) built and
   running, signed in as a user with a team and a project.
2. **A project with at least one graph entity** whose `source_key`/`external_ref` you know — the
   simplest path is to connect a GitHub source and sync it (creates entities), then note one
   entity's id and `source_key` from the project's Sources/graph view.
3. **No hardware required** for the API + widget flows below. The sim/robot/flash flows that need
   physical devices are called out and marked NOT-RUNNABLE-WITHOUT-HARDWARE.

---

## Flow 1 — Bench telemetry ingest + read (API)

The bench routes are `/api/v1/projects/{project_id}/bench/...`. Use an authenticated request
(bearer token from the app session). `{entity_id}`/`{ref}` are the entity and its `source_key`.

1. **Ingest a batch.** POST `/bench/telemetry` with body
   `{"packets": [{"schema_version":1,"device_id":"<ref>","ts_us":1767225600000000,"values":{"rpm":100.0}}]}`.
   ☐ Expect `200` and `data: {"accepted":1,"unresolved":0,"rejected":0}`.
2. **Read recent values.** GET `/bench/recent/{entity_id}`.
   ☐ Expect `200`, `data.signals` contains a series `{"signal":"rpm","points":[{"value":100.0,...}]}`.
3. **Read a summary.** GET `/bench/summary?duration_seconds=10`.
   ☐ Expect `200`, `data.windows` a list; the newest window's `signals` includes `rpm`.
4. **Ingest to an unknown device.** POST a packet with `device_id":"ghost"`.
   ☐ Expect `200` and `data.unresolved` incremented, `accepted` unchanged — no error.
5. **Ingest a hostile packet.** POST `{"packets":[{"ts_us":"garbage"},{"nonsense":true}]}`.
   ☐ Expect `200`, `data.rejected == 2`, service stays up (re-run step 2, still works).
6. **Batch too large.** POST 501 packets. ☐ Expect `422` (bounded).

## Flow 2 — Observer events

1. **Post an event.** POST `/bench/telemetry` with
   `{"packets":[...one valid packet...],"events":[{"kind":"threshold_breach","device_id":"<ref>","signal":"temp","at":"2026-01-01T00:00:00Z","value":95.0,"detail":{"high":80.0}}]}`.
   ☐ Expect `200`.
2. **Read events.** GET `/bench/events`. ☐ Expect the event back, `kind` and `signal` intact.

## Flow 3 — Cross-tenant isolation (the highest-severity invariant)

Set up a SECOND user (Bob) with his own team+project.

1. As Bob, GET `/projects/{alice_project}/bench/recent/{alice_entity}`.
   ☐ Expect `404` (no existence leak).
2. As Bob, GET `/projects/{alice_project}/bench/events` and `/bench/summary?duration_seconds=10`.
   ☐ Both `404`.
3. As Bob, POST `/projects/{alice_project}/bench/telemetry`. ☐ Expect `404`.
4. As Bob, POST to HIS OWN project a packet with Alice's `device_id`.
   ☐ Expect `200` but `accepted == 0` (that device isn't in Bob's graph) — no data bleed.
5. Unauthenticated GET `/bench/events`. ☐ Expect `401`.

## Flow 4 — Live Bench widget (desktop)

The widget self-registers (id `livebench`). It appears wherever the workspace canvas mounts
widgets for a focused part; if the canvas isn't wired in your build, this flow is UI-pending —
note it and skip to Flow 5.

1. Focus a part that has telemetry (ingest some via Flow 1 for its entity first).
   ☐ The widget shows signal tiles with current values, and a rolling chart per signal.
2. ☐ A connection-state line reads `LIVE DATA` right after ingest, degrading to `STALE` then
   `NO STREAM` as the data ages (no fresh ingest for >15s). It NEVER reads "REAL".
3. Post an observer event for the focused entity (Flow 2). ☐ An anomaly marker (⚠) appears.
4. Focus a part with NO telemetry. ☐ An honest "No telemetry yet…" message, no fake values.
5. Stop the backend, keep the widget focused. ☐ It shows an unavailable/error state, no crash.

## Flow 5 — Robot recognition proposal surface (desktop component)

The RBT-03 proposal table renders four evidence tiers. Wherever it's surfaced in your build:

1. ☐ Rows show a confidence badge (e.g. `92% · bus-enumerated`, `55% · firmware`) and an
   "evidence" toggle that reveals the value, honesty note, and provenance (e.g. `src/arm.ino:11`).
2. ☐ Each proposed row has a one-click **Accept** and a **Reject**; a bare-serial "unknown" row
   has NO accept button and shows `unknown`.
3. ☐ **Accept-all** accepts proposed rows only and never touches unknowns.
4. ☐ On an unknown row, type a name and Save → the row shows `edited`. Saving an empty name does
   nothing.
5. ☐ Nothing is accepted until you click — even a 0.92 row starts as `proposed`.

## Flows requiring physical hardware — NOT RUNNABLE WITHOUT A ROBOT

Documented for the human hardware session; the automated suites cover the logic against
fixtures/sim, and these gates are reported UNVERIFIED in the completion report.

- **LB-01 sim**: MuJoCo runs headless (a pendulum scene streams for real in tests); Gazebo and
  Isaac Sim need their installs (Gazebo apt, Isaac container) before a live smoke.
- **LB-02 robot**: needs a wifi/serial robot streaming LB-06 or JSON lines.
- **RBT-01 buses**: needs a Dynamixel U2D2 / CAN interface for live enumeration (the CH343 USB
  bridge on the bench IS testable and correctly reports "MCU unknown").
- **RBT-04 active id**: needs an actuator + the SOLUSDEV-60 confirmation surface merged.
- **LB-03 flash**: needs a sanctioned flashable device.
- **LB-04 full induction**: unplug a real sensor / force a rate clash on a running robot; the
  drill script + `DrillReport` (latency, attribution, false-pos, misses) is the deliverable.

## Edge cases to exercise

- Empty project (no entities): bench reads return empty, not errors.
- Rapid repeated ingest: recent values stay bounded (ring buffer), no unbounded growth.
- Malformed JSON body to any bench route: `422`, service survives.
