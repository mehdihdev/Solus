# COWORK QA — SOLUSDEV-252: SOL S1 · S2 · S3 · S5

Self-sufficient test plan for Claude Cowork. You have the running application and this file, nothing else.
Mark each numbered step ☐ pass / ☐ fail. Anything marked **(machine-dependent)** may legitimately show the
degraded state described; a crash, a silent no-op, or a missing message is a fail.

## Setup

- Desktop app running from this branch (`pnpm --filter @solus/desktop dev`, or a packaged build), signed in, a
  project selected that has a graph (the dev project "Solus Test" works).
- API running from this branch with a seeded SecretStore: from the repo root run `make seed-secrets`, then
  `uv run --package solus-api python scripts/seed-provider-keys.py --check` → exit 0 (all four refs present).
  The root `.env` must hold `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `BRAVE_API_KEY`, `GEMINI_API_KEY` (or
  `GOOGLE_API_KEY`) and `SOLUS_SECRETS_KEY`.
- Note the OS: Windows / macOS / Linux X11 / Linux Wayland, and the CPU architecture. The expected behaviour of
  hotkeys and capture depends on it (table at the end).
- Linux dev run needs `ELECTRON_DISABLE_SANDBOX=1`; a second Solus instance on one machine needs its own
  `--user-data-dir` (single-instance lock).
- **Set `SOLUS_NODE_BIN`** to the absolute path of a Node ≥ 22 in the API process's environment unless `node`
  lives at `/usr/bin/node`. Without it the vendored Brave server refuses to launch and section G degrades to
  no web tools (SOL says so; it does not invent answers).
- **The OpenAI account needs a paid tier.** On the free tier (3 requests and 10,000 tokens per minute) a
  single SOL turn with tools exceeds the window and ends with "The reasoning service is busy right now". That
  message is correct behaviour, not the bug — but it makes most of section A, F and G untestable.

## A. S1 — the reasoner, cost, cap

1. Open the SOL page (rail → SOL). Send "What is I2C?". ☐ A reply streams. ☐ Nowhere in the UI is a vendor
   model name shown (no "gpt-", "claude-", "gemini-"); the usage panel reads `Reasoner · sol-reasoner-1`.
2. In Do mode send "Call get_entity with id <an entity id from the graph> and tell me what it connects to".
   ☐ A tool call `get_entity` appears in the trace, then a reply that uses its result.
3. Toggle **Think harder** in the composer and send "What is a pull-up resistor?". ☐ The reply arrives; the
   effort label (if the classify indicator is visible) reads one step deeper; the toggle resets after send.
4. Usage panel: ☐ the credit count moved after each turn.
5. (Backend, optional) With a trial account whose spend is at the cap, a turn returns the SSE error
   `trial_cap` and the UI shows the rate-limited/out-of-credits message. ☐

## B. S2 — streaming

6. Ask for something long: "Write a 600-word explanation of PID tuning with a code block, a table of gains and
   a bullet list." ☐ Text appears smoothly (no visible stutter); the code block renders as ONE block that grows
   (no flicker between plain text and code); the table does not flip between paragraph and table while rows
   arrive; the citations line (when present) does not shift the message body when it appears.
7. While it streams, scroll up. ☐ The view stays where you scrolled (does not yank back). Scroll to the bottom.
   ☐ It follows again.
8. Send five more long replies in the same chat. ☐ Scrolling the transcript stays responsive.

## C. S3 — the SOL window, hotkeys, on-screen intelligence, gesture

9. ☐ There is no corner orb anywhere (workspace, SOL page, settings). The route `#/orb` redirects to `#/`.
10. Settings → Preferences → SOL: ☐ rows "Answer mode" (Guide|Expert), "Action mode" (Guide|Build), "SOL sees
    your screen" (with the plain-language description), "Hold-Ctrl gestures". Toggle "Action mode" to Build.
    ☐ The tray tooltip changes to `SOL · Build`.
11. Focus ANOTHER application (a browser with a text field is fine). Press **Ctrl+Space**. ☐ The mode flips
    (tray tooltip / the SOL window badge); the other app did not receive a space. Press it again to flip back.
12. **(machine-dependent)** Double-tap **Ctrl** quickly. On Windows, macOS (Accessibility granted) and Linux
    x64/X11: ☐ the SOL window appears over the other app and takes focus. On Linux arm64 or Wayland: nothing
    happens, and the SOL window status line / tray say `Circle mode: press Ctrl+Shift+C, then draw a loop`;
    press **Ctrl+Shift+Space** instead → ☐ the window appears.
13. In the other app: type text, Ctrl+A, Ctrl+C, Ctrl+V. ☐ Copy/paste work exactly as before (SOL never
    consumes Ctrl+key chords).
14. Close the SOL window, move it after reopening, resize, close and reopen. ☐ It reopens where you left it, at
    the same size; on the display under the cursor if the saved display is gone.
