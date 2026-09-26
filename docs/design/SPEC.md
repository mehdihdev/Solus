# Solus — Product Spec (docs/design/SPEC.md)

This is the written spec every ticket prompt references. Screens from the design pass live beside it
in `docs/design/screens/<surface>-<state>.png` when they exist; until then this document is the
source of truth. Solus is a desktop (Electron) robotics development platform: dark-first, dense but
legible, open all day beside the user's real tools.

Solus connects a user's existing tools (Onshape, Fusion, SolidWorks, GitHub, KiCad, Altium, ANSYS,
their robot, their simulator) into one graph that recognises the same physical part everywhere it
appears, explains failures **across mechanical, electrical and software**, and operates those tools
through **SOL**, its agent. Three users share it without configuring anything: an ML researcher
debugging a robot arm, a hobbyist building from scratch, and a Formula SAE electronics lead.

---

## Top-level navigation

```
Home | Workspace | Live Bench | SOL | Store  ‖  [pinned widgets…]
```

Widgets installed from the Store get their own tab **after a visual separator**. A user can
right-click a widget tab and **pin it for all projects**; otherwise it is per-project.

---

## 1. Home — projects and the whole account

**Purpose:** manage across teams and projects, and connect **entire accounts** (not documents).

- **Teams:** the active team is always visible; a switcher appears only when the user belongs to more
  than one. Each team shows its members with roles (owner can change roles and remove), a
  **one-time invite token** to add someone, join-by-token, and a humanised activity feed. Every user
  has a personal team that is exempt from plan limits. Projects belong to a team; a later joiner
  gains access to the team's existing projects automatically. Plan limits on collaborative teams show
  honestly when reached, with the upgrade path, never as a silent failure.
- Project grid (scoped to the active team): create, open, switch, archive, recent activity per project.
- **Account connections:** connecting Onshape, GitHub, Fusion, etc. binds the *whole account* here.
  Picking specific documents happens later, in Workspace. Show connection health and API quota
  position per account (approaching a limit is visible before it hits).
- **Preferences — "how I engineer":** the user's own conventions for code style, mechanical and
  electrical design, documentation. This is the Solus equivalent of a `claude.md`. Editable here;
  SOL reads it on every turn. Most of the rest of the root configuration is hidden from the user.

---

## 2. Workspace — the graph, made usable

**This replaces the old Graph page.** The graph is still the center, but Workspace is where a
project's specific documents, repos and hardware are brought in and organised.

**On project creation**, an empty project-level `.solus` appears with five sections:
**Hardware configs · Project details · Error logging · Documentation · Code environment.**
Right-clicking **any** section offers the same three actions: **Import files** (e.g. Formula SAE
rules), **Ask SOL to find** (a search box), **Type it** (a plain text box). Error logging is
editable by the user too.

**The Add button (top-left)** opens a panel with two tabs:

*From a service* — lists the accounts connected in Home. Each has a dropdown of that service's
documents/repos/projects. Clicking one **creates a node in the graph** and syncs it on that first
select; afterwards it only syncs when the source changes. Adding a second document from the same
service creates another node of the same type. A document may belong to more than one project.

*Hardware* — the five ways a physical part enters (section 3).

**Node zoom (Prezi-like):** hover a node and scroll to zoom *into* it, revealing what constitutes
it. Onshape document → assemblies → parts. GitHub repo → directories → files. Physical Robot →
categories (sensors, actuators/motors, controllers, end effectors, power, structure, wiring) →
individual parts. Never draw hundreds of nodes at one level.

**Physical Robot** is a node *type*. A project can have several (a leader and a follower arm; a
drone and its ground station). One is created automatically when hardware is detected, or manually;
default name is the project's; renameable.

**Widget nodes:** Live Bench and each installed widget (e.g. BOM) appear as high-level nodes.

**Link suggestions:** when something new arrives (a CAD gripper, a detected device) and plausibly
belongs to an existing robot, it spawns *separately* and Solus **suggests** the connection. The user
accepts or declines; can also connect manually (drag, or right-click → Attach to…), or tell SOL.

---

## 3. Hardware onboarding — the five paths, as buttons

From **Add → Hardware**, five cards. Be exact about every click.

