# Cowork QA — SOL's thinking, visible

Ticket: **SOLUSDEV-326** · Branch: `SOLUSDEV-326-sol-visible-thinking`

This file is self-sufficient: a running app and this document, nothing else.

---

## 0. What changed, in one paragraph

While SOL works on a question, the reply now opens with a **Thinking…** block. It streams SOL's
thought summary, plus a line for each tool SOL runs ("Get entity", "Read netlist", …). When the
turn finishes, the block folds into one line such as **Thought for 12s · 3 steps** (thinking time
only, not the time tools took). Clicking
that line opens it again. In **Guide** mode it stays open after the answer; in **Expert** mode it
folds. The old collapsed "N tool steps" line is gone; its contents live inside this block now.
The thought is a _summary_ the model provider writes, like the one Claude and ChatGPT show. It is
not the raw internal reasoning, which no provider exposes.

### Known limits (not bugs)

- [ ] **Trivial questions on the Claude route show no thought**, only steps or nothing. By design:
      Claude Haiku (the trivial code route) is excluded to avoid adding cost. A trivial
      _general_ question routes to OpenAI and does show a thought.
- [ ] **The first-tier answer from project facts** (answer badge "from your project's facts") makes
      no model call, so it shows no Thinking block.
- [ ] **How much thought appears is up to the model.** A simple question may show only a sentence
      or two, or none. One run with no thought is not a failure. Keep pushing with the multi-step
      questions in §2.
- [ ] **A reloaded turn shows its thought, but not its steps inside the block.** Steps of past
      turns appear as the separate grey tool rows, as before.

---

## 1. Setup

- [ ] The desktop app is running against an API on this branch (`pnpm dev:all`). The API has
      working **OpenAI** and **Anthropic** keys (SOL routes between them).
- [ ] You are signed in, with credits available (Billing → Credits shows a non-zero balance).
- [ ] A project is open that has at least one connected source with some graph content (a GitHub
      repo or a KiCad project), so SOL has something to look up.
- [ ] Settings → SOL mode is known: start in **Expert**.

---

## 2. Main flows

### 2.1 Watching SOL think (Expert)

1. Open SOL (the SOL page, or the SOL window / pill).
2. Ask a question that needs looking things up, e.g. _"Which parts on my board talk over I2C,
   and could any of their addresses clash?"_
   - [ ] Expected: the reply shows a quiet `thinking…` note at first.
   - [ ] Expected: within a few seconds a **Thinking…** label appears (shimmering), and below it
         the thought text grows sentence by sentence, not word by word.
3. Keep watching while SOL uses tools.
   - [ ] Expected: each tool appears as a line with a pulsing dot while running, then ✓ (or ✕ on
         failure). It shows a readable name ("Get entity") with a grey mono line under it, e.g.
         `graph.get_entity → ok`, plus any arguments.
   - [ ] Expected: thought written after a tool appears **below** that tool's line, not above it.
4. Wait for the answer.
   - [ ] Expected: the block stays open (label **Thinking…**) while SOL is still working, even if
         some reply text appears before a tool runs.
   - [ ] Expected: when the reply is complete, the block folds to one line:
         `Thought for Ns · N steps` with a ▸ arrow. The answer reads below it.
5. Click the folded line.
   - [ ] Expected: it opens (▾) and shows the same thought and steps, in the same order. Click
         again: it folds.

### 2.2 Guide mode keeps it open

1. Settings → SOL mode → **Guide**.
2. Ask another multi-step question.
   - [ ] Expected: same live behaviour as 2.1.
   - [ ] Expected: after the answer, the block **stays open**, labelled `Thought for …`. Clicking
         folds it.

### 2.3 After a reload

1. With a turn from 2.1 on screen, reload the app window (or switch to another conversation and
   back).
   - [ ] Expected: that assistant reply still shows `Thought for Ns` (folded in Expert). Opening
         it shows the thought text. The tool steps of that turn appear as the separate grey
         tool rows above the reply.
2. Open a conversation from **before** this change.
   - [ ] Expected: old replies show no Thinking block and no error.

### 2.4 A turn with steps but no thought

1. Ask something trivial that still needs a lookup, e.g. _"what's the name of entity <id>?"_,
   with a known id from the graph.
   - [ ] Expected: either a thought plus steps, or, if the model showed none, a folded line that
         reads just `1 step` (or `N steps`). Opening it lists the steps.

### 2.5 Build mode with an approval card

1. Switch the composer to **Build** and ask for a change that needs approval (e.g. an Onshape
   variable or a file edit, if connected).
   - [ ] Expected: the Thinking block sits at the top of the reply. The approval card and
         "SOL's reasoning" block (if any) appear below it, as before. Approving or rejecting
         still works.

---

## 3. Edge cases and failure paths

- [ ] **Stop mid-thought**: while **Thinking…** is streaming, press Stop / cancel the turn.
      Expected: the block stops growing. Nothing crashes. After reload, whatever thought was
      captured before the stop shows on the reply.
- [ ] **Out of credits mid-turn**: with a nearly empty balance, ask a long question. Expected: the
      usual credits message. The Thinking block shows whatever arrived, with no error inside it.
- [ ] **Offline**: disconnect the network, ask SOL something. Expected: the usual "SOL is
      unreachable" text. No Thinking block appears.
- [ ] **Markup in thought**: ask _"Explain what `<img src=x onerror=alert(1)>` would do in HTML"_.
      Expected: if SOL's thought quotes it, the literal characters show as text. No image, no
      alert, no formatting.
- [ ] **Secrets**: in a test project whose synced repo has a config file holding a _fake_
      provider-style key (the `sk-ant-api03-` prefix followed by 40 or more letters; make one
      up, never use a real key), ask SOL to _"read that config and tell me what credentials it
      uses"_. Expected: the key never appears in the thought text, live or after reload; it
      shows as `[REDACTED]`.
- [ ] **Very long thinking**: ask for a deep multi-part analysis. Expected: the block stays
      responsive. Thought stops growing after a long while (capped at roughly 24,000
      characters), and the answer still arrives.
- [ ] **Reduced motion**: macOS System Settings → Accessibility → Display → Reduce motion ON.
      Expected: no shimmer on **Thinking…** and no pulsing dot. The label shows in grey.
- [ ] **Theme switch**: change theme/accent while a block is visible. Expected: the block re-skins
      (muted text, accent ✓, red ✕). No hard-coded colours.

---

## 4. Cross-feature checks

- [ ] **SOL window / pill**: the same block appears in the floating SOL window and behaves the same.
- [ ] **Command runs (Build)**: an auto-run command's output row still appears below the block.
- [ ] **Research sources**: a web-research question still shows the source pills under the answer.
      Its `research` step shows inside the Thinking block.
- [ ] **Drive strip (if drive is enabled)**: a `drive.step` still shows its strip. Its step also
      appears in the block.
- [ ] **Usage / credits**: Billing → usage for the turn. Expected: no unusual jump compared with
      before for the same kind of question (summaries add no thinking tokens on these routes).

---

## 5. Sign-off

| Area                   | Pass | Fail | Notes |
| ---------------------- | ---- | ---- | ----- |
| 2.1 Expert live + fold |      |      |       |
| 2.2 Guide stays open   |      |      |       |
| 2.3 Reload             |      |      |       |
| 2.4 Steps only         |      |      |       |
| 2.5 Build + card       |      |      |       |
| 3 Edge cases           |      |      |       |
| 4 Cross-feature        |      |      |       |
