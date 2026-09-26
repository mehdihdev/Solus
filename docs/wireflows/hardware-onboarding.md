# Wireflow — Hardware onboarding (SOLUSDEV-250/260 integration)

Authority: the September 15 UI brief supersedes earlier presentation in the SOLUSDEV-248 and SOLUSDEV-250 ticket briefs; `docs/architecture/hardware-onboarding.md`;
`docs/api/hardware.md` (routes). This file governs the flow; visual polish within it is
implementer judgment (CLAUDE.md §3). Every claim a card makes comes from a live backend response —
offline / runner-absent degrades to honest copy with disabled controls, never fabricated
availability. Nothing on this surface auto-accepts: a proposal becomes a graph fact only when the
user adds it (ADR-012). A name can save hardware context; driver/configuration and actual
packets are separate requirements for connection and streaming. This document reconciles the
current inline 250 flow with 251/260 storage and privacy rules. The later 253/256 two-screen
review and standalone-part UI remain targets, not descriptions of shipped controls.

## Where it lives

Two places, one model:

1. The **Hardware** tab of the workspace **Add** panel (`features/graph/WorkspaceAdd.tsx`, the
   `hardware` prop → `HardwareAddPanel`). Inline sections lead to a collapsed unassigned
   disclosure. Private local configuration/calibration sources appear directly below detected
   devices, with Choose local file, Verify and Relink controls. They are not hidden inside
   Unassigned parts; that disclosure retains the connector-parts flow.

```
| Add › Hardware                                                            |
| <intro line — SOL mode>                                                   |
| Devices found            <live list of pending device cards>              |
| Local configuration and calibration   [Choose local file] [Refresh]       |
| Search                   [ Search parts and platforms — e.g. … ]          |
|                          rows: name · part|platform · summary · action    |
|                          supplier results inline after explicit search    |
| Describe something new   [ What is it? ] [Add]                             |
|                          optional ownership/category details inline       |
| ▸ Unassigned parts                                                        |
```

2. **Pending device cards at the canvas edge** — the same cards, docked along the workspace edge
   while a detected device is unbound, so a device plugged in mid-session is visible without
   opening Add. A card is one entity in both places (`useDetectedDevices()` seeded on ready and kept
   current by `hardware.devices_changed`); adding or dismissing it in either place clears both.

Escape or an outside click closes Add before affecting graph navigation (`workspace.md` §Add).

## Flow 1 — Devices found (the one-question card)

One card per device the machine can see that is not yet bound in the graph and not dismissed.
A card is **a sentence, one question, Add**:

1. **Sentence** — the wire's `headline`, said by tone (`looks_like` · `probably` · `something`),
   then the `summary` verbatim: "Probably · Arduino-class board on USB · 4 channels at 50 Hz · your
   sketch names them motor_l, motor_r, dist, batt". Identity is shown as far as it is known: the
   USB serial, or “no serial number — identity is tied to this USB port; keep it plugged in
   here” for a port-bound serial-less device. The same explanation appears in the sidebar. A device with no binding at all cannot be proposed
   and says so.
2. **One question** — the card asks only what the wire could not settle:
   - Nothing unsettled → **the name**, initially empty and required; the headline is only a
     placeholder/suggestion. Existing robot names are preserved.
   - Two repo configs match (leader and follower are wire-identical) → the wire's
     `disambiguation.question` with its options as a radio ("Which arm is this?"); the answer is
     recorded as `disambiguated_by: user` and the second device is offered the remaining option.
   - A library robot already in the graph matches (a pending link suggestion names it) → **"It's
     <robot>"** is the first choice, binding the device to that robot on Add; "a new robot" and the
     project's other robots follow. Accepting resolves the suggestion; rejecting records it.
   - Existing robots and no suggestion → **Part of ▾** (new robot first, then the robots).
3. **Add** explicitly accepts the shown proposed rows and chosen target, using the current
   propose/confirm routes or the existing suggestion acceptance flow. Proposals may use safe
   ping/listen interrogation; passive enumeration itself opens no device. No motion is implied.
   The renderer sends no raw `repo_root`: a non-null request path is refused. The transaction
   saves the robot and independent per-entity v2 component/connection configs, preserving prior
   fields and provenance. The navigator shows the saved node immediately as **Connecting…**
   when session start was requested; confirmation does not wait for driver opening.
   Existing project graph events refresh terminal connection state. A connection failure leaves
   the saved node with a portable error and retry using its ID. Live Bench shows **Receiving
   data** only after actual packets, with channels/units derived from verified capabilities.
