# Wireflow — SOL Page (SOLUSDEV-233)

The full-page SOL surface (`MainScreen 'sol'`). Three columns inside the shell
(below the topbar), per the design template (Claude Design
`templates/workspace/Workspace.dc.html`, 2026-10-24); the SOL window keeps its own
compact layout and shares the chat surface (`SolChat`, `layout="panel"`) and stream
protocol unchanged.

```
| CHATS (250px) | 44px header + thread (full width) + composer | CONTEXT (320px) |
```

## Left — CHATS sidebar

- A **New chat** card at the top with the platform hint (`⌘N` / `Ctrl N`); the chord
  really starts a new chat while the page is mounted.
- Rows grouped by last activity (`updated_at`, computed on the client):
  `TODAY` / `THIS WEEK` / `EARLIER`, newest first within a group, from
  `GET /sol/conversations`. A row is the conversation title (seeded from the first
  message, 60-char cap; "New chat" fallback) over a relative time — never a message
  count, which the API does not carry. Active row is highlighted (`aria-current`).
- Click a row → the transcript reloads that conversation (any live turn is
  cancelled first). New chat → clears the active conversation; the next send
  creates a fresh one server-side.
- The **SOL USAGE** card sits at the bottom of this column (see below).
- **Right-click a row** → context menu: **Rename** (name dialog →
  `PATCH /sol/conversations/{id}`) and **Delete** (confirm dialog →
  soft-delete; the chat's `~/.solus` cache file is removed; deleting the open
  chat clears the transcript to a fresh one). The list refreshes after either.
- States: spinner on first empty load; "No chats yet…" when empty;
  "Chats unavailable — offline." on failure; "Open a project…" without one.

## Center — chat column

- Header (44px): the active chat's title (`New chat` before the first send), a mono
  `N NODES IN CONTEXT` — the chat's pinned nodes, the one honest count on the page
  (the former `GROUNDED IN N CONNECTIONS` line is retired with its extra fetch) — and
  **Open SOL window** under Electron.
- The header has no Guide/Expert selector. The universal tone preference remains
  in Settings (ADR-016); the stored server mode still governs the next turn.
- Transcript (full column width between the two side panels): user bubbles right (`--sur2`); SOL replies lead
  with the Solus mark in a gutter and a mono `SOL` label, then markdown, mono tool
  lines in the backend's persisted format (`tool → outcome`), confirmation cards
  (unchanged CTR-03 flow) and the citation chips — the raw `[connector:ref]` token
  in a pill, a domain dot only when the connector maps to one of the four domains,
  and an `[entity:id]` chip focuses that node in the Workspace. Messages enter with
  a short fade-rise.
- Composer: a bordered box with a **+** attach button (menu: **Upload file or
  image** → the project's `.solus/documentation`; **Add node from graph** →
  Workspace), an autosizing textarea (`Ask SOL about this project…`; Enter sends,
  Shift+Enter newline; Ctrl/Cmd+Enter stays with the command cards, SOLUSDEV-317)
  and the accent **Send**; the box's footer row keeps the Guide/Build action-mode
  badge, **Think harder**, **Confirm every change** and the routing line — ALWAYS
  present (SOLUSDEV-233): with a classification it reads `tier · type · model`
  (click to override); with none (empty input / endpoint hiccup) it shows the
  honest idle line "auto routing · sizes each message to the cheapest capable model"
  in the same spot — no layout shift, never a fabricated tier. Every send carries
  the typed `@`-mentions first, then the chat's pinned nodes, deduped and capped at 8.
  Typing `@` in the input opens a **graph-entity picker** (SOLUSDEV-168): a
  listbox above the composer, debounced ~400ms against
  `GET /projects/{id}/entities?q=&limit=8`, matching names and connected code paths,
  arrow keys + Enter to pick, Escape to
  dismiss. Picking splices `@Name` into the text and carries the entity **id**
  alongside the message, so SOL grounds on the node the user meant instead of
  whatever similarity search ranked first. A mention deleted from the text is not
  sent. Mentions arrive back as `graph` sections in `context_used`, so they render
  in "From the graph" with no extra UI. A failed search shows no list and never
  blocks Send. Code results show their stored path to distinguish duplicate filenames.
  Changing projects immediately invalidates old results and selected mentions.
  The action-mode toggle **defaults to Build** (wire value `do`, SOLUSDEV-168) and sticks for the
  panel instance. Guide refuses exactly the tools the CTR-03 gate already parks,
  so a Guide default only replaced an approval card with a "switch to Build mode"
  refusal; every mutation still parks for explicit approval. The API default
  (`MessageCreate.action_mode`) stays `guide` for non-UI callers.
- Turn rejections are named, not generic: 402 → "You're out of SOL credits —
  top up to keep going." (and the top-up card lights); 429 → "Too many SOL
  turns right now — give it a few seconds."

SOLUSDEV-262 demo review: the composer includes **Confirm every change**. This
per-conversation preference sends the existing `force_confirmation` flag and
defaults off. It persists across pane navigation, resets for a new conversation
or account, and is disabled while a turn streams because that turn already
captured its policy. It does not approve any pending action.

