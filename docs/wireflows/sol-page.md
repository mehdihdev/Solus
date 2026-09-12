# Wireflow — SOL Page (SOLUSDEV-233)

The full-page SOL surface (`MainScreen 'sol'`). Three columns inside the shell
(below the topbar); the orb popover keeps its own compact layout and shares the
chat surface (`OrbChat`) and stream protocol unchanged.

```
| CHATS (224px) | SOL header + transcript + composer (flex) | CONTEXT/USAGE (288px) |
```

## Left — CHATS sidebar

- Header: `CHATS` + a bordered `+` button ("New chat").
- Rows: conversation title (seeded from the first message, 60-char cap;
  "New chat" fallback) over a relative timestamp. Newest first, from
  `GET /sol/conversations`. Active row is highlighted (`aria-current`).
- Click a row → the transcript reloads that conversation (any live turn is
  cancelled first). `+` → clears the active conversation; the next send
  creates a fresh one server-side.
- **Right-click a row** → context menu: **Rename** (name dialog →
  `PATCH /sol/conversations/{id}`) and **Delete** (confirm dialog →
  soft-delete; the chat's `~/.solus` cache file is removed; deleting the open
  chat clears the transcript to a fresh one). The list refreshes after either.
- States: spinner on first empty load; "No chats yet…" when empty;
  "Chats unavailable — offline." on failure; "Open a project…" without one.

## Center — chat column

- Header: SOL orb (pulses while streaming), "SOL", then a mono subtitle:
  the project name, plus `· GROUNDED IN N CONNECTIONS` **only when N is the
  project's real connected-source count from the server** (SOLUSDEV-152
  charter: never a fabricated number; no server truth → no line).
- The header has no Guide/Expert selector. The universal tone preference remains
  in Settings (ADR-016); the stored server mode still governs the next turn.
- Transcript: user bubbles right, assistant markdown left, mono tool lines in
  the backend's persisted format (`tool → outcome`), citations region,
  confirmation cards (unchanged CTR-03 flow). Messages enter with a short
  fade-rise.
- Composer: input + Guide/Do action-mode toggle + Send (unchanged), routing
  line underneath — ALWAYS present (SOLUSDEV-233): with a classification it
  reads `tier · type · model` (click to override); with none (empty input /
  endpoint hiccup) it shows the honest idle line "auto routing · sizes each
  message to the cheapest capable model" in the same spot — no layout shift,
  never a fabricated tier.
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
  The action-mode toggle **defaults to Do** (SOLUSDEV-168) and sticks for the
  panel instance. Guide refuses exactly the tools the CTR-03 gate already parks,
  so a Guide default only replaced an approval card with a "switch to Do mode"
  refusal; every mutation still parks for explicit approval. The API default
  (`MessageCreate.action_mode`) stays `guide` for non-UI callers.
- Turn rejections are named, not generic: 402 → "You're out of SOL credits —
  top up to keep going." (and the top-up card lights); 429 → "Too many SOL
  turns right now — give it a few seconds."

## Right — CONTEXT IN USE

- **Custom instruction** card: the user's standing preference note
  (Add/Edit → textarea, 500-char cap, Save/Cancel; failed save keeps the
  editor open with an error). Stored per user; enters the prompt only as a
  fenced data block (§7).
- **Context files** card: the `document` sections of the last turn's
  `context_used` frame, rendered as mono file labels (citation refs).
- **From the graph** card: the `graph` sections as pill chips; a muted
  footnote counts telemetry/error sections and notes budget truncation.
- Empty state before the first turn: "Send a message and SOL will show what
  it grounded the answer in…". Labels only — section text never reaches the
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

## Right — SOL USAGE

- "This cycle `used / allowance`" in credits (ADR-018 — credit-denominated,
  never raw tokens) from `GET /users/me/usage`, with a progress bar (accent →
  warn ≥70% → err ≥90%; fill width eases). Balance line underneath.
- **Top-up card** ("Running low on credits" / "Out of credits" after a 402):
  the ADR-024 packs from `GET /billing/packs` as `$N` buttons through the same
  Stripe checkout flow as the Billing screen. Shown when the balance is low
  (≤100 credits, provisional) or a turn was rejected with 402.

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
