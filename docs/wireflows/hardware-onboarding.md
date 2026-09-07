# Wireflow — Hardware onboarding (SOLUSDEV-248: R1 / R2 / R4)

Authority: the SOLUSDEV-248 ticket brief; `docs/architecture/hardware-onboarding.md`;
`docs/api/hardware.md` (routes). This file governs the flow; visual polish within it is
implementer judgment (CLAUDE.md §3). Every claim a card makes comes from a live backend response —
offline / runner-absent degrades to honest copy with disabled controls, never fabricated
availability. Nothing on this surface auto-accepts: a proposal becomes a graph fact only when the
user confirms it (ADR-012).

## Where it lives

The **Hardware** tab of the workspace **Add** panel (`features/graph/WorkspaceAdd.tsx`, the
`hardware` prop) — `HardwareAddPanel` replaces today's single "Add Physical Robot" button with
five `ConnectTile`-style cards. Each card opens a `ModalShell` flow; Escape or an outside click
closes the modal before affecting graph navigation (`workspace.md` §Add).

```
| Add › Hardware                                                              |
| [ Detected  n ] [ From a file  n ] [ Library ] [ Sourced ] [ Authored ]            |
```

## Flow 1 — Detected (the proposal, not the form)

1. Card shows the live device count from `GET /hardware/detected`. Open → a list of every
   enumerated device **at whichever level is known** (`deviceTitle`): a board name, a machine name
   when an interrogator answered, or "USB-serial bridge — MCU unknown" for a CH343 — never a
   guessed board. The `transport:binding` identity (USB serial) is always shown; a device with no
   serial is marked unverified after replug.
2. Click a device → `POST /hardware/detected/{device_ref}/propose` → `RecognitionPanel` mounts
   with real `MappingProposal`s: one row per proposed part (bus address, model, proposed name,
   category), each with its **confidence** and its **evidence** (the `ModalityMatch` list: what was
   pinged, what answered, which repo config matched). A row below threshold is shown as such, not
   hidden and not pre-accepted.
3. When more than one repo config matches (lerobot leader and follower are wire-identical) a
   **disambiguation radio** asks once — "Which arm is this?" — and the answer is recorded as
   `disambiguated_by: user`. The second device is offered the remaining config. No local checkout
   linked → the panel says so and proposes from wire evidence only.
4. Target: **Add as new Physical Robot** (default name is the project's name, editable) or
   **Add to [robot ▾]** listing the project's existing robots. No robots yet → only the first
   option is offered.
5. Per row **Accept** / **Reject**; **Accept all** accepts every row at or above threshold. A
   rejected row is dropped from confirm and recorded as rejected evidence.
6. **Confirm** → `POST /hardware/detected/{device_ref}/confirm` with the accepted rows. Expected:
   the robot exists (created through the same service as manual creation, or the chosen one),
   accepted parts sit under their categories with `external_ref = <device_ref>/<address>`, the
   robot's `.solus` Hardware-configs entry holds the config (provenance `detected` / `repo`), and a
   bench session opens via `POST /bench/sessions {mode: real, config: {provider: robot,
   robot_entity_id}}`. The navigator focuses the new robot; Live Bench shows named joints in their
   real units (six joints in `deg`, gripper in `%` for the reference arm) and the link state is
   derived, never asserted.
7. If the matched repo config binds a port that no longer matches the device, SOL offers a
   **port-path repair** confirmation card (DiffRow): it applies only when a local checkout path is
   known; otherwise it shows the corrected command line and applies nothing.

## Flow 2 — From a file

1. Card shows the count of parts from connected CAD / schematic / BOM sources that no robot owns.
   Open → the list, grouped by source document, with the part's real graph identity.
2. Multi-select → **Add to [robot ▾]** and a category pick → the parts move under that category;
   their source identity and cross-domain edges are untouched. No connected source with unassigned
   parts → "No unassigned parts from connected sources." with a link to Add › From a service.

## Flow 3 — Library

1. Open → a search box (`GET /hardware/library?q=`) returning **parts** and **platforms** as two
   groups. Empty query shows the curated seed; no match → "Nothing in the library matches."
2. Select → preview (`GET /hardware/library/{kind}/{id}`): a part shows its category and key
   specs; a platform shows its part list and platform-only facts (gear-ratio tables).
3. A part → **Import into [robot ▾]** + category → `POST /hardware/library/parts/{id}/import
   {robot_id, category}`. A platform → **Import as new robot** →
   `POST /hardware/library/platforms/{id}/import` → robot + parts + config, every value with
   provenance `library`.
4. A library robot later matched by a detected device produces one pending **link suggestion**
   (`GET /hardware/suggestions?status=pending`), never a second robot; the user accepts or rejects
   it (`POST /hardware/suggestions/{id}/accept|reject`).

## Flow 4 — Sourced

Footer "Find a part". Open → the sourcing panel (STORE ST5, `sourcing.md`) on its **Workspace
door**: the same two-door panel the BOM uses, defaulting to *From CAD* so SOL derives the torque
from one of the project's assemblies; the selected candidate enters the chosen robot category as
a PLANNED part and the robot view reloads (`onCreated`). Offline the card is disabled like the
other four.

## Flow 5 — Authored

1. Open → form: **Name**, **Category** (the seven: Sensors, Actuators / motors, Controllers, End
   effectors, Power, Structure, Wiring), **Lifecycle** (planned · ordered · received · installed ·
   live), and **key specs by category**. Spec fields are generic to the category, not to a product
   family: an actuator asks for interface (PWM, serial bus, CAN, pneumatic pilot, …), supply, and
   a rated output with its unit — so a pneumatic valve (flow), an ESC (current) and a servo
   (torque) fill the same fields as naturally. Manufacturer part number is optional everywhere.
2. Target: **under [robot ▾]** or **new Physical Robot** (created first through the same service).
3. **Create** → `POST /hardware/robots/{robot_id}/parts {name, category, specs}` → the part
   appears under the chosen category with `origin=manual`, and the robot's config entry gains it
   with provenance `user`. Later promotion goes through `POST …/parts/{part_id}/lifecycle` and
   changes neither the part's id nor its edges.

## Empty / error / offline states (all honest)

- Runner absent (livebench not loaded by the local API): Detected card disabled with that reason;
  the other four cards stay usable — they are API-only.
- API unreachable: the panel renders offline copy; counts are omitted, not invented.
- No devices: "No devices detected." with the enumerate hint (USB, CAN adapter, network).
- Propose / confirm failure: the backend's error verbatim (validation text, `device_ambiguous` +
  candidates, `source_unavailable`, a device already confirmed to a robot names that robot).
- Repo config found but its calibration file is missing: the proposal proceeds with the part names
  and says calibration will import when the file appears.
- Detected but no bench session cap slot: the robot and config are still created; the session
  error is shown on the robot with a Retry, never a silent success card.

## Copy (ADR-016 — SOL mode)

Row and step copy consumes the user's mode. **Guide** explains the evidence ("Solus pinged bus ids
1–6; each answered with model 777, which the library knows as STS3215…") and what confirm will
write; **Expert** is terse ("6 × STS3215 on usb:5B42134331, config from lerobot"). Live engine
claims — confidences, device titles, backend errors — are always shown verbatim, never rephrased.