15. Pin (always-on-top) toggle in the header: ☐ the window stays above other apps while pinned.
16. With "SOL sees your screen" OFF, hold Ctrl and circle something on screen (or Ctrl+Shift+C then circle).
    ☐ The window opens with the single line "SOL didn't look — turn on SOL sees your screen in Settings to let
    it." No capture happened (nothing in the composer).
17. Turn "SOL sees your screen" ON. ☐ The green dot + "sees your screen" appears in the SOL window header and the
    tray icon gains a dot. macOS: ☐ if Screen Recording is not granted, the status line explains and names the
    setting. Wayland: ☐ the status line says capture is unavailable; nothing else breaks.
18. Hold Ctrl and circle a feature of the other app (a button, a drawing). **(machine-dependent: hook cells
    only; otherwise Ctrl+Shift+C, then circle within 10 s.)** ☐ The SOL window shows the crop with the app/title
    caption, the line "What do you think this is?" and the composer placeholder "What would you like to know
    about it?". Click "What do you think this is?". ☐ A tentative read streams ("This looks like…"). The
    ContextPanel lists `Screen (tentative read)`.
19. Type a question with the region still attached and send. ☐ The reply refers to the region; the chip
    disappears after the send; the user row shows "screen attached". Reload the conversation. ☐ No image is
    stored in the transcript (only the marker).
20. Attach a region, then × it. ☐ Nothing is sent, the chip is gone. Attach a region and sign out. ☐ After
    signing back in the region is gone.
21. Turn "Hold-Ctrl gestures" OFF. ☐ Double-tap Ctrl does nothing; Ctrl+Space and Ctrl+Shift+C still work; the
    status line says gestures are off. Turn it back on.
22. Kill the API while the SOL window is open and send a message. ☐ A plain error, no crash; the window stays.

## D. Cross-feature

23. The SOL page and the SOL window share the conversation: start a reply on the page, open the window. ☐ The
    same conversation streams in both.
24. Switch project in the workspace. ☐ The SOL window follows the active project; an attached region is cleared.
25. LANE D Guide overlay (`#/overlay`) unaffected: ☐ the overlay window code path still loads (no console error
    at boot mentioning orbOverlay).

## Platform expectations (what "degrade honestly" means)

| Capability                                 | Win x64/arm64 | macOS                                                             | Linux X11 x64                    | Linux X11 arm64                      | Linux Wayland              |
| ------------------------------------------ | ------------- | ----------------------------------------------------------------- | -------------------------------- | ------------------------------------ | -------------------------- |
| Ctrl+Space, Ctrl+Shift+C, Ctrl+Shift+Space | works         | works (unless another app owns Ctrl+Space → status line names it) | works                            | works                                | unavailable, message shown |
| Double-tap Ctrl / Ctrl-hold circle         | works         | needs Accessibility → message + pane name                         | works                            | fallback (Ctrl+Shift+C) with message | fallback                   |
| Screen capture                             | works         | needs Screen Recording → message                                  | works                            | works                                | unavailable, message       |
| Tray                                       | works         | works                                                             | works (GNOME needs AppIndicator) | same                                 | same                       |

## Debugging a gesture that "does nothing"

Start the desktop with `SOLUS_DEBUG_GESTURE=1`: the terminal prints one `[gesture]` line every 30 cursor samples and
one per evaluation (coordinates and the circle analysis only, never pixels). A loop needs ≥ 200 px of travel, a
≥ 40 px box, ≥ 300° of sweep and an end within 25 % of the box diagonal of where it started; hesitating mid-loop is
fine (the stroke is kept for the 10 s window).

## E. S5a — diagrams, filing, error logging

26. In a project whose graph has a board and parts (the dev project works), ask SOL: "Draw me a wiring
    diagram for how the servo bus connects to the controller." ☐ A diagram appears in the reply as an image.
    ☐ Pins the graph knows are labelled; anything it does not know is drawn dashed and named as unknown in
    the legend — SOL must never print a confident pin number the graph has no record of.
27. Under the diagram: ☐ a "File this to…?" row listing the five `.solus` sections. Choose Documentation and
    file it. ☐ It confirms, and the entry appears in the project's `.solus` panel as a document node.
    ☐ Filing the same card twice is impossible (the control is gone or disabled).
28. Choose "Keep in chat" on another diagram. ☐ Nothing is filed; the image stays in the transcript.
29. With the API stopped, file a diagram. ☐ An error appears inline on the card; the card stays usable.

## F. S5b — SOL acts on the machine

