# Cowork QA — SOLUSDEV-323 Onboarding redesign ("SOL walks you in")

Governing spec: `docs/wireflows/onboarding.md`. Mark each row ✅ / ❌ and note what you saw.

## Setup

- [ ] Desktop app running from branch `SOLUSDEV-323-onboarding-redesign` (`pnpm dev:all`), API + DB up,
      **migrations not needed** for this ticket.
- [ ] A **brand-new** Solus account (never onboarded). For resume tests you will also need a second
      machine or a second fresh profile signed into the same account.
- [ ] macOS: note whether Solus currently has **Screen Recording** and **Accessibility** permission
      (System Settings › Privacy & Security). Run section D once with Screen Recording **off**.
- [ ] Test material: a GitHub account with at least one repo; a KiCad netlist export (`.net`) or
      board file (`.kicad_pcb`).
- [ ] For section H also run once with macOS **Reduce motion** on (Accessibility › Display).

## A. Meet (step 1)

1. [ ] Sign in with the fresh account → the onboarding window opens on **Meet**: a glowing orb
       lights up on the left, headline **"Hi — I'm SOL."**
2. [ ] The progress rail at the top shows six labels `MEET PROJECT VOICE ACCESS CONNECT BUILD`;
       the MEET segment is half filled.
3. [ ] Three cards rise in one after another: _Reads your whole robot_, _Sees what you're stuck on_,
       _Catches what breaks between worlds_.
4. [ ] No **Skip setup** link in the header on this step.
5. [ ] Click **Let's set up** → Project step.

## B. Project (step 2)

1. [ ] Headline **"What are you building?"**; header now shows **Skip setup**; **Back** at bottom left.
2. [ ] With an empty description the primary button reads **Skip — name it later**; the project name
       reads "My first robot" in grey; the worlds card says `TYPE TO START`.
3. [ ] Type `STM32 firmware` → the **Software** chip lights up blue with a small pop; the counter reads
       `1 OF 4`; the orb on the left breathes faster.
