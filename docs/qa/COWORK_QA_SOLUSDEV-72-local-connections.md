# Cowork QA — SOLUSDEV-72: Local connections surface

Self-sufficient test plan for Claude Cowork. You need: the running app (API on
`localhost:8000` with the root `.env` sourced, desktop dev via `make dev-api` + `make
dev-desktop`), a logged-in member of a project, and this file. No implementation context
required.

Machine expectations for this plan (the dev DGX box): MuJoCo installed in the API venv; Gazebo
NOT installed; Isaac Sim present at `~/isaacsim`; ONE LeRobot arm on a CH343 USB-serial bridge
(serial `5B42135040`); optionally a second identical arm for §6.

## 1. Sources screen — Local Connections section

1. Open a project → Sources (rail). Below the integration tiles, a **LOCAL CONNECTIONS** area
   shows SIMULATORS / DEVICES / LOCAL TOOLS.
   - [ ] MuJoCo row: available, Start enabled.
   - [ ] Gazebo row: says **not installed** (`gz` CLI absent) and Start is disabled — verify it
         cannot be clicked.
   - [ ] Isaac row: not startable; reason mentions the direct script and MCAP replay.
   - [ ] MCAP replay row: unavailable with reason "bench_data_root is not configured" (unless a
         human has set `SOLUS_BENCH_DATA_ROOT`).
   - [ ] Device row: "WCH CH343/CH9102 USB-serial bridge", **MCU unknown** (never a guessed
         board), confidence 0.3, serial `5B42135040` visible.
2. Stop the API process → the section degrades to honest offline copy (no cached inventions).

## 2. Start a MuJoCo session and see it stream

1. Click **Start** on MuJoCo.
   - [ ] A session chip appears inline: label "MuJoCo demo", state moves connected → streaming,
         packet counts climb, Stop button present.
2. Go to **Live Bench** WITHOUT focusing any entity in the Context Model.
   - [ ] A `DEMO/ROD` panel renders with `qpos`/`qvel` updating (real pendulum swing — values
         oscillate, `qvel` alternates sign; they are not constants).
   - [ ] Header says devices stream from active sessions and focusing an entity gives the
         entity-scoped view. No dead-end "select an entity" wall.
3. Back in Sources, click **Stop**.
   - [ ] Chip flips to ended; clicking Stop again is harmless (idempotent).
   - [ ] The session auto-ends by itself after its duration (default 300 s) — a finished sim
         must not hold one of the 4 per-project session slots (start 4 short sessions to prove
         the cap frees).

## 3. Failure paths

- [ ] With 4 active sessions, a 5th start shows a "too many sessions" error.
- [ ] Starting MuJoCo with a custom MJCF containing `<include file="/etc/passwd"/>` (or any
      `file=` attribute) is refused with a generic message — the error must NOT echo the path
      or any filesystem detail.
- [ ] MCAP path outside the configured data root (e.g. `../../etc/passwd`) → validation error.
- [ ] Kill the API mid-session → Live Bench panels degrade to STALE → NO STREAM (derived from
      data age, never asserted); Sources degrades honestly.

## 4. Devices — identity honesty (single arm)

1. With the one arm connected, click its **Connect** (real/serial session).
   - [ ] The session binds by serial (`5B42135040`) and appears on that device row.
   - [ ] Live Bench shows its device-keyed panel (the arm is NOT in the graph — this is the
         pre-reconciliation view).
         Note: the arm must actually emit LB-06 JSON lines for data to render; a silent arm shows the
         honest "no stream" state, which is correct.
2. Edit the device label to "leader".
   - [ ] Unplug/replug the arm into a DIFFERENT USB port; after re-enumeration the label still
         attaches to it (identity is the USB serial, not `/dev/ttyACM*`).

## 5. Fusion / bridge tools

1. Sources tile grid: a **Fusion** tile exists (local-bridge mode).
   - [ ] Clicking it opens guidance (launch Fusion, enable Preferences → General → API → Fusion
         MCP Server) + companion state — NEVER an OAuth browser flow or file picker.
2. LOCAL TOOLS section: Fusion row shows companion + server state.
   - [ ] With the companion connected and Fusion running but zero allowlisted tools, the copy
         says connected but **no tools callable yet** — it must not imply full function.

## 6. TWO IDENTICAL ARMS (human-assisted — requires both LeRobot arms plugged in)

This is the safety property. With leader AND follower connected simultaneously:

- [ ] Both enumerate as separate device rows.
- [ ] If their USB serials differ: each row shows its own serial; label each ("leader" /
      "follower"); unplug both, swap ports, replug — labels and any bound session follow the
      SERIAL, not the port.
- [ ] If serials are identical (or absent): both rows are flagged ambiguous with the device
      path as the visible tiebreaker; Connect requires an explicit per-device pick; the started
      session attaches ONLY to the picked row (never both); on replug the binding renders as
      needing re-confirmation rather than assuming.
- [ ] At no point may the UI claim to know which arm is which without either a distinct serial
      or an explicit user pick.

## 7. Cross-tenant isolation

As a user with NO membership in the project (fresh account):

- [ ] `GET /api/v1/projects/{project_id}/bench/sources`, `/sessions`, `/sessions/{id}`,
      `/device-recent?device_id=x` and `POST /sessions` all return **404** (not 403 — no
      existence leak). Unauthenticated → 401.

## 8. Isaac direct script (human-assisted — needs an articulated USD scene)

```
SOLUS_TOKEN=<jwt> ~/isaacsim/IsaacSim/_build/linux-aarch64/release/python.sh \
  livebench/src/livebench/sim/isaac_direct.py --project-id <project> --scene <robot.usd>
```

- [ ] Joint states appear in Live Bench as `isaac/<dof>` device panels (same pre-reconciliation
      path as §2). An empty stage prints "no articulations on this stage — nothing to stream"
      and exits — no fabricated data. ROS is not required anywhere.
