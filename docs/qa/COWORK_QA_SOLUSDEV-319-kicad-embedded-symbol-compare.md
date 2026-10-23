# COWORK QA — SOLUSDEV-319: KiCad `add_symbol` accepts KiCad-saved schematics; real refusal reasons

## What changed

- SOL's KiCad `add_symbol` tool used to refuse (`unsupported_symbol`) any symbol already present in
  a schematic KiCad had saved, because KiCad re-indents the embedded symbol copy. It now treats a
  whitespace-only difference as the same symbol; a copy whose content differs is still refused.
- Every KiCad write-tool refusal now reaches SOL as `<code>: <plain explanation>` (e.g.
  `stale_plan: the schematic or library changed since it was read; read it again and retry`), so
  SOL can tell the user the actual cause.
- The `agent.tool_invoked` data event now records `error_code` and, for structured refusals,
  `reason` (the code only — never message text).

## Setup

1. Solus desktop running (`pnpm dev:all`), signed in, data-collection consent ON (Settings).
2. KiCad 9/10 installed at `/Applications/KiCad` (symbol libraries under
   `KiCad.app/Contents/SharedSupport/symbols`).
3. A KiCad project saved by KiCad itself that already contains at least one `Device:R` and one
   `Device:LED` (e.g. a basic LED + resistor circuit), with its folder linked as the Solus
   project's workspace.
4. Bridge companion connected (no "Bridge attention" warning for KiCad).

## Flows

| #   | Steps                                                                                                                    | Expected                                                                                                                                                        | Pass/Fail |
| --- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 1   | SOL, Build on, Confirm every change on. Ask: "Add another 330 Ω resistor and LED to the schematic."                      | SOL reads geometry + library, proposes `add_symbol` for `Device:R` and `Device:LED`; approval cards show the concrete placement. No "unavailable" message.      | [ ]       |
| 2   | Approve both cards.                                                                                                      | Schematic file gains R/LED instances; reopening in KiCad shows them; only ONE embedded `Device:R` definition in the file.                                       | [ ]       |
| 3   | Ask SOL to build the full 5 V USB-A output circuit (polyfuse, USB-A connector, PWR_FLAGs, R + LED, no-connect on D+/D−). | All placements, wires, labels and no-connects proposed and applied; rerun ERC via SOL shows the earlier PWR_FLAG errors resolved.                               | [ ]       |
| 4   | Edit the schematic in KiCad and SAVE while SOL has a pending proposal, then approve the old card.                        | Refused; SOL says the schematic changed since it was read and re-reads instead of claiming the integration is unavailable.                                      | [ ]       |
| 5   | Ask SOL to place a symbol that doesn't exist (e.g. `Device:NotAPart`).                                                   | SOL reports the symbol isn't in the installed KiCad libraries.                                                                                                  | [ ]       |
| 6   | Ask SOL to create a schematic at a path outside the linked folder (e.g. `../other.kicad_sch`).                           | Refused; SOL says the path is outside the linked project workspace.                                                                                             | [ ]       |
| 7   | After flows 4–6, inspect `data_events` rows of type `agent.tool_invoked` for the failed calls.                           | `ok: false`, `error_code: "tool_error"`, `reason` = the code (`stale_plan`, `library_unavailable`, `path_escapes_workspace`); no paths or message text present. | [ ]       |

Additional flow — schematic open in KiCad:

| #   | Steps                                                                          | Expected                                                                                                     | Pass/Fail |
| --- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | --------- |
| 8   | Keep the schematic open in KiCad's Schematic Editor and ask SOL to add a part. | Refused; SOL asks you to close the schematic window in KiCad (project window may stay open). File unchanged. | [ ]       |
| 9   | Close only the Schematic Editor window and ask SOL to retry.                   | Placement succeeds; reopening the schematic shows the new part.                                              | [ ]       |

## Edge cases

| #   | Case                                                                                                        | Expected                                                     | Pass/Fail |
| --- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | --------- |
| E1  | Hand-edit the embedded `Device:R` in the `.kicad_sch` (change a pin number), then ask SOL to add another R. | Refused as an unsupported/mismatched symbol; file untouched. | [ ]       |
| E2  | Data-collection consent OFF, repeat flow 5.                                                                 | No `data_events` row written.                                | [ ]       |
| E3  | Fresh schematic created by SOL (no prior symbols), add R twice.                                             | Both succeed (regression of the pre-existing path).          | [ ]       |

## Cross-feature

- Undo/redo in KiCad after SOL edits still works once the file is reloaded.
- Other SOL tools (Onshape, code) unaffected; their failed calls also carry `error_code` on `agent.tool_invoked`.