4. **Dismiss** hides the card for this session; the device stays in the store and returns on the
   next removal/reappearance cycle; repeated unchanged full frames do not undo dismissal.
5. Proposal rows and their evidence (the `ModalityMatch` list: what was pinged, what answered,
   which repo config matched) stay one disclosure away on the card — shown, never hidden, never
   pre-decided beyond the accept-all that Add means. A row below threshold is marked as such.
6. A missing or changed calibration source requests explicit native relinking/review.
   No port-path repair or repo write occurs automatically. An authorized future write-back must
   show its concrete change through the existing confirmation gate.

## Flow 2 — Unassigned parts (collapsed disclosure)

1. Collapsed by default; **nothing is read until it opens** — never on mount, never on a graph
   revision. Open → one paged list using the unified `GET /hardware/unassigned` query,
   covering manual, retained and connector-sourced parts without a live manual owner. Do not
   also fetch the orphan endpoint or show the same UUID twice. **Load more** extends this
   source. Rows show names and types, never identifiers.
2. Each row: **Part of ▾** (the project's robots, the first preselected) + **Category ▾**
   (defaults to Structure) + **Add** → `POST /hardware/robots/{robot_id}/parts/attach
{entity_ids: [id], category}`; the row leaves the list. Source identity, independent component config/provenance and cross-domain edges
   are untouched. A stale owner/config returns 409; a deleted part returns 404. Preserve the
   choice and show an honest recovery message rather than a successful attachment.
3. No robot yet → the rows list with "No robot to add these to yet." and no target. The unified list
   settled and empty → "Nothing unassigned."; a failed read shows the backend's error verbatim and
   never claims emptiness over it.

## Flow 3 — Search

1. One box (`GET /hardware/library?q=`, 250 ms debounce; empty input keeps the panel compact).
   Placeholder names no product. Results are one flat list: **name · kind (part | platform) ·
   summary**. No match → "Nothing in the library matches."; a failed search shows the error verbatim.
2. A **platform** row → **Add as new robot** reveals an inline name field (empty, placeholder =
   the platform's name) + **Add** → `POST /hardware/library/platforms/{id}/import {name}` →
   robot + parts + config with provenance `library`; the robot view reloads. When the import raised
   link suggestions against detected devices the row says "A link suggestion is pending — the
   device card offers it." (no ids).
3. A **part** row provides an inline required name and optional robot placement, followed by
   **Add** → `POST /hardware/library/parts/{id}/import {name, robot_id?}`. Without a robot,
   this creates one standalone part and its independent library-provenance config. It requires
   `Idempotency-Key`; retries of an uncertain operation retain that key, while a completed
   operation clears it. Existing robot imports preserve the definition's default category.
4. Every row has a **Details** disclosure that lazily reads `GET /hardware/library/{kind}/{id}`
   and lists the definition's facts as-is: maker, driver, notes, key specs (resolution,
   calibration, telemetry channels) for a part; the slots (role · part @ address) for a platform.
   No preview pane — nothing is hidden, and specs belong to the sidebar later.

## Flow 4 — Supplier results in Search

Supplier search uses the same query as the library search and the existing sourcing engine.
An explicit credit-labelled action starts metered work; typing and opening Hardware do not.
Results, progress, errors and specs stay inline. Selecting an actual supplier candidate uses
the existing planned-part selection endpoint and refreshes the graph. No Hardware sourcing modal
or separate Sourced section remains. The independent BOM sourcing flow is retained.

## Flow 5 — Describe something new

1. One field, **What is it?** Optional inline details expose **Category ▾**, following a deterministic keyword
   guess over the name (`categoryFromName`: motor / servo / pump / valve → Actuators; camera /
   encoder / pressure → Sensors; battery / regulator → Power; controller / board → Controllers;
   gripper / suction → End effectors; cable / connector → Wiring; else Structure) and is marked
   **suggested** until the user picks one; this local fallback is not represented as a SOL model call. The pick sticks. **Part of ▾** lists the robots, the
   first preselected.
2. **Add** with a robot → `POST /hardware/robots/{robot_id}/parts {name, category, specs: {},
lifecycle: planned}` → the part appears under the category with `origin=manual`; the field
   clears. **Add with no robot** → `POST /hardware/entities {kind: part, name}` creates an
   unassigned part without a container robot. Description and Add alone suffice; specs are optional.
3. No spec fields here. Guide mode says why: "Specs come later — from SOL, from a datasheet, or
   never." Later promotion goes through `POST …/parts/{part_id}/lifecycle` and changes neither
   the part's id nor its edges. `HARDWARE_SPEC_FIELDS` (generic per category, never per product
   family) is kept for the sidebar.

