# Cowork QA — Robot onboarding (SOLUSDEV-248: R5 · R3 · R1 · R2 · R4)

Self-sufficient end-to-end test plan for robot onboarding: the per-robot hardware config with
provenance (R5), the transport / protocol-driver / reconnect layer and the telemetry library
(R3), the Add › Hardware five-card surface (R1), the detection loop enumerate → identify →
interrogate → propose → confirm (R2), and the curated parts / platform library (R4).

Everything here was run against a real API and two real serial servo arms on 2026-09-06 unless a
step is marked **(fixture only)** or **(human step)**. Legend: ✅ pass · ❌ fail · ➖ blocked/NA.

The product rule under test everywhere: **propose, never assert; empty beats invented.** A
detected device produces a proposal the user confirms, never a silently created robot; an
unknown never gets a guessed name; a question is asked once and remembered.

---

## Required setup state

- **Postgres + Redis up**: `make db-up` (docker `solus-db-1`, `solus-redis-1` healthy).
- **Dev database migrated to head** — the ticket adds a migration:
  ```
  cd packages/api && uv run alembic upgrade head    # head must be 7e290e665c1f (mergepoint)
  ```
  A dev DB left at the previous head makes `POST …/projects` return 500 (the `.solus` seed
  writes the new `payload` column). If you see that, run the upgrade.
- **API** on `127.0.0.1:8000` from a shell that has NOT `source`d the root `.env`
  (`make dev-api`, or `cd packages/api && uv run uvicorn --factory solus_api.main:create_app
--port 8000`). The API reads the root `.env` itself. It needs `SOLUS_SUPABASE_JWT_SECRET`,
  `SOLUS_DATABASE_URL`; no new environment values were added by this ticket.
- **livebench installed in the API's environment** (`uv sync --all-packages` at the repo root).
  Without it every hardware route still answers, but Detected shows the honest "runner not
  installed" state and accept/confirm report `bind_error` / `session_error`.
- **Desktop** `pnpm --filter @solus/desktop dev`, signed in, with a project. Workspace → Add →
  Hardware is the surface under test (it replaced the single "Add Physical Robot" button).
- **Optional hardware for the live flows**: one or two serial servo arms on USB (any bus the
  installed plugins speak; the run used two six-servo arms on a USB-serial bridge). Nothing else
  may hold the port: stop any teleop / bench script first — a busy port reads as silence by
  design, and silence is reported as "no protocol found", not as an error.
- **Optional local repo checkout** whose code declares the robot's motors and whose calibration
  files exist on this machine (the run used a `lerobot` clone at `~/lerobot`). Its absolute path
  is `<REPO_ROOT>` below. Without it, Detected still proposes parts by address; names and
  calibration simply stay empty.
- **Second user in a different team** with a project (`<TOKEN_B>`, `<PROJECT_B>`) for the
  isolation checks.
- For API-level steps: `<TOKEN>`, `<PROJECT_ID>`, `H=http://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/hardware`,
  `AUTH="Authorization: Bearer <TOKEN>"`. Every response is `{ "data": … }` on success or
  `{ "error": { "code", "message" } }`.

---

## Flow A — Add › Hardware shows five honest cards (R1)