SOLUSDEV-261 approval-card polish preserves the CTR-03 flow: a clear review heading,
always-visible action summary, responsive labeled Before/After values with exact
case and whitespace, and expandable tool/approval identifiers. Missing and empty
values are distinct. Approve/Reject, busy states, retry and terminal refusal behavior
are unchanged. User-facing action-mode wording is Guide/Build; internal wire values
remain `guide`/`do` for compatibility.

SOLUSDEV-261 restoration: reopening a chat reads its persisted active approval
cards alongside history and shows their original identifiers and full previews
in an "Awaiting your approval" transcript entry. This is current server state;
historical waiting prose is not approval status. Expired or decided actions are
not restored as actionable cards. The local cache never supplies approvals.
After a successful decision, the entry reports that decision and no longer says
it is waiting when its final card is removed. Identical pending proposals in
later turns reuse the original card; typing acceptance does not approve it.

## Right — context column (320px)

- **CUSTOM INSTRUCTIONS**: the user's standing preference note (Add/Edit → textarea,
  500-char cap, Save/Cancel; failed save keeps the editor open with an error). It is
  the per-ACCOUNT setting and the card says "Applies to every chat on this account" —
  there is no per-chat instruction. Enters the prompt only as a fenced data block (§7).
- **FILES & IMAGES**: the project's `.solus` file entries (`kind: artifact`, every
  section) as ext-labelled tiles; **+ Upload** = `uploadArtifact` + `POST
/solus/documentation/entries` through the existing import handler. SOL reads
  `.solus` into context by file name (the bytes never reach the model), and the empty
  copy says so.
- **NODES IN CONTEXT**: the chat's pinned nodes (client-side, `localStorage
solus_sol_pinned_v1`, keyed by project and conversation; a fresh chat's pins follow
  the conversation the first send creates; cleared when the account ends). Rows show
  the domain dot, name and type with ✕ to unpin; **From graph →** opens the Workspace,
  whose panel's **Ask SOL** pins the selected node and seeds the composer `About
