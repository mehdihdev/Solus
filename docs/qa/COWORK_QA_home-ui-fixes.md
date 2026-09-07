# COWORK QA — Home UI fixes (SOLUSDEV-253)

Self-sufficient end-to-end test plan. You have the running application and this file only.

## Required setup

- Desktop in dev mode with the companion (`SOLUS_COMPANION_DEV_CMD` set), signed in as a
  verified member of a team with at least TWO projects, one of them with a folder linked on Home
  (see `COWORK_QA_i2-local-folders.md`) and a few `.solus` entries (Workspace › `.solus` node,
  or an approved failing `code.test` run from `COWORK_QA_i3-code-environment.md`).
- A GitHub account not yet connected (for the wizard header).

## Flow 1 — the connect wizard shows the Solus mark

1. Home › Connected accounts › Software › GitHub › **Connect**. Expected: the header shows the
   Solus logo (the graph mark on its rounded tile, in the theme's accent) — travelling dots —
   the GitHub logo. No letter "S" anywhere in the header.
2. Settings › Appearance: change the accent. Reopen the wizard. Expected: the mark re-skins.

- [ ] 1 · [ ] 2

## Flow 2 — switching projects keeps the companion alive

1. Home: with project A current, click **Switch to** on project B's card. Expected: you stay
   on Home; the topbar pill reads B; B's card button now reads "Open", A's "Switch to".
2. Within ~10 s the topbar chip settles on "Bridge ready" (or "Bridge attention" for a
   misconfigured fork) — NOT a flapping "Bridge offline".
3. Switch back to A, then to B again, three times. Expected: the chip settles each time; in a
   terminal `pgrep -f "python3 -m solus_companion" | wc -l` prints 1.
4. Home › Local folder card (project with a linked folder): **Open in editor** is enabled once
   the chip is ready and launches VS Code on the folder.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Flow 3 — a greyed "Open in editor" says why

1. Quit the companion (or wait for it to restart after a switch). Expected: the button is
   disabled AND a small note under the buttons reads "Solus companion is offline on this
   machine".
2. On a machine without VS Code, expected note: "VS Code is not installed on this machine".
3. Immediately after linking a folder, before the first scan lands: "Not scanned yet".

- [ ] 1 · [ ] 2 · [ ] 3

## Flow 4 — the project's `.solus` on Home

1. Home, right column, below Connected accounts: a card labelled **.SOLUS** with the current
   project's name and five rows — Hardware configs, Project details, Error logging (chip
   "AUTO + YOU"), Documentation, Code environment — each with its count ("EMPTY" when none).
   Counts match Workspace › `.solus` node.
2. Click **Error logging**. Expected: the row opens in place (smooth slide, chevron turns) and
   lists the entries: text, "filed by SOL" or "you", relative time, Edit / Delete.
3. Click **Project details** › **Add a note**, type a sentence, **Add**. Expected: toast
   "Added to .solus › Project details"; the note appears with "you · now"; Workspace › `.solus`
   › Project details shows the same node.
4. **Edit** the note, change the text, **Save**. Expected: the text updates in place; Workspace
   agrees.
5. **Delete** → the link turns red "Confirm delete?"; wait 5 s → it reverts to "Delete"
   (nothing deleted). Click Delete then Confirm → the note is gone here and in Workspace.
6. **Import file** on Documentation, pick a small PDF. Expected: the row shows the file name,
   media type and size; the Workspace `.solus` node gains the document.
7. Switch to another project (Flow 2). Expected: the card re-scopes to that project's `.solus`
   (name and counts change).
8. Home › with no project open (fresh team): "Open or switch to a project to see its .solus."
   Stop the API: "Solus can't reach its API — the project's .solus appears when it does." No
   invented rows in either state.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5 · [ ] 6 · [ ] 7 · [ ] 8

## Flow 5 — "How you engineer" lives in Settings

1. Settings › below Appearance: the **HOW YOU ENGINEER** card with the same View → Edit → Save
   document as before, the "Stored on this computer" note included.
2. Edit a convention, save, open SOL and ask something it affects. Expected: SOL's answer
   reflects it (it reads the document on every turn).

- [ ] 1 · [ ] 2

## Edge cases

- A `.solus` note over 4000 characters: the composer caps it; the counter appears past 3500.
- A file over 8 MiB: "File too large" toast, nothing imported.
- Two desktops on the same account: a note added on one appears on the other after its next
  `.solus` read (open/close the section, or switch projects and back).
- Keyboard: Tab to a section row, Enter opens it; Tab to Delete, Enter arms it, Enter again
  confirms — a single Enter never deletes.

- [ ] all edge cases exercised
