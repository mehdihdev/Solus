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
- States: spinner on first empty load; "No chats yet…" when empty;
  "Chats unavailable — offline." on failure; "Open a project…" without one.

## Center — chat column

- Header: SOL orb (pulses while streaming), "SOL", then a mono subtitle:
  the project name, plus `· GROUNDED IN N CONNECTIONS` **only when N is the
  project's real connected-source count from the server** (SOLUSDEV-152
  charter: never a fabricated number; no server truth → no line).
- Right of header: the universal Guide/Expert mode toggle (ADR-016). It
  persists to `PATCH /users/me/settings` with optimistic revert — the server's
  stored mode is what the next turn's prompt reads.
- Transcript: user bubbles right, assistant markdown left, mono tool lines in
  the backend's persisted format (`tool → outcome`), citations region,
  confirmation cards (unchanged CTR-03 flow). Messages enter with a short
  fade-rise.
- Composer: input + Guide/Do action-mode toggle + Send (unchanged), classify
  indicator underneath.
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
meter fill eases to its new width. Transform/opacity only, tokens only, all
disabled under `prefers-reduced-motion`, CSS-only (the orb perf ratchet forbids
JS timers in orb-adjacent files).

## Failure / edge paths

- No project open: full-surface prompt to open one; composer not rendered.
- History fetch fails: `SOL HISTORY UNAVAILABLE — OFFLINE`, composer stays.
- Usage fetch fails / offline: "Usage unavailable offline."; no fabricated
  numbers anywhere on the page.
- Signed out (dev bypass): panels degrade to their offline states.