**Detected — "Plugged in right now."** Devices appear continuously as they are found over **USB,
USB-CAN, Bluetooth, WiFi (mDNS) and MAVLink** — no scan button needed. Each shows what is honestly
known at each layer: the transport (*USB, serial 5B42…*), the board or bridge (*CH343 USB-serial
bridge — MCU unknown*), and, after a safe interrogation, the bus (*six STS3215 on a Feetech bus, IDs
1–6*). Click a device → **Add as new Physical Robot** or **Add to [existing robot ▾]** → Solus
proposes servo/channel → function mappings with confidence and evidence → one-click **Accept** per
row, **Accept all**, or **Reject** → done. Config written, transport opened, streaming begins.
Two identical arms are distinguished by USB serial and labelled so; a re-plugged robot reconnects
silently, and one whose servo count changed is re-proposed rather than assumed.
Design the device card at all three levels of knowledge, including the fully-unknown case ("unknown
MCU, six float channels at 100 Hz — name them?").

**From a file — "Parsed from what's already here."** Lists parts found in connected CAD, schematics
and BOMs that aren't yet assigned to a robot. Multi-select → **Add to [robot ▾]**.

**Library — "A known platform or part."** The library has **two levels**: *parts* (an STS3215
servo, an MPU-6050 IMU, a BTS7960 driver — with specs) and *platforms* (whole robots composed from
parts: SO-101, Unitree G1, UR5, common drone stacks). Search either. A platform preview shows its
actuators, kinematics, bus map and protocol → **Import** → a Physical Robot node with all of its parts
and joints, config written. A part imports into a chosen robot's category. Where a vendor ships an MHS
driver, the definition is marked *vendor-authored*.

**Sourced — "I need a part."** A requirements box (*"holds 2 kg at 30 cm"*) **or** a button
**Derive from CAD** (Solus computes required torque from geometry and mass). SOL returns candidates
with trade-offs (torque, cost, weight, protocol), filtered by the project's compliance rules → compare
side by side → **Select** → the part enters as *planned*, and its vendor CAD model can be dropped into
the assembly.

**Authored — "Define a custom part."** A form: name, category, key specs → **Create**.

**Lifecycle state on every part** — planned · ordered · received · installed · live — shown
consistently in Workspace, Live Bench and BOM. A planned part is visibly not yet wired.

**Transport and connection state** — every robot shows how it is connected (USB serial / CAN /
Bluetooth / WiFi / ROS 2) and whether it is streaming, stale, or disconnected, with reconnect inline.
A from-scratch robot can adopt the **Solus telemetry library** (one include for Arduino / MicroPython
/ Python) to get named, unit-tagged channels; design the moment Solus offers it.

Right-click any part: **Attach to robot · Edit config · Open in [tool] · Show evidence.**

---

## 4. Live Bench — the robot, live

Fed by **Physical Robot nodes**. Shows only what is connected; nothing configured.

- **Sim scene** (left): robots linked to their CAD, **live-updated when the CAD changes**. Multiple
  robots, independently placeable, mirroring real motion.
- **Telemetry** (right): one widget per signal from motors, motor controllers, CAN. Current value,
  rolling chart, anomaly markers. Names default to `RobotName-Motor-3` and rename inline. Units come
  from the data; a dropdown converts for display.
- **Sensor panes:** LiDAR point cloud, camera feed, time-aligned with telemetry.
- **Live reasoning:** SOL watches the run and surfaces findings — *what could be going wrong* — each
  as headline → explanation → detail, spanning domains where the cause does.
- **Live test:** run the robot, capture everything during the run, compare against expected or a
  previous run.

---

## 5. SOL

**The SOL tab** holds the chats. **No model picker.** The reasoner is labelled `sol-reasoner-1`;
routing happens invisibly. Streaming must be smooth.

**Two modes, toggled by double-tapping Ctrl:**
- **Guide** — an orb appears over the *external* tool (Onshape, KiCad…), **highlights the control to
  click, and shows text beside it** explaining what the tool does and what to do next. Guide only
  points and explains; it never executes.
- **Build** — SOL does it, operating the tool through its API. Destructive actions still show a
  **diff** and wait for approval — the same approval card for a CAD edit, a firmware flash, or a
  robot motion.

**Ctrl+Space spawns a SOL panel anywhere on screen, even over other applications**, as long as Solus
is running. The panel can **screen-grab the active window** for context (what app, what tool is
open) — show a clear indicator when it does.

**Artifacts:** when SOL produces something (wiring steps with images, a script, a diagram) it asks
**"File this to…?"** with the `.solus` sections as choices. When it runs code and hits an error, the
error is filed to **Error logging** automatically.

Design: the chat tab; the orb pointing at a control in an external app with its explanation beside
it; Build executing with the approval card; the floating panel over another application; the
filing dialog.

---

## 6. Store and widgets

A widget is an **extension**: it adds a tab (after the separator), a high-level graph node, and
abilities for SOL. Store: browse, detail (what it adds, what it needs connected), install,
uninstall. Right-click the tab → **Pin for all projects**.

**BOM (first widget):** every part in the robot, raw materials, anything purchased. One row per
canonical part (a part in CAD, schematic and BOM is *one* row). Lifecycle state per row. **Find
compatible parts** for a selected row, honouring the project's compliance rules.

---

## Principles that must hold on every screen

**Derive, never configure.** **One connection is useful alone.** **Explain, don't just display** —
none of these users knows what stall current is. **Empty beats invented** — no data, no unit, no
joint name, no confident pointer → say so. **Propose, never assert** — matches and mappings are
proposals confirmed with one click; low confidence stays visibly unconfirmed. **Empty states are
deliberate** — a bare workspace looks designed, not broken.

## Section map for ticket prompts

| Epic | Read |
|---|---|
| Home | §1 |
| Workspace | §2 (Add, `.solus`, node zoom, Physical Robot, link suggestions) |
| Robot onboarding | §3 |
| Live Bench | §4 |
| SOL | §5 |
| Store + Widgets | §6 |
| Integrations | §1 (account connections), §2 (Add → From a service), §3 (Detected/transports) |
| Engineering corpus | §5 (SOL context layering) |

Companion documents: `Solus-Design-Doc-v2.md` (architecture and the why), `Solus-User-Flow-Spec.md`
(principles and per-user flows).