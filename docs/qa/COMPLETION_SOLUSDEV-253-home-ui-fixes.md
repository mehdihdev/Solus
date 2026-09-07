# Completion report — SOLUSDEV-253 · Home UI fixes

Branch `SOLUSDEV-253-home-ui-fixes`, stacked on `SOLUSDEV-250-code-environment` (merge order
I2 → I4 → I3 → this). Not pushed; no MR opened. The ticket number is provisional — rename the
branch if the real ticket differs.

## What was asked, what was found

1. **Connect wizard showed a letter "S" for Solus.** The link header's Solus endpoint now draws
   the `SolusLogo` (theme-tokenised mark) inside a frameless `EndpointMark`; the same header
   serves the simulator-start dialog.
2. **"Switch to" sent the user to the Workspace.** Not reproducible on this build: the card's
   footer button only re-scopes Home (`switchWorkspaceProject(project, 'home')`, no
   navigation), verified live over CDP and by the existing HomeScreen tests. Mehdi re-tested and
   confirmed it looks fine; no change made.
3. **"Open in editor" greyed out with no visible reason.** Two causes, both fixed:
   - Root cause: on a project switch the companion supervisor (`main/companion.ts`
     `replaceChild`) signalled only the `uv run` wrapper pid, so the detached companion child
     survived. Old and new companions then superseded each other on the bridge forever (close
     4409 loop), the topbar showed "Bridge offline", and every Open-in button greyed. Verified
     live: five companion processes for four projects under one desktop. Now `killTree`
     (process group) with a SIGKILL escalation after the same grace `stopCompanion` uses; a test
     spawns a real harmless child and asserts the negative-pid SIGTERM.
   - The disabled button said why only in a hover tooltip; the reason is now a note under the
     buttons (the offline notes that already existed still cover their own cases).
4. **"How you engineer" → the project's `.solus`.** New `SolusCard` on Home: the current
   project's five `.solus` sections (docs/api/solus.md) with honest counts, rows that open in
   place (grid-row animation, chevron turn), typed/SOL-filed notes with Edit and a two-click
   Delete, imported files with type and size, "Add a note" (the Workspace's `SolusComposer`)
   and "Import file". It reuses `useSolusConfig`/`useSolusActions`, so a note added on Home is
   the same node the Workspace shows. Honest states for no project, offline and loading. The
   "How you engineer" document (HOME H3, SOLUSDEV-244) moved to Settings, under Appearance —
   delegated judgment, so the ~/.solus preferences keep an editor.

## Governing docs

`docs/wireflows/home.md` (amended: the `.solus` card replaces the HOW YOU ENGINEER card;
Settings hosts it), `docs/api/solus.md` (unchanged: no new route), `docs/api/local-folder.md`
§5, DECISIONS.md ADR-034. `docs/design/SPEC.md` is a copy of the CI file and
`docs/design/screens/` does not exist — noted.

## Verified live (this Mac)

- Scratch Electron harness against the real API on :8001 (Mehdi's own desktop held the
  single-instance lock): the card renders under Connected accounts with `.SOLUS · Rover FW`;
  Error logging opens to the eight SOL-filed entries; "Add a note" → composer → Add filed
  "Wheelbase 1.6 m, 6S battery" into Project details (toast "Added to .solus › Project
  details", count 1, Edit/Delete present); the GitHub connect wizard's Solus end is the SVG
  mark with no letter. Screenshots 26–30 in the session scratchpad.
- The supervisor fix cannot be exercised inside a running dev desktop without restarting its
  main process; the unit test covers the signal shape.

## Tests

Desktop: `companion.test.ts` (+1 process-group kill), `ProjectFolderCard.test.tsx` (+1 inline
reason), `ConnectWizardModal.test.tsx` (+1 logo), `SolusCard.test.tsx` (6: honest states, rows
and counts, add, edit, two-click delete, import), `HomeScreen.test.tsx` (card hosted online,
absent offline), `SettingsScreen.test.tsx` (+1 hosts the preferences document). Lint clean on
the touched files except one pre-existing `react-refresh/only-export-components` hit in
ConnectWizardModal.tsx (a utility export, present on HEAD). Typecheck clean.

## Phase 4 review findings (all fixed before handoff)

Code review (1 HIGH): the retired child's own `exit` listener still scheduled a backed-off
restart of the OLD command, spawning a phantom second companion over the new one → `retire`
detaches the listeners first (test: no restart probe, one SIGTERM). Security review (2 HIGH, 3
MEDIUM, 2 LOW): H1 — the SIGKILL escalation keyed on "some process holds this pid" and could
hit a recycled pid → it now keys on THIS child's exit event (tests: a child that dies gets no
SIGKILL, one that ignores SIGTERM gets exactly one group SIGKILL); H2 — no hostile-text fixture
on the new render surface → added (model-authored text, script-shaped file name, markup in
media type all render as text, no element created); M1 — a double-click or held Enter defeated
the delete arming → 400 ms dwell floor and key-repeat guard (tests); M2 — no coalescing of a
respawn storm → replacements inside 500 ms collapse onto one respawn (test: a burst leaves one
child); M3 — the card kept composers across a project switch → `key={project id}` on Home; L1 —
the delete button now names the note it would delete; L2 — `taskkill` and `ps` pinned to their
system paths.

## Found on the way

- The H9 PostToolUse hook invokes vitest as `--silent=<file>`, which vitest rejects; the hook
  reports a failure for every new desktop test file even when the suite passes. Human-owned;
  flagged, not edited.
- My "Switch to" reproduction killed Mehdi's running desktop at 11:47 and orphaned its two
  companions (terminated afterwards). Reported in-chat.
