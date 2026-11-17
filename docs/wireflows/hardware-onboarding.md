# Wireflow — the Hardware page (SOLUSDEV-326)

**Last updated:** 2026-11-17 (SOLUSDEV-326: SOL is the shell's sidebar, after the merge of
SOLUSDEV-327; the page's own docked panel is removed).

Hardware onboarding happens with SOL, one card at a time, on one page: `features/hardware`
(`HardwareScreen`). SOL's tools propose and the person answers on a card
(`docs/contracts/action-gate.md` §Cards, open cards, notices and answers); nothing joins the graph
unasked (ADR-012). The earlier renderer flow (the Add › Hardware panel with Devices found, Search,
Describe something new and Unassigned parts, the detected-device cards on the canvas edge, the
robot-brain cards and the robot sidebar's Unassigned parts list) is removed; its routes remain on
the API (`docs/api/hardware.md`) for SOL's tools. Authority: `docs/architecture/hardware-onboarding.md`,
`docs/api/hardware.md`, the action-gate contract. Visual polish within this flow is implementer
judgment (CLAUDE.md §3).

## Ground rules

1. The page does not rearrange. Regions keep their place and size; content fills in.
2. One card at a time, one or two buttons. No steppers, checklists or option rows.
3. Approvals look different from offers and say what physically happens.
4. SOL narrates in the SOL sidebar; the card is where the person answers.
5. True states only. No bare spinners.
6. Card text is model- or tool-authored, and every name is someone's own text: all of it prints as
   text, never as HTML.

## Layout

```
| rail | Hardware                                   [+ Add hardware] | SOL  HARDWARE     ⤢  ×      |
|      | Robot parts Solus knows about, and whether …               |                             |
|      | ┌ card slot · 132 px · aria-live ────────────────────────┐ | SOL's messages              |
|      | │ one open card, or the working / start / idle line      │ | the person's messages       |
|      | └────────────────────────────────────────────────────────┘ |                             |
|      | Done so far: 3 servos added · Nano added        (30 px)    |                             |
|      | Robot parts · 4                                            | [Ask SOL, or tell it what   |
|      | PART   WHAT IT IS   ROBOT   IN WORKSPACE GRAPH   STATUS    |  you have]          [Send]  |
|      | Rover arm · 4 parts          not yet [Add robot]           |                             |
|      |   shoulder_pan  STS3215  Rover arm  not yet  ● Connected   |  (the SOL sidebar, when     |
|      | ▸ Described in your workspace, not seen yet · 4            |   open: ⌘J / Ctrl J)        |
```

The main column is at most 980 px wide with 24 px 28 px padding and scrolls on its own. The page
has no SOL panel of its own: SOL is the shell's sidebar (`docs/wireflows/sol-sidebar.md`), opened
and closed with its menu-bar toggle or ⌘J / Ctrl J like on every screen (one open state for the
whole shell, closed on first run). The page works with it closed: the card slot always shows the
open card and the working line. Top to bottom, fixed:

1. **Header.** "Hardware" (20 px/600), the line "Robot parts Solus knows about, and whether each
   one is connected.", and the page's one permanent button, a ghost "+ Add hardware". The page
   draws its own header; there is no second top bar.
2. **The card slot**, 20 px below.
3. **Done so far**, a fixed 30 px row.
4. **"Robot parts · N"** and the parts list.

The page shows nothing else: no topology, links, channels or bench controls. Without an open
project it draws the header alone, the button disabled.

One chat drives the page: the project's current SOL chat on the Hardware surface
(`useSolChat(projectId, 'hardware')`). The page uses it for the slot and the plug-in notice, and
on this screen the sidebar uses the same surface on the same session. Every turn it starts
(typed in the sidebar, a sidebar chip, the start card, an edit, an answer, a notice, a decision
made in the sidebar's thread, the resume after a card) goes as `action_mode: "do"` with
`force_confirmation: true`, so a gated call always parks a card (the server forces the same for
notices and card resumes). A slot press starts its turn and does not wait for it: SOL answers in
the sidebar, and a turn that fails says so there.

**The SOL sidebar on this screen** (`SolSidebarHost`, `screen === 'hardware'`):

- Tag `HARDWARE`; greeting, chips and placeholder as in `sol-sidebar.md` §6.
- **Cards stay in the slot** (`cardsInSlot`): a parked row that carries a card is not drawn in
  the sidebar's thread. A row with no card (a command, a CAD edit) can never reach the slot, so
  it stays in the thread, where it is decided — also as `"do"` with `force_confirmation`.
- **No running-processes strip.**
- **It always docks**, whatever the window width: an overlay would cover the card's buttons at
  the page's right edge. The page gets the room that is left (§Narrow widths).
- A SOL reply that finishes while the sidebar is closed raises the shell's "SOL replied" toast
  (`sol-page.md` §Session lifetime); with it open, none.

## Three states

| State     | Card slot                                                                | Done so far                            | List                                                                    |
| --------- | ------------------------------------------------------------------------ | -------------------------------------- | ----------------------------------------------------------------------- |
| A1 Start  | the start card "Plug in your hardware" / [Connect a robot computer]      | empty                                  | "No robot parts yet"; the described group when the workspace has any    |
| A2 Midway | SOL's open card (an offer, an approval, a step or a problem), or working | this visit's receipts, joined by " · " | the robot's group and its parts, each with its status                   |
| A3 Done   | SOL's closing offer (for example "Add to workspace graph"), then idle    | every receipt of the visit             | every part Connected under its robot; lone parts under "Not on a robot" |

The cards' words in A2 and A3 are SOL's, written at run time; only the start card, the expired
card, the working line and the idle line are the renderer's own.

**The start card** shows while the list is empty and nothing else fills the slot, and again after
"+ Add hardware" whatever the list holds. Pressing its button sends its sentence to SOL and turns
it off for the rest of the visit (until "+ Add hardware"). A device that was already plugged in
when Solus started needs no press: the first time the page opens in an app session SOL is told
about it (§"The plug-in notice and the toast"), and its card takes the slot before the start card.

**"+ Add hardware"** clears the caller's "Not now" list (`DELETE /hardware/devices/dismissals`
through the typed client), so devices waved off are offered again, and shows the start card. A
clear that fails (a hosted API has no machine to clear) is not shown; the start card still comes.
It also announces to SOL, again, every device that is plugged in and still unclaimed (§"The
plug-in notice and the toast").

## The card and its slot

Built in `features/hardware` (`HwCard`, `CardSlot`, `DoneSoFar`).

- **The slot** is a fixed 132 px `aria-live="polite"` region and is never blank. It shows, in
  order: the caller's open card (`GET …/sol/cards/open`); the working line (pulsing dot, what SOL is
  doing from the `tool_call` frame's `working`, else "Identifying <device>" while a plug-in
  inspection of a device the reader has not dismissed runs, and the seconds elapsed); the local
  start card when the page asks for it; the idle line "Nothing needs you right now. Anything you
  plug in shows up here." in a dashed outline. It reads the open card on mount, on window focus,
  after every decision or answer, when the page asks, and every 5 s while the document is visible.
  The page asks on each SOL stream frame that can open a card (a tool call, a parked card) and
  when a turn starts or ends; text frames are left to the 5 s read (narrower than "every frame":
  one read per token batch would be hundreds of requests a turn). A failed read keeps what is shown.
- **The card** is a grid `3px | 1fr | auto`, radius 6, at least 132 px. Offer: `--sur`, `--acc`
  edge, no kicker. Approval: 10% `--warn` over the page ground (opaque), a `--warn` border all
  round, kicker "APPROVAL · THIS CHANGES THE HARDWARE". Step: `--sw` edge, "YOUR STEP". Problem:
  `--err` edge, "PROBLEM". The title is one line (ellipsis). The body clamps at two lines with a
  "more" toggle that shows all of it and the card's `more`; a `backtick` span is a code chip. A
  card opened with "more" grows over the rows below the slot and never moves them. A `field` is a
  mono label and a 220 px input; the primary is disabled while the field is empty. Buttons sit on
  the right: the primary, and the secondary as a ghost when there is one. A status line and a
  progress bar are drawn only when the page passes them (the Card contract carries none).
- **The start card** is local, never a parked call: "Plug in your hardware", one button, "Connect
  a robot computer", which sends that sentence to SOL. Pressed while SOL is still replying, the
  sentence waits for that turn and goes after it (as does "Ask again" on an expired card). The start card leaves on the press, so it cannot be pressed
  twice while that turn runs, and comes back only when the sentence never reached SOL (the turn
  failed, or the send itself threw).
- **A press.** On a gated card the primary approves and the secondary rejects through the decide
  route (a decision and nothing else). On a question card (`ask_user`) they answer 0 or 1 through
  `MessageCreate.answer`, with the field's text when the person changed it; the decide route is
  never called. The slot hands the page the whole open card with an answer, so it is posted to the
  conversation the question was asked in (the only one the server takes it in). The answer turn
  may wait behind a live one, and until it lands the server still lists the question as open: the
  answered question is kept out of the slot meanwhile, so it cannot be answered twice, and comes
  back only when the answer never reached SOL. Its `receipt` joins "Done so far" once the answer
  turn was admitted, not on the press. **An edit answers its
  card** (contract §Cards 5): the primary of a gated card whose field was edited never calls the
  decide route. It posts one `MessageCreate.answer {question_id: <the card's confirmation id>,
choice: 0, text: <the new value>}` in that card's conversation; the server expires the card
  without deciding it (so an edited device offer is never the "Not now" that dismisses the
  device) and writes the turn itself, `<field label>: "<new value>"` with the value JSON-quoted
  as data: the field was prefilled by SOL, so what the person did not retype never reads as
  their own words. The card is treated as an answered question: kept out of the slot until its
  turn has gone, back when the turn failed. Nothing was approved, so the button keeps its own
  label (never a success word), nothing joins "Done so far" and nothing is resumed: SOL
  continues from the answer turn. In the SOL thread the turn is the receipt line
  `Edited: <field label> — <new value>`, live and reloaded. "Not now" on an edited card is still
  only a rejection, and an untouched field an approval. The field's whole value is its tooltip,
  and past 24 characters its length is written beside it ("74 characters"). After a
  decision on a
  card with `resumes`, SOL is continued in that card's conversation, including after a refusal
  (expired, stale, already decided). An approval that ran adds the card's `receipt` to "Done so
  far". A decision the server refuses (expired, stale, already decided, or the tool failed) never
  reads a success word and files no receipt: the button keeps its own label, the server's own
  words show on the card's error line for 2.4 s, and then the card leaves. A decision that never
  reached the server keeps the card and says "That did not go through. Try again." Every decision
  made here is told to the chat (`cardDecided`), so the card's row leaves the thread too — on the
  SOL page it is no longer a live card, and a restored "Awaiting your approval" line is not left
  with no card under it.
- **Expiry.** A card that passes `expires_at` while it is on show becomes the Problem "This card
  expired" / "SOL asked something you did not answer in time." with "Ask again", which sends the
  fixed sentence "Please ask me again about the card that expired." (never the card's own title)
  to the conversation the expired card was asked in. It does not use up the start card: on an
  empty list the start card is offered again afterwards. It stays until it is answered or another
  card is open.
- **Motion.** On the press the other button is disabled and the pressed one keeps its own label
  until the press went through (the decision came back, the turn was handed over); only then does
  it read its result word for 600 ms ("Approved" on an approval, "Added" when the label starts
  with "Add", else "Done"; a secondary keeps its label). A success word is never shown for a
  decision the server may still refuse. The card leaves in 160 ms (fades, rises 6 px); the next arrives in 200 ms
  (fades in, drops 4 px). Focus moves only to the card that follows the person's own press, once,
  and only while their focus is on the page itself or still in the slot: a question card's primary
  takes it, and a gated card is focused itself (one Tab from its buttons), never the button that
  decides it. A card that arrives on its own, and the start card, never take the focus, so a stray
  Space or Enter cannot approve anything (CLAUDE.md §7; narrower than the design's motion step 4).
  With reduced motion both are a 120 ms fade.
- **Arrival guard.** A card read from the server takes no press for its first 450 ms on show,
  whatever it replaced (the start card, the expired card, another card, the card just answered): a
  click aimed at the button that was there a moment ago never decides or answers a card the person
  has not read (CLAUDE.md §7). The arrival is stamped before the card is painted (a layout
  effect), so there is no moment in which it can be pressed unguarded. The local start and
  expired cards are not guarded.
- **Done so far** is a fixed 30 px mono row: "Done so far: " and this visit's receipts joined by
  " · ", or empty (the row stays, so nothing below moves).

### The parts list (`features/hardware/PartsList.tsx`)

"Robot parts · N" (13 px/600; N counts parts), then the column headers (mono 10 px uppercase:
Part, What it is, Robot, In workspace graph, Status) over one grid (1.25fr 1.2fr .9fr 1.05fr
.9fr, gap 12) in a bordered `--sur` container. The component reads through the typed client, on
mount, after its own Add, and when its `refreshKey` changes (the page changes it after a decided
card and when a SOL turn starts or ends): the manual robots
(`GET /entities?type=physical_robot`), every part-like entity with its robot
(`GET /hardware/parts?ownership=all`, all pages up to 1000 rows), the machine nodes
(`GET /entities?type=machine`; the device memory reaches a machine's owner alone) and
`GET /hardware/expected`. The plugged-in device rows come from the shell's one device store, so
a status follows a plug or an unplug with no read: the store also keeps each remembered row
(one carrying `last_seen`, so the machine's owner alone) that left while it watched, stamped
with the moment it left, and that is newer than the memory as last read — a part unplugged
with the app open reads "Last seen just now", never the older snapshot and never "Not
connected". A project switch or a sign-out drops them; the next read has the machine's own. Everything on show is what the reader may see
(`docs/api/hardware.md` §1a); every name is someone's own text and prints as text.

- **Groups.** One `--sur2` row per robot, "<robot> · N parts", oldest robot first, its parts
  under it oldest first; then "Not on a robot · N" for manual parts no robot holds. A
  connector's part no robot holds is workspace design and is not listed. A robot with no parts
  (a plain connection) says its own status on its group row. A row that a later read brings
  fades in with `local-row-in` (180 ms, off under reduced motion) at the end of its group; the
  first read animates nothing and no row that was on show moves.
- **In workspace graph.** "in graph", or "not yet" with a button: an outlined "Add robot" on a
  robot's row, a text "Add" on a part no robot holds. Both are the person's own action:
  `PUT /hardware/entities/{id}/graph {in_graph: true}`, no card, then the list reads again. A
  robot's part has no button of its own (the route refuses it: it moves with its robot; narrower
  than the design, which draws "Add" on every part). A refusal prints under the table (never in
  it: a rowgroup holds rows only) in the server's own words (`hardwareErrorText`), so it names
  only hardware the reader may see; it goes when its row does.
- **Status** is a dot and a word, derived on every render and never stored (`partStatus.ts`):
  Identifying (pulsing `--acc`: its device row is `inspecting` and the reader has not said "Not
  now"); Connected (filled `--ok`: the robot's connection is `connected`, or its device is
  plugged in); Unknown, streaming (filled `--ok`: the same, for a robot with no parts); Last seen
  <n> minutes/hours/days ago, or "just now" (filled `--mut`: the device is not plugged in and
  the machine remembers it, or the store saw it leave); Not connected (hollow `--err` ring: neither); Not seen yet (hollow `--mut` ring:
  described rows only). A part's device is the one its `device_ref` names, else one bound to it,
  else (with no `device_ref`) one bound to its robot. While any row reads "Last seen", the
  list draws again each minute so the words advance on a page nobody touches; the clock rests
  while the window is hidden and the words are brought up to date the moment it shows again.
- **Empty.** The headers and a 44 px dashed box, "No robot parts yet".
- **Described in your workspace, not seen yet · N.** A collapsed full-width button under the
  list (`aria-expanded`, a chevron, and on the right the mono "from <sources>"), hidden when N is
  0; N is the rows plus `more`. It expands into rows of the same grid: name, what it is, the
  robot's name or "none yet", "described only", "Not seen yet", then "and N more" when rows were
  left out.
- **Narrow widths** (CSS only: container queries on the page root, `.hw-page`, so they measure
  the room beside the sidebar, not the window). Page under 1100 px: the Robot column goes and
  the robot is a second line of the Part cell; under 900 px the headers go and a row is two
  lines (name + what it is / graph + status).

## Entry points

- **The rail**: the Hardware item (`Icons.hardware`, tooltip and accessible name "Hardware")
  between Workspace and Live Bench, icon-only like the others.
- **Workspace › Add › Hardware**: a row that closes the Add modal and opens this page
  (`docs/wireflows/workspace.md` §Add).
- **Live Bench**: "Add hardware" in its add menu and the device banner both open this page.
- **The plug-in toast** (below), the menu bar and the command palette.

## The plug-in notice and the toast

The shell subscribes once to the project's device rows (`useDeviceStream`: one `GET /detected`
seed, then the `hardware.devices_changed` frames) and keeps them in `deviceStore`; the page reads
from there. A device **arrives** when its row becomes an offer: it has a device ref, nothing the
reader may see binds it (`bound_to` null), the reader has not said "Not now" (`dismissed`), and
its plug-in inspection has settled (`state` is `inspected`, `busy` or `unknown`; `inspecting`
waits). What was plugged in before Solus first read the rows raises no toast, but it is an offer
like any other.

**Each offer is announced to SOL once per app session**, however the page comes to it: it was
plugged in before Solus started, the toast stood in for it while the page was closed, or it
arrived with the page open. The renderer keeps the set of announced offers for its lifetime
(`announced` in `deviceStore`); a sign-out or a project switch empties it, and a device leaves it
when it stops being an offer, so one that is unplugged and plugged in again is a new arrival. A
device the person waved off with "Not now" is not an offer and is never announced.

- **While the page is open** (`usePlugInNotice`) an offer not yet announced this session is
  announced to SOL with `MessageCreate.notice {kind: "device", device_ref}`, 2 s after the page
  first sees it (a port that flaps inside the 2 s is one arrival; a device that leaves, is bound
  or is waved off inside them is not announced). A notice waits behind a live SOL turn and is sent when it ends, never
  cutting it off. The server writes the turn's words and SOL answers with a card in the slot.
  In the SOL thread the notice is a quiet Solus system line, never the person's bubble
  (`docs/wireflows/sol-page.md` "Cards in the thread"); an answered question card is a receipt
  line there, "Answered: <label>". A
  409 `notice_debounced` and a 422 (the device has gone) leave nothing in the thread; any other
  failure is not retried. A device that leaves and is plugged in again is a new arrival.
- **While the page is closed** the shell raises one toast instead: "Something was plugged in" /
  "Open Hardware to see it." with the action "Open Hardware". No notice is sent then, but the
  shell remembers which devices the toast was about (`deviceStore.unannounced`; a device leaves
  that list when it stops being an offer).
- **Opening the page** for the first time in a session announces every current offer, through
  the same 2 s wait and the same queue: a device plugged in before Solus started gets its card
  without a replug, and the toast leads to a card. A later open announces only what is new or
  remembered from a toast: a device already announced does not start a SOL turn each time the
  page opens. A notice still inside its 2 s when the page closes (or when React StrictMode
  remounts it) is remembered as owed, and the next open sends it, once.
- **"+ Add hardware"** clears the "Not now" list, shows the start card and announces every device
  that is an offer at that moment again, although it was announced before, after the same 2 s.
  The server's own 2 s debounce bounds repeated presses.

## Narrow widths

The page's breakpoints measure the page (`.hw-page`), which is the window less the rail and,
when it is open, the sidebar (360 px by default, 320 to 480 by drag). The sidebar never overlays
this page.

- Page 1100 px and wider: as drawn.
- 900 to 1099: the list drops the Robot column into the Part cell as a second line.
- Under 900: the list's headers go and a row is two lines (name + what it is / graph + status).

## What else still renders hardware

- **The robot sidebar** (`docs/wireflows/workspace.md` §Physical Robot): the parts the robot
  contains, its connection line, pending link suggestions with Accept and Reject, Rename and the
  two-step Delete robot (its parts are retained, and appear on this page under "Not on a robot").
  It lists no unassigned parts and has no Attach: lone parts live on this page, and attaching one
  to a robot is SOL's (`hardware.add_parts`).
- **The Hardware CONFIG editor and its private sources panel**, below.
- **The robot topology graph** (robot → brain → bus → device → part) in the Workspace; a board
  that is both an upstream device and a downstream brain appears once, and missing facts say
  unknown.

### Configuration and local source references

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
CONFIG deletion names its binding effects and cannot trigger recreation through a later GET.

### Registered widget roots (SOLUSDEV-262 W5)

Project overview lifts persisted Live Bench and installed widget registrations into top-level
nodes, preserving graph UUIDs and underlying contains relations. No installed registration means
no fabricated widget node. Cards show installation/blocked state and open the existing supported
page view; disabled or blocked widgets explain their state and cannot open. Live Bench opens its
existing tab. Installation/removal refreshes this projection from current project graph data.
For older projects whose persisted registration layer is absent, Workspace initializes it through
the existing member-authorized reconcile action, then rereads the graph. Failed initialization
shows a bounded retry control; a viewer is told that a project member must initialize widgets.