<name>: `. Above 8 pins a note says only the first 8 ride along.
- **ARTIFACTS**: what SOL produced in this chat — this session only (reloaded turns
  carry no artifact bytes). Right-click: **Save to .solus folder** (the same
  idempotent `fileArtifact` as the transcript card, into Documentation; a filed one
  shows the green `.solus` pill and the item is disabled with `Filed to …`), **Show in
  chat** (scrolls to the card; there is no honest "open" for a bearer-protected blob),
  **Copy contents** (text media only).
- **CONTEXT IN USE**: the last turn's manifest, unchanged — **Context files** (the
  `document` sections as mono file labels) and **From the graph** (the `graph`
  sections as pill chips; a muted footnote counts telemetry/error sections and notes
  budget truncation). Empty state before the first turn: "Send a message and SOL will
  show what it grounded the answer in…". Labels only — section text never reaches the
  client.

## Session lifetime (SOLUSDEV-233)

- A chat session OUTLIVES the page: leaving the SOL screen mid-response keeps
  the turn streaming in the background; returning re-attaches to the live (or
  finished) transcript. Streams are torn down only on chat switches and
  sign-out — never by navigation.
- A reply that finishes while the user is elsewhere raises the shell toast
  ("SOL replied" / "SOL turn failed", author-safe) with a **View** action
  jumping to the SOL page when the workspace is still on that project.
- Each chat's settled turns mirror to `~/.solus/projects/<id>/sol/` (ADR-034
  Layer 1 cache): returning to a chat paints instantly from the cache, the
  server load then wins, and a cached chat stays readable when the API is
  down. The server remains the source of truth.

## SOL USAGE (bottom of the CHATS column)

- "This cycle `used / allowance`" in credits (ADR-018 — credit-denominated,
  never raw tokens) from `GET /users/me/usage`, with a 3px progress bar (accent →
  warn ≥70% → err ≥90%; fill width eases). Balance line underneath. An accent **+**
  (`Add credits`) beside the meter opens the packs on demand.
- **Top-up card** ("Running low on credits" / "Out of credits" after a 402; "Add
  credits" when opened by the +): the ADR-024 packs from `GET /billing/packs` as
  `$N` buttons through the same Stripe checkout flow as the Billing screen. Shown
  when the balance is low (≤100 credits, provisional), a turn was rejected with 402,
  or the + was pressed.

## Motion

Messages, sidebar rows, and panel cards enter with a 0.18–0.22s fade-rise; the
meter fill eases to its new width. The same fade-rise now plays on EVERY
workspace screen switch (app-wide, keyed per navigation in the shell). Transform/opacity only, tokens only, all
disabled under `prefers-reduced-motion`, CSS-only (the orb perf ratchet forbids
JS timers in orb-adjacent files).

## Failure / edge paths

- No project open: full-surface prompt to open one; composer not rendered.
- History fetch fails: `SOL HISTORY UNAVAILABLE — OFFLINE`, composer stays.
- Usage fetch fails / offline: "Usage unavailable offline."; no fabricated
  numbers anywhere on the page.
- Signed out (dev bypass): panels degrade to their offline states.

## Compact intervention cards and autonomous Build — SOLUSDEV-261

Build runs routine edits through the centrally validated execution policy. Guide
remains read-only. Only actions requiring intervention show a compact card: keep
summary, status and Approve/Reject visible; show the number of proposed changes.
Put the complete verbatim preview into an expandable, scroll-bounded region
(collapsed for lengthy previews; short previews may stay open). Never discard
rows, multiline values or identity/fingerprint details. Ambiguous intent gets a
short question before acting. The renderer does not grant or classify permissions.

### Command output in compact confirmations

While an approved local code run/test executes, keep the card compact with its
existing execution indicator and show a bounded, keyboard-scrollable plain-text
output region. Poll the owner-scoped output endpoint only during execution;
append incremental stdout/stderr, label truncation, and retain final completion
or failure state. Never interpret terminal text as HTML or instructions. No modal
or second approval screen is introduced.

## Command execution — SOLUSDEV-317

Governing spec: `docs/api/code-command-execution.md`. Applies identically to the SOL window.

- **Command card.** For `code.exec`, `code.process_start`, `code.run`, `code.test`,
  `code.install`, `code.create_environment` and `code.profile_capture`, the compact card's
  header shows the program basename and one badge per value of the `risk` row (`network`,
  `install`, `destructive`, `hardware`, `remote`, `runs_shell`, `project_scripts`), plus a `sandboxed` badge
  read from the `sandbox` row. The badges are presentation only. The renderer does not
  classify anything; the verbatim rows (program, command, cwd, environment, profile,
  sandbox, risk, fingerprint) are unchanged in the expandable preview.
- **Cmd/Ctrl+Enter approves.** While focus is inside a SOL chat surface (page or window,
  composer included), Cmd+Enter (macOS) / Ctrl+Enter (Linux) approves the newest pending
  **command** card in that surface. The shortcut is never registered globally.
  - A card is approvable by shortcut only after it has been rendered and the newest command card
    for at least 700 ms. A newer card restarts that clock, so an auto-resumed card cannot be
    approved by a press meant for the previous one.
  - Key auto-repeat is ignored. After a shortcut approval, the next one needs a fresh keydown
    (any keyup, or the window losing focus).
  - Ignored when the card is busy or permanently failed, during IME composition, with Alt/Shift
    held, or when no command card is pending. With a command card pending, a blocked press is
    consumed and never submits the composer. With none pending, Cmd/Ctrl+Enter behaves as before.
  - The Approve button shows `⌘↵` / `Ctrl↵` (hidden from screen readers; `aria-keyshortcuts`
    set). Non-command cards still need a click.
- **Command preview is open.** Command cards render their verbatim preview expanded (bounded,
  scrollable) rather than collapsed, so the resolved program, full argv, cwd, profile, sandbox and
  risk rows are on screen before Approve. The Cmd/Ctrl+Enter arming clock starts only once the
  preview region has been in view (IntersectionObserver) for 700 ms.
- **Composer drafts win.** Cmd/Ctrl+Enter pressed in the composer while it holds a non-empty draft
  never approves a card: the key is consumed and nothing happens (the user is typing, possibly "no,
  don't run that"). With an empty composer the shortcut approves as above.
- **Output stays.** The output region is shown while an approved command runs, and the final
  output stays under the resulting "Approval recorded" message with the exit status
  (`exited 0`, `exited 2`, `timed out`, `refused: …`) until the conversation is closed.
- **SOL continues.** After an approved command card finishes, the client starts a resume turn
  (`resume_confirmation_id`) without adding a user bubble. SOL reads the result and either
  proposes the next step (which is another card) or answers. A `resume_limit` answer shows
  "SOL paused — reply to continue". Rejecting a card does not resume.
- **Running processes strip.** Above the composer, when this machine has processes started by
  SOL for the open project: one row per process (name or program, state, elapsed time) with
  **Output** (expands a bounded, keyboard-scrollable plain-text region, polled while open) and
  **Stop** (a direct user action, no card). The strip polls every 2 s while any process is
  running and every 15 s otherwise, and is hidden when there are no processes or the bridge
  is offline.
- **Refusals.** A denied command (shell, inline code, sudo) never produces a card. SOL gets
  the refusal and proposes a direct command instead. A missing sandbox shows up as the card's
  refusal text, `sandbox unavailable: …`.

### SOLUSDEV-317 follow-up — auto-run and output blocks (2026-10-19)

Build mode runs no-risk commands without a card (`docs/api/code-command-execution.md` §10).
They appear as a compact command row (program, status, `auto`) with a code-block output
region. Risky commands, workspace programs and shell scripts still show the card. Command output
and SOL's markdown code blocks share one code-block surface, and each block has a top-right
Copy button. The truncation label appears only when output was actually truncated.