## Empty / error / offline states (all honest)

- Offline (signed out or no project): one line — "Connect this project to add hardware." — and
  every control disabled; no device list is rendered and nothing is read.
- Runner absent (livebench not loaded by the local API): Devices found says so with the reason
  verbatim; Search, Describe, Sourced and Unassigned parts stay usable — they are API-only.
- No devices: "Nothing found yet" with the enumerate hint (USB, CAN adapter, network) — never a
  count that was not observed; the store's never-seeded state reads as "looking", not as empty.
- Propose / confirm failure: show the portable typed backend message for absent/ambiguous
  devices, unavailable runner or conflicting configuration. Never show private paths or another
  project's identifiers. Cached proposal + unplug still refuses confirmation without new nodes.
- Missing/changed calibration file: preserve saved values and request relink/review. File
  appearance never silently imports or replaces calibration.
- Confirmed but no bench session cap slot: the robot and config are still created; the session
  error is shown on the robot with a Retry, never a silent success card.
- Search / import / attach / describe failures: preserve the draft. Explain 404 as a deleted
  or unavailable part and 409 as a version/ownership conflict requiring refresh and review.

## Copy (ADR-016 — SOL mode)

Section copy (`HARDWARE_COPY`: intro · devices · search · describe · unassigned) consumes the
user's mode. **Guide** explains the surface and what Add will save; **Expert** is terse.
Distinguish passive enumeration from the safe ping/listen work a proposal may perform. Neither
permits motion. Headlines, summaries, confidence language and device identity reflect actual
evidence. Error copy explains the portable typed failure without exposing raw backend internals.

## Configuration, local source references and deletion

Selecting a Hardware CONFIG opens the v2 editor for its configured subject, not a note editor.
GET is pure; absence remains absent until explicit first save. Save sends the expected version,
preserves unrelated fields and records changed leaves with user provenance. A 409 retains the
draft and offers reload. CODE CONFIG keeps its separate environment view.

The source subsection lists opaque references, opens MAIN's native picker and rechecks bytes.
Shared `source:<UUID>` maps to a bare UUID IPC key. An approved migrated reference can be
explicitly relinked; known same-file picks normally reuse their reference. Changed bytes require
review before private authorization is updated. Paths stay in the account/project private store;
shared calibration values and provenance never change merely because a file was relinked.
Browser-only use shows honest native-picker unavailability. Unknown/corrupt/newer private state
is not silently reset. Late list/pick/recheck and CONFIG read/write responses are discarded across
account/project/entity changes, including A→B→A.

Robot deletion uses the sidebar's concrete two-step confirmation, retains parts and independent
configs, disables obsolete bindings, cancels pending connection work and releases the device.
The same unified unassigned list exposes retained parts after reload. CONFIG deletion names its
binding effects and cannot trigger recreation through a later GET.

## Acceptance and later review design

The approved later 253/256 two-screen journey unifies detected/library/authored/imported inputs,
requires review and names for every newly materialized child, supports standalone part creation
and separates Add from Add and connect. Its observation-generation/revision APIs are not implied
by the current compatibility cards. Preserve these goals without describing absent controls as
working features.

Exercise the 250 33-step QA against the merged Electron build, including delete/reclaim,
serial-less copy, two simultaneous confirms, replug and late-response rejection. Measure
confirmation response-to-node separately from browser receipt-to-card and physical detection.
Native picker, calibration relink and actual arm streaming remain unverified until exercised;
fixture or API success alone does not establish those gates. No motion or flashing is part of QA.

## SOLUSDEV-262 — brain-first presentation (implementation in progress)

The new user brief replaces category zoom with robot → brain → bus → device → part. Category
chips filter parts while preserving their ancestor context. Host, MCU and onboard cards show
known software/firmware, channel and downstream wiring; missing facts say unknown. A board
that is both an upstream device and downstream brain appears once. Existing names and part
identity persist; new name fields remain empty and no proposal is auto-accepted.

Cards remain canvas-edge/Add-panel controls. Bare-MCU onboarding asks one question at a time:
what is wired → typed/schematic/probe evidence → review topology → generated-sketch diff →
approve flash → observe actual telemetry. Probe cards explicitly disclose firmware erasure;
floating analog values do not assert connected parts. A missing USB serial is visibly explained.

### Reviewed host and local control software