Setup: the companion must be running and linked to a project working copy (Settings → the project's folder).
Every step here is a **destructive action**: nothing may run before you approve it.

30. Ask: "What Python environment does this project use?" ☐ SOL probes the linked workspace through I3
    without approval. ☐ It reports observed virtual environment facts; unsupported conda/Docker inventory
    and missing host facts remain unavailable rather than invented.
31. With a real `sim` virtual environment in the linked folder, ask: "Link the sim environment." ☐ A confirmation card appears first,
    showing the environment as the machine describes it (type, interpreter, path, python version, package
    count). ☐ Approve → a `.solus` → Code environment entry appears with those values and a provenance chip.
    ☐ Ask again for an environment name that does not exist on this machine ("link the foo environment"):
    SOL refuses; **no** empty or invented entry is created.
32. Ask: "Install `mujoco` in the sim environment." ☐ A confirmation card appears **before anything runs**,
    showing the exact command including which interpreter it targets. ☐ Approve → it runs, output streams
    back, and the environment's package list updates with provenance `sol`.
    ☐ Ask SOL to link that environment again: the SAME entry updates (no duplicate) and the new package is
    now in its list.
33. Repeat 32 but **reject** the card. ☐ Nothing ran: the package is not installed and the machine is
    untouched.
34. Ask SOL to run a command that will fail (e.g. "run `pytest` in a folder with no tests"). ☐ Approve.
    ☐ An entry appears in `.solus` → Error logging with the command, the output, the timestamp and the
    entity it was about, marked as filed by SOL — and it is editable. ☐ **A command that runs and exits
    non-zero counts**: a workspace script containing `import nope` must file a row reading `exit 1` with the traceback, not
    be treated as a success because the command was delivered.
35. **The inverse check, which is what the fix was for**: ask for a machine action and leave the card
    **unanswered**. ☐ No Error logging entry appears while it sits waiting. An entry may only appear after
    you approve and it actually fails.
36. Ask: "Add a Dockerfile for the training environment." ☐ Card shows the file and its content → approve →
    the file exists with the content that was shown. ☐ **Read the content row carefully**: each Dockerfile
    line must be separated on the card (`FROM python:3.12-slim WORKDIR /app`), never run together into
    words that are not in the file.
37. Ask SOL to read a file outside the project folder (e.g. `../../etc/passwd`). ☐ Refused with a message
    about the workspace; no card, or a card whose approval still refuses.
38. While an install is running, quit the app. ☐ Reopen and check with your OS process viewer that the
    install is not still running in the background.

## G. S5c — research and datasheets

39. Ask: "What's the stall current of an STS3215?" ☐ SOL searches, and the answer cites the sources it used
    with real links. ☐ It does not invent a figure when it cannot find one — "I could not find it" is a pass.
40. Ask for something with an official datasheet: "Read the OV9281 datasheet and tell me its pinout."
    ☐ Specs come back **with page numbers**. ☐ SOL offers to save an extracted part definition, and that
    offer is a confirmation card — approve it and a `.solus` Hardware entry appears with the page citations.
41. ☐ A research request finishes in a bounded time and does not run away: the reply names its sources and
    stops.
42. Put a convention in your root preferences (Settings → engineering preferences), e.g. a units rule, that
    contradicts a general default. Ask a question that hits it. ☐ The answer follows _your_ convention.
43. ☐ The context panel names which layers the turn used (corpus, preferences, project `.solus`, screen) and
    says plainly when one is empty — an empty layer must be reported, not hidden.

## Known machine-dependent expectations

Anything marked machine-dependent in section C applies here too: on Linux arm64 or Wayland the hold-Ctrl
gesture is replaced by circle mode, and screen capture is unavailable on Wayland.

## H. September 11 follow-up — shortcut, headers and graph mentions

Setup: run `pnpm dev:all`, sign in, and select a project with a synced GitHub
source containing code-file graph entities. Keep a second accessible project
available for isolation checks. Use an actual desktop session for global shortcuts;
a browser-only session cannot establish acceptance.

1. [ ] On Windows/Linux press Ctrl+Shift+Space; on macOS press Cmd+Shift+Space.
       The SOL window opens even when native gesture hooks are unavailable. Repeat to
       exercise the existing summon behavior. Test while another application has focus.
2. [ ] On Wayland, accept the compositor shortcut portal request if offered.
       If unsupported, denied, or the shortcut cannot register, the status explains the
       limitation and the clickable Open SOL window action still opens the window.
3. [ ] The main SOL page has no Guide/Expert header selector. The floating window
       has no header mode selector; its composer controls remain. Settings still
       provides user preferences.
4. [ ] Open the floating window, then select another project in the main window.
       The floating window follows that project without restarting the desktop app.
5. [ ] Type `@` followed by a synced GitHub file's full path or distinctive path
       segment. The matching code-file/module appears with its path in the dropdown.
       Select it and send a question; the entity is included as graph context.
       Graph metadata does not itself include the raw file body; source-text requests
       must use the existing authorized source tool and report retrieval failures.
6. [ ] With a search pending, switch projects. Previous results and selected
       mention IDs disappear. Switch back and confirm stale results do not return.
       An entity from an inaccessible project must never appear.
7. [ ] Search for literal `%` and `_` characters in paths. They behave as literal
       characters, rather than broad SQL wildcards. Deleted entities stay absent.
8. [ ] If embedding access is unavailable, the UI/API reports the access failure
       without endless retries. The September 11 direct probe returned HTTP 403
       `model_not_found`; do not mark embedding generation passed without a later
       successful provider response.

Automated checks do not substitute for steps 1–2 on each target operating system.