| #   | Step                                                         | Expected                                                                                                                                                                                                                    | ✅/❌ |
| --- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| A1  | Workspace → Add → **Hardware** tab                           | Five cards: **Detected** (Devices on this machine), **From a file** (Parts from connected sources), **Library** (Curated parts and platforms), **Sourced** (Parts from suppliers), **Authored** (Describe a part yourself). |       |
| A2  | Look at **Sourced**                                          | Rendered disabled (aria-disabled), footer reads exactly "Sourcing (ST5) is not available yet." Clicking does nothing; no modal, no dead button.                                                                             |       |
| A3  | Go offline (stop the API) and reopen the tab                 | Cards still render; opening one shows the offline copy ("Connect this project to add hardware." or the modal's honest error), never a spinner forever.                                                                      |       |
| A4  | Switch SOL mode Guide ↔ Expert (Settings) and reopen a card | Card intro copy changes with the mode (Guide explains, Expert is terse).                                                                                                                                                    |       |

## Flow B — Authored part, end to end (R1 + R5)

| #   | Step                                                                                                                                            | Expected                                                                                                                                                                    | ✅/❌ |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| B1  | With no Physical Robot in the project, open **Authored**                                                                                        | The Robot target says "Create a Physical Robot first (Add › Hardware › Authored)." and offers to create one (name field → Create).                                          |       |
| B2  | Create robot "Rover"                                                                                                                            | Robot appears in the workspace with its seven category children (Sensors, Actuators / motors, Controllers, End effectors, Power, Structure, Wiring).                        |       |
| B3  | Authored → Robot "Rover", Category **sensors**, name "Cabin pressure", fill Interface `I2C`, Supply `3.3`, Range `300–1250 hPa` → Create        | Part lands under Rover › Sensors; modal says the part was created; lifecycle **planned**.                                                                                   |       |
| B4  | Authored again → Category **actuators**, name "Left ESC", Interface `PWM`, Supply `12`, Rated output `30 A`, Control signal `DShot600` → Create | Part lands under Rover › Actuators / motors.                                                                                                                                |       |
| B5  | Open the project `.solus` → **Hardware configs**                                                                                                | One entry per Physical Robot ("Hardware config — Rover") of kind `config`. `PATCH` on it (edit text) is refused with 409 — configs change only through the hardware routes. |       |
| B6  | Lifecycle: in the inspector for "Left ESC" (or `POST $H/robots/<ROBOT_ID>/parts/<PART_ID>/lifecycle {"state":"live"}`)                          | Lifecycle becomes **live**; the part keeps the same entity id and its `contains` edge; config provenance for `parts.<id>.lifecycle` is `user`.                              |       |
| B7  | Same as B6 with `{"state":"bogus"}`                                                                                                             | 422 validation error; nothing changes.                                                                                                                                      |       |

API twin of B3:

```
curl -s -X POST "$H/robots/<ROBOT_ID>/parts" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"name":"Cabin pressure","category":"sensors","specs":{"interface":"I2C","supply_v":3.3}}'
```

→ 201 with the part entity; `GET $H/robots/<ROBOT_ID>/config` shows `parts.<id>` with
`lifecycle: planned` and provenance `user`.

## Flow C — Library: search, preview, import (R4)

| #   | Step                                                                  | Expected                                                                                                                                                                                                                                                                                                | ✅/❌ |
| --- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| C1  | Open **Library** with an empty search                                 | Two groups, **Parts** and **Platforms**, showing the curated seed (18 parts, 6 platforms).                                                                                                                                                                                                              |       |
| C2  | Search `so101`                                                        | Hits: two platforms (a follower arm and a leader arm) and one servo part. Search `zzz` → exactly "Nothing in the library matches."                                                                                                                                                                      |       |
| C3  | Select the follower-arm platform                                      | Preview shows six parts by function name (shoulder_pan … gripper) and a gear-ratio table.                                                                                                                                                                                                               |       |
| C4 | **Import as new robot** (Robot name "Follower (library)") — the modal then reads "Imported — 6 parts" | A new Physical Robot with six parts under Actuators / motors; `GET $H/robots/<id>/config`: every valued leaf has provenance `library` with source `platform:so101-follower`; joints `degrees` → unit `deg`, gripper `range_0_100` → unit `%`; lifecycle `planned`; **no identity yet** (nothing bound). |       |
| C5  | Select a **part** (a servo) → Import into "Rover", category actuators | Part lands under Rover › Actuators / motors with provenance `library`.                                                                                                                                                                                                                                  |       |
| C6  | Import the same platform twice                                        | Two robots (import is not idempotent by design — each import is a new physical thing). Record what you see.                                                                                                                                                                                             |       |

API twin: `GET $H/library?q=so101` · `GET $H/library/platforms/so101-follower` ·
`POST $H/library/platforms/so101-follower/import {"name":"Follower (library)"}` → 201
`{robot, part_ids[6], config_entry_id, suggestion_ids[]}`.

## Flow D — Detected: one arm, from bare device to live telemetry (R2 + R3 + R5)

Requires an arm on USB and the runner installed. Start with the arm's port free.

| #   | Step                                                                                                                                                                                                                                                                          | Expected                                                                                                                                                                                                                                                                                                                                                  | ✅/❌ |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| D1  | Open **Detected**                                                                                                                                                                                                                                                             | "Looking for devices…" then a list keyed by **USB serial** (`usb:5B42134331`), never by tty path. Level is honest: a bare USB-serial bridge shows the **transport** level at confidence 0.30 with the path shown as a detail (`/dev/serial/by-id/…`). No vendor guessed.                                                                                  |       |
| D2  | Unplug the arm, wait ~3 s, reopen                                                                                                                                                                                                                                             | The device disappears. Replug → it returns under the **same** serial even if the tty path changed.                                                                                                                                                                                                                                                        |       |
| D3  | Click **Propose** on the arm (repo root set to `<REPO_ROOT>` in the field, or leave empty)                                                                                                                                                                                    | Within ~2 s: driver `feetech-sts` (a plugin's name, shown as a fact), **six rows** at addresses 1–6, model per row, confidence 0.92, provenance **repo** when a repo root was given (names shoulder_pan … gripper), else rows are by address (`addr_1` …) with no names.                                                                                  |       |
| D4  | With `<REPO_ROOT>` given and more than one config in the repo matching six such servos                                                                                                                                                                                        | A **disambiguation** question: "N configs in your repo match this device — which is it?" with the options listed and, when the parts' burned calibration matches one config, that option marked as favoured with the reason. The favoured option is **not** pre-applied: nothing is confirmed until you choose.                                           |       |
| D5  | Pick a config, target **Add as new robot** "Arm A", Confirm                                                                                                                                                                                                                   | "Robot confirmed": robot + six parts under Actuators / motors, each part's external ref `usb:<serial>/<address>`; config identity/protocol/bus_map provenance `detected`; part names, calibration values (homing offset, range) and units provenance `repo` with the calibration file path as `source`; parts lifecycle **live**; a bench session starts. |       |
| D6  | Open Live Bench for Arm A (or `GET …/bench/sessions/<id>`)                                                                                                                                                                                                                    | `counts.ingested` grows (~180/s for six servos at 30 Hz), `unresolved` stays 0, `device_ids` are the six part keys. Move a joint: its `<name>.position` series changes, in **deg**; the gripper's `gripper.position` in **%**. Values must be plausible (joints roughly −180…180, gripper 0…100).                                                         |       |
| D7  | Re-open Detected → Propose the same arm again (stop its session first, or expect "no protocol found" while the session holds the port)                                                                                                                                        | No link suggestion to its own robot; the repo config you chose is listed as already bound and is **absent** from the options; Confirm as a new robot → **409** "usb:<serial>/1 is already part of robot <id> — reconnecting a known machine needs no second robot".                                                                                       |       |
| D8  | Port-path repair: when the repo binds a port path that is not where the device is now, the proposal carries a `port_repair` notice (`kind` file or command, `configured` vs `actual` path, `source`, `note`). Solus never edits the repo: the note tells you what to change (a file line, or the corrected command for repos that bind ports on the command line). When the paths agree, `port_repair` is null. |                                                                                                                                                                                                                                                                                                                                                           |       |

API twin of D3/D5:

```
curl -s "$H/detected" -H "$AUTH"
curl -s -X POST "$H/detected/usb:<SERIAL>/propose" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"repo_root":"<REPO_ROOT>","budget_s":1.5}'
curl -s -X POST "$H/detected/usb:<SERIAL>/confirm" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"target":{"kind":"new","name":"Arm A"},
       "accepted":[{"row_id":"usb:<SERIAL>/1","function_name":"shoulder_pan"}, …],
       "repo_config_id":"<one of disambiguation.options>","repo_root":"<REPO_ROOT>","window_seconds":1.0}'
```

`accepted[].row_id` is the row's `id`. Only rows the server re-proposes are accepted (a stale or
invented row id → 422 "unknown proposal rows").

## Flow E — Two arms: the second one is offered the remaining config (R2)

| #   | Step                                                                                                                                                                                                                                            | Expected                                                                                                                                                                   | ✅/❌ |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| E1  | Both arms plugged in, Detected                                                                                                                                                                                                                  | Two devices, two different serials, both at the same honest level.                                                                                                         |       |
| E2  | Propose arm 1 with `<REPO_ROOT>`, confirm it with config X                                                                                                                                                                                      | As Flow D.                                                                                                                                                                 |       |
| E3  | Propose arm 2                                                                                                                                                                                                                                   | Six rows; the disambiguation **omits X** (it is bound) and lists the rest; `bound_repo_configs` names X. The question is asked once per arm, never re-asked after confirm. |       |
| E4  | Confirm arm 2 as "Arm B" with config Y, then open both sessions                                                                                                                                                                                 | Both ingest; the two arms' signals never mix: each part key carries its own serial.                                                                                        |       |
| E5  | **(human step)** Stop both sessions, swap the two USB cables between ports, restart both sessions from their robots (Live Bench → the robot, or `POST …/bench/sessions {"mode":"real","config":{"provider":"robot","robot_entity_id":"<id>"}}`) | Each robot still streams from **its own** arm: the config's `last_seen_path` updates but the binding (serial) and every part key stay the same. Labels hold.               |       |
| E6  | **(human step)** While a session runs, unplug arm 1 for ~5 s and replug                                                                                                                                                                         | Session stays `active`; ingestion pauses and resumes silently; the session's device stays keyed by serial; no second robot, no new proposal needed.                        |       |

## Flow F — Library robot and the same machine on the wire reconcile to one robot (R4 + R5)

| #   | Step                                                                | Expected                                                                                                                                                                                                                                                                                                                                                         | ✅/❌ |
| --- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| F1  | Fresh project: Library → import the follower-arm platform (Flow C4) | Robot "Follower (library)", six parts, no identity.                                                                                                                                                                                                                                                                                                              |       |
| F2  | Detected → Propose the arm                                          | Under the rows, one **link suggestion**: candidate = the library robot, tier **high**, confidence 0.80, reason "this robot's bus map (6 parts at addresses 1, 2, 3, 4, 5, 6) matches the device; nothing is bound to it yet". It is a suggestion: nothing is bound yet. `GET $H/suggestions?status=pending` lists it.                                            |       |
| F3  | **Accept** it                                                       | Response `status: accepted, bound: true, session_id` set. The library robot now has the arm's identity (provenance `detected`), the six library parts are keyed `usb:<serial>/1…6`, their lifecycle is **live** (provenance `detected`), the library names and units are kept (provenance `library`). **No second robot exists.** The session ingests (Flow D6). |       |
| F4  | Propose the arm again                                               | `suggestions: []` (a device never suggests linking to the robot it is bound to). Confirm as new → 409 as in D7.                                                                                                                                                                                                                                                  |       |
| F5  | Instead of F3, **Reject** with a reason                             | Suggestion `rejected`; nothing bound; a later propose creates a fresh pending suggestion again (rejections are per row, not a permanent ban).                                                                                                                                                                                                                    |       |
| F6  | Two library robots imported, one arm proposed                       | **Two** suggestions (one per candidate), no winner picked. Accepting one marks the other `superseded`.                                                                                                                                                                                                                                                           |       |

## Flow G — From a file (R1/R2 attach)

| #   | Step                                                                                                       | Expected                                                                                                            | ✅/❌ |
| --- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ----- |
| G1  | Project with no connected sources → **From a file**                                                        | "No unassigned parts from connected sources yet."                                                                   |       |
| G2  | Connect a source that yields part-like entities (a KiCad schematic, a CAD assembly or a BOM), sync, reopen | Unassigned parts listed (kinds part / component / cad_part / assembly not under any robot), paginated 24 at a time. |       |
| G3  | Select several → Robot "Rover", Category → Add                                                             | Parts now sit under Rover › <category>; they keep their source origin and ids (no copies).                          |       |
| G4  | Attach one of them to a second robot                                                                       | 409 naming the robot that already owns it. Unknown id → 404. More than 64 ids → 422.                                |       |

API twin: `GET $H/unassigned?limit=24` · `POST $H/robots/<ROBOT_ID>/parts/attach
{"entity_ids":[…],"category":"structure"}`.

## Flow H — Bench session from a robot's config (R3)

| #   | Step                                                                                                                   | Expected                                                                                                                                                             | ✅/❌ |
| --- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| H1  | `POST …/bench/sessions {"mode":"real","config":{"provider":"robot","robot_entity_id":"<ROBOT_ID>"}}` for a bound robot | 201; `provider: robot`; `device.device_ref` is the serial key and `device.driver_id` the config's driver; no port path or baud in the request — all from the config. |       |
| H2  | Same for a robot with no identity (library-only)                                                                       | 422 "needs an identity and a protocol before it can open".                                                                                                           |       |
| H3  | Same while another session holds the port                                                                              | The open fails honestly (device busy / not found), never a silent zero-ingest session.                                                                               |       |
| H4  | `GET …/bench/recent/<PART_ID>` during H1                                                                               | A series named `<function>.position` with unit from the config.                                                                                                      |       |

## Flow I — Telemetry library (R3) **(human step: needs a board)**

Flash `libs/solus-telemetry/arduino/examples/NanoSixChannels` (Arduino IDE or arduino-cli, board
Arduino Nano, 115200 baud). Then Detected → the Nano appears at the **transport** level (USB
bridge); Propose → the framing interrogator recognises the line protocol, driver `raw-lines`
or `lb06`, six rows by address with the sketch's channel names; Confirm → Live Bench streams the
six channels at ~35 Hz effective. The MicroPython and Python emitters in the same directory
produce the same frames (parity test in `libs/solus-telemetry/tests`).

## Flow J — Generalisation proofs **(fixture only, in CI)**

- `livebench/tests/lb_three_machines_test.py`: a flight controller over UDP, a CAN drive base
  and a bare line-protocol rover all onboard through the identical shared code path
  (module-set equality asserted), and every packet carries a part key.
- `livebench/tests/lb_vendor_hygiene_test.py`, `packages/api/tests/test_vendor_hygiene_api.py`,
  `apps/desktop/…/hardware/vendorHygiene.test.ts`: no vendor or product name in shared code.
  Add the word "feetech" to a comment in `livebench/src/livebench/hardware/connection.py` →
  the ratchet fails. Revert.

## Permission and isolation

| #   | Step                                                                                                          | Expected                                                                                                                                   | ✅/❌ |
| --- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| P1  | `<TOKEN_B>` reads `$H/detected`, `$H/robots/<ROBOT_ID>/config`, `$H/suggestions` of `<PROJECT_ID>`            | 404 (no existence leak).                                                                                                                   |       |
| P2  | `<TOKEN_B>` accepts a suggestion id from `<PROJECT_ID>` under `<PROJECT_B>`                                   | 404.                                                                                                                                       |       |
| P3  | A **viewer** of `<PROJECT_ID>` calls any POST/PUT hardware route                                              | 403. Reads still 200.                                                                                                                      |       |
| P4  | No token                                                                                                      | 401.                                                                                                                                       |       |
| P5  | `POST $H/detected/../confirm` or a device ref with `/`, spaces or a path (`/dev/ttyACM0`)                     | 422, or 404 when the path cannot even route (device refs are `<transport>:<binding>`; a path is never accepted as identity). `repo_root` that is relative or does not exist → 422. |       |
| P6  | `PUT $H/robots/<ROBOT_ID>/config` with an unknown field, a document over 64 KiB, or more than 256 bus entries | 422; the stored document is unchanged.                                                                                                     |       |

## Cross-feature interactions

- **Workspace graph**: confirmed / imported / authored robots appear as manual `physical_robot`
  roots with category children; parts are `part` entities under them. Detected parts keep
  `origin: manual` (provenance lives in the config, not in `origin`).
- **`.solus` Hardware configs**: one `config` entry per robot; editing its text is refused (409); deleting it soft-deletes the entry and the next hardware write creates a fresh one (record what you see); the entry's `payload` is the exact document `GET …/config` returns.
- **Events / activity feed**: `hardware.part_created`, `hardware.lifecycle_promoted`,
  `hardware.proposal_built`, `hardware.robot_confirmed`, `hardware.suggestion_created`,
  `hardware.suggestion_decided`, `hardware.library_imported`, `hardware.config_updated` appear
  for the matching steps.
- **Live Bench**: the robot session is the same session type as serial/sim ones (list, get,
  stop); the Sources screen's local-connections list still works unchanged for raw serial.
- **Fingerprint**: no automatic merge ever happens from a proposal; link suggestions are the
  only cross-entity link and they require a click.

## Known limitations to expect (not failures)

- A robot bound from a library platform keeps the library's calibration mode; real calibration
  values come only from a repo config (Flow D) — the library has none.
- Port-path repair is advice only: Solus reports the configured vs actual path and the file or command to change; it never writes to the repo.
- If two parts' declared channel names share the same `<part>` prefix, only exactly declared
  names route to those parts; an undeclared `<prefix>.x` signal stays on the device key and
  counts as unresolved.
- The Sourced card is intentionally disabled (sourcing is a later ticket).