An endpoint brain card offers “Connect this computer” within the existing canvas card. It uses
the current project's local folder source and the desktop companion identity. If no folder is
linked, reuse the existing project-folder selector in the card. Only local code/folder entities
from that source are available as control-software choices; linked remote repositories remain
references. Show the selected folder/software name before requesting a topology proposal.
The review shows host → USB → endpoint, the existing downstream wiring, and provenance. A
separate confirmation applies the graph change; cancel does not apply it. Selection changes,
project/account changes, or stale evidence invalidate the pending review. Unavailable desktop
identity/bridge and unsynchronized local sources explain why connection is unavailable.
The resulting card describes software as a user declaration, not proof of a running process
or installed telemetry shim. Unknown endpoint type remains unknown unless explicitly declared.

### SOLUSDEV-262 W5 — registered widget roots

Project overview lifts persisted Live Bench and installed widget registrations into top-level
nodes, preserving graph UUIDs and underlying contains relations. No installed registration means
no fabricated widget node. Cards show installation/blocked state and open the existing supported
page view; disabled or blocked widgets explain their state and cannot open. Live Bench opens its
existing tab. Installation/removal refreshes this projection from current project graph data.
For older projects whose persisted registration layer is absent, Workspace initializes it through
the existing member-authorized reconcile action, then rereads the graph. Failed initialization
shows a bounded retry control; a viewer is told that a project member must initialize widgets.

### Local evidence review

Within the existing brain card, select a local evidence file using the native hardware-source
picker, choose firmware or configuration, then request extraction. Cancellation leaves no review.
Show candidates with their original pin/address provenance and unknown/conflicting facts. Explain
that this is source evidence, not verified wiring or running code. No accept/connect/flash action
is implied by this review. Changing file, kind, brain, robot, project or account invalidates it,
including A→B→A transitions. Browser preview explains unavailable native selection.

Extraction review shows selectable bounded rows, explicit editable names, and a Confirm evidence
button. Nothing is preselected or autoaccepted. Empty success says no evidence was found. Confirm
revalidates the exact source and graph proposal; stale source resets review. Success identifies
retained/created nodes and refreshes the brain tree. This evidence-only operation does not connect
hardware, change calibration or deploy code.

### Presence firmware card

An MCU brain offers explicit board profile and heartbeat/probe selection. Preparing displays the
complete generated source, exact observed target and binary digest; probe explains erasure and
raw analog/I2C limits. It never claims CH340 identifies an Uno or empty firmware. Request flash
review sends only the retained plan ID through the existing SOL Build chat and registered
hardware.flash_presence tool, then shows the existing complete-source confirmation card.
Preparation and requesting review do not approve a flash. Profiles unavailable or configured
actuator boards remain blocked. Account/project/brain/profile changes discard stale responses.

A transport-only USB device with no recognized protocol offers Add MCU connection after the user
enters a name. This records only the observed connection, then reveals its brain/presence card;
it starts no telemetry and claims neither empty firmware nor a specific board. Named channel
acceptance sends only explicit user/proposal names; unnamed actuator rows use the server's stable
RobotName-Motor-N default, not an invented client channel name.

### Host mirror offer

After explicitly accepting a host and local control source, offer a Python loop-file selection
within that source. The user supplies the control-object name, insertion anchor, method, dictionary
signal mapping, argument selector when needed, units and loopback receiver port. Show the exact
`solus_telemetry` mirror snippet before requesting a change. SOL reads the chosen file through
existing authorized machine tools and offers a fingerprinted before/after diff at the central
confirmation gate. Missing write authority or an ambiguous anchor prevents the edit. The offer
never asserts that the shim is installed or that a control process is running. Selection and
account/project changes invalidate the offer; no remote repository is substituted for a local file.

An unassigned source part offers “Find robot links” as an explicit action in the existing robot
sidebar. Display a supported candidate by robot name with confidence and evidence, plus separate
Accept and Decline controls. No match is an honest result. Decline is remembered for the same
evidence; Accept revalidates before attaching the existing part. Account/project/part changes
invalidate outstanding results. No source part is autoattached from its name or a GET request.
# SOLUSDEV-262 wiring completion amendment

Inside the existing MCU presence card, offer three explicit choices: type wiring, use a
schematic, or inspect a recorded probe. Typed wiring collects channel, pin and input kind.
Schematic and probe choices select scoped existing evidence and show observations/confidence
and unresolved devices. A probe first uses the existing erase/code/target confirmation and
must be recorded before its observations can be selected. Never display floating pins as parts.
Review, then Accept wiring, then Prepare firmware are separate actions. Changing the profile,
source, target or declarations invalidates the prepared review. Empty accepted wiring produces
heartbeat only; named supported inputs produce readings. Existing firmware may be in a linked
repository; the full erase warning and complete generated source remain visible before flash.