4. [ ] Click the **Quadruped** example → the textarea fills; all four chips light; `4 OF 4`.
5. [ ] The **PROJECT NAME** line shows the first sentence ("A 12-DOF quadruped for outdoor
       inspection"). Remember it — section F checks the real project gets this exact name.
6. [ ] Clicking an example creates nothing (no project appears anywhere yet).
7. [ ] **Back** returns to Meet; **Let's set up** returns here with the text kept.
8. [ ] Click **Continue** → Voice.

## C. Voice (step 3)

1. [ ] Headline **"How should I talk to you?"**; two cards, **Guide** selected (amber outline).
2. [ ] The preview card shows the question "Why does my I²C bus hang on boot?" and a long Guide
       answer with a `CONCEPT · I²C ADDRESSES` box.
3. [ ] Click **Expert** → the answer cross-fades to a two-line terse answer; button reads **Use Expert**.
4. [ ] Keyboard: Tab onto the selected card, press ←/→ → the selection moves and focus follows.
5. [ ] With Expert chosen, click **Skip setup** in the header → you land in the workspace. Open
       Settings › SOL on **another machine/profile** → mode is **Expert** (saved immediately).
       (Re-create a fresh account to continue the remaining sections.)
6. [ ] Click **Use Guide/Expert** → Access.

## D. Access (step 4)

1. [ ] Headline **"Want me to see what you see?"**; the orb has shrunk.
2. [ ] Two rows: **See your screen** (switch OFF) and **Summon me from anywhere**.
       No mouse-and-keyboard row on this build (expected — it ships with SOLUSDEV-319).
3. [ ] Primary button reads **Not now — continue** while the switch is off.
4. **Screen Recording NOT granted:**
   - [ ] Turn the switch on → a line appears with the platform message, **Open System Settings** and
         **Recheck**; the button becomes **Continue**.
   - [ ] **Open System Settings** opens the Screen Recording pane (not a browser, not any other URL).
   - [ ] Grant it, return, click **Recheck** → "Screen access granted" (macOS may require an app
         restart before it reports granted — note what you see).
5. **Screen Recording granted:** turn the switch on → "Screen access granted" with a green check.
6. [ ] Turn it off → note disappears; Settings › SOL shows _SOL sees your screen_ off as well.
7. **Summon practice:**
   - [ ] Without clicking anything in the app, **double-tap Ctrl** → the real SOL window opens, and back
         in onboarding the two `ctrl` key caps press and the text reads "That's it — I'm one double-tap
         away, in any app."
   - [ ] Double-tap again → the key caps press again.
   - [ ] **Show me** opens the SOL window without a key press.
   - [ ] Settings › SOL → turn hotkeys off, come back → the row shows "SOL's hotkeys are off…" and no
         key caps; **Show me** still works. Turn hotkeys back on.
8. [ ] Click **Continue / Not now — continue** → Connect.

## E. Connect (step 5)

1. [ ] Headline **"Plug in your tools."**; the stage line reads "From what you told me, start with
       GitHub and KiCad." (with the Quadruped description) — or "Pick the tools your team already
       lives in." if the description was empty.
2. [ ] Tools sit on a ring round a small orb; tools whose world you described show `SUGGESTED`.
3. [ ] Footer: `0 CONNECTED · 2+ RECOMMENDED`, **Skip for now**, **Build my graph** disabled.
4. [ ] Click **GitHub** → the real connect wizard opens. Complete it → the tile glows blue, a wire
       grows from the orb to it, the footer reads `1 CONNECTED · 2+ RECOMMENDED`.
5. [ ] Connect **KiCad** with the netlist/board file → yellow glow + wire; footer
       `2 CONNECTED — READY`; Skip disappears; **Build my graph** enabled.
6. [ ] Cancel a wizard midway → the tile returns to its idle state; nothing fake is shown.
7. [ ] Force an error (e.g. pick a non-KiCad file) → the tile shows **Retry** and the error; hover the
       tile status to read the full message.
8. [ ] Narrow the window to its minimum width → the ring shrinks; at the narrowest it becomes a plain
       two-column grid. Every tool remains clickable at every width.
9. [ ] **Back** returns to Access.

## F. Build (step 6) and Land

1. [ ] Click **Build my graph** → headline "Building your graph."; the orb spins faster.
2. [ ] Each connected source has a row with a shimmering detail until its sync finishes, then the real
       `N entities · M relations` (or the real error in red).
3. [ ] The graph panel draws nodes in the sources' colours (blue for code, yellow for electronics) with
       edges drawing in; failed or empty sources draw nothing.
4. [ ] Summary line: "N entities in your graph, from your synced sources." (real number).
5. [ ] The _FIRST THING TO TRY_ card and **Open workspace** appear when done.
6. [ ] **Open workspace** → the workspace opens; the project is named exactly as in B.5; a pill rises
       at the bottom centre: "I'm here whenever — double-tap ctrl from any app." with **Dismiss**.
7. [ ] **Dismiss** hides it; reload → it does not return. Without dismissing it hides after ~9 s.

## G. Resume and skipping (FND-08)

1. [ ] Fresh account: go to **Access**, quit the app, relaunch → resumes on **Access**.
2. [ ] Same on **Voice** and **Connect** → resumes there.
3. [ ] Quit on **Project** → resumes on **Meet** (by design: the server's default value is the same as
       the Project step's).
4. [ ] Finish onboarding, sign in on a second machine → goes straight to the workspace.
5. [ ] **Skip for now** with zero tools → Build completes with "No sources are syncing yet…" and an
       empty graph reading "Your graph draws itself here as your sources sync."
6. [ ] API down (stop the backend) → the whole flow still completes; the workspace opens.

## H. Motion and accessibility

1. [ ] Every step's content rises in (slide up + de-blur), staggered; no jank on a normal laptop.
2. [ ] With **Reduce motion** on: nothing animates, the orb is still, the landing pill is still centred
       at the bottom, every step is fully usable.
3. [ ] Keyboard only: you can complete the whole flow with Tab / Shift+Tab / Enter / Space / arrows.
4. [ ] VoiceOver reads the progress as "Step N of 6", the Voice cards as radio buttons, the Access
       switch as a switch with its on/off state.

## Cross-feature checks

- [ ] Home › Connected accounts still connects tools exactly as before (it shares the connect
      plumbing that was refactored for the ring).
- [ ] Settings › SOL reflects the screen switch and SOL mode chosen during onboarding.
- [ ] The SOL window opened by a double-tap during onboarding behaves normally afterwards.
