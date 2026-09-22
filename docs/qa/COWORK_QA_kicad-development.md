# KiCad development — SOLUSDEV-261

This is an execution checklist, not a claim that the live circuit is complete.

Packaged-runtime regression, 2026-09-12: the strict argument adapter originally
passed MCP SDK unit tests but failed startup under the fork's pinned FastMCP 2.
The corrected adapter validates raw inputs before either SDK can coerce them.
The real `bin/launch` regression verifies 15 advertised tools, refusal of unknown
fields and string booleans, and a valid create preview with no files created.
Full fork validation: 380 passed, one existing expected failure. Independent code
and security reviews passed. The restarted live bridge advertises 29 tools across
Code, KiCad and Local. This does not prove a linked schematic write or circuit ERC.
After restart, a live SOL call to `kicad.get_symbol_definition` returned Device:R
with pins 1 and 2, both passive. No write or approval was performed.

## Installed acceptance evidence — 2026-09-12

The current scoped circuit excludes XIAO/driver wiring and all physical hardware,
per the user's later instructions. The owned operation layer generated a disposable
Uno + FSR402 resistive-model + 10 kΩ divider. The real installed KiCad 10.0.6 CLI
export and ERC, plus reads through the sanctioned `bin/launch` MCP transport,
verified the saved diagram. No product approval was automated and no companion
workspace registry was changed for this fixture test.

Evidence directory on this development machine:
`/home/beeboss/Solus/tmp/integration-check-kicad/verified-divider-final/`.
It contains `uno_fsr_divider.kicad_pro`, `.kicad_sch`, `.net.xml`, `.pdf`, `.svg`,
`.png`, `erc-result.json`, `launcher-readback.json` and `graph-proof.json`.

- [x] Read the actual installed 32-pin Uno and two-pin passive definitions.
- [x] Create/place/wire/label/mark-unused operations; dry-run symbol placement
  leaves bytes unchanged and matches the committed fingerprint.
- [x] Native netlist: `/SENSE_A0` contains A1 pin 9, RFSR1 pin 2 and R1 pin 1;
  `/+5V` contains A1 pin 5 and RFSR1 pin 1; `/GND` contains A1 pins 6, 7 and 29,
  R1 pin 2 and FLG1 pin 1.
- [x] Real ERC: `checked:true`, `passed:true`, zero errors and zero warnings.
  KiCad's default ignored checks are disclosed: single global label, four-way
  junction, SPICE model issue and footprint filter. No project-specific rule
  settings or manufactured exclusions were applied.
- [x] Actual MCP launcher advertises 15 tools; geometry, native netlist export
  and ERC read back the fixture. Netlist export must say `degraded:false`.
- [x] Solus' actual parser and graph mapper produce 34 entities, 35 relations
  and zero mapping errors. This includes native unconnected-pin net records;
  the three shared ground pins remain on one component-to-net relation.
- [ ] Authenticated project's KiCad source is bound to this schematic, and its
  change signal updates persisted graph topology. Pure graph mapping above does
  not establish this step; local-folder discovery alone only creates a project node.

The FSR uses the real generic `Device:R_Variable` symbol with no invented footprint
or manufacturer pin numbering. Its value identifies it as a generic FSR402 model.
The manufacturer's [FSR400-series datasheet](https://www.interlinkelectronics.com/downloads/datasheets/fsr-400-series-datasheet.pdf)
describes a two-wire resistance and divider circuit. The 10 kΩ measuring resistor
is the requested example, not a universally validated calibration. FLG1 explicitly
records the example's USB-powered-board ground assumption; it is an ERC supply
assertion, not hardware verification or a measured current rating.

Two native checks exposed and fixed defects: newly placed visible fields were
stacked at the symbol center while footprint text was exposed and datasheets were
discarded; workspace-relative MCP project exports reached the Flatpak adapter
with a relative schematic path, producing a degraded synthesized netlist. Fields
are now separated with pin clearance, metadata is hidden, actual library datasheet
values are preserved, and verified input bytes reach the adapter through its
bounded stdin transport.

The fresh security review also required binding both export sinks to the verified
bytes. Discovered schematics now pass through the bounded no-follow reader once;
the CLI and fallback consume a private snapshot instead of reopening mutable source
paths. Ordinary relative child-sheet references retain their layout inside that
snapshot. Native snapshots live in random 0700 OS temporary directories outside
the bound workspace, inaccessible to workspace-confined capabilities. The Flatpak
helper receives the captured closure over stdin and recreates it in container-private
temporary storage. This boundary excludes arbitrary same-user OS code; a configured
workspace containing the temporary root fails closed. The closure is limited to 64 files, 32 MiB total and depth 32; symlinks,
escapes, absolute/variable references and cycles are refused. Snapshots are cleaned
up after use. Regressions cover initial symlinks, CLI-time replacement, replacement
immediately after a successful read, hierarchy confinement and closure limits.

Both native export and ERC receive inherited anonymous output descriptors rather
than writable filesystem pathnames; netlists are capped at 32 MiB and ERC at 8 MiB.
ERC preserves the native violations exit code (5) and validates the actual report. Installed Flatpak
1.14.6 rejects `--forward-fd`, so its fixed owned helper creates the descriptor
inside the container, invokes `/app/bin/kicad-cli` with `pass_fds`, and returns only
bounded XML or ERC JSON on stdout. This mechanism was verified against the installed runtime.
Legacy Flatpak source and output path arguments are refused. Large artifacts are staged,
synced, atomically published and read back through a held artifact-directory
descriptor, with directory identity checks. Deterministic swaps **before the
native write**, plus publication swaps, verify that an external sentinel is
neither overwritten, returned nor deleted.

Validation: `SOLUS_TEST_INSTALLED_KICAD=1 .venv/bin/pytest -q
integrations/mcp/kicad/tests` — 419 passed, one existing expected byte-roundtrip
failure. The installed acceptance is opt-in; its disposable directory is removed
after the test. Persistent evidence above was generated separately.

## Setup

1. [ ] Start this checkout with `pnpm dev:all`. Sign in to Solus and select
   **Workspace W242 Service QA**. The API, background worker and companion must
   remain running.
2. [ ] In native Solus, open Home → Local folder → Link folder and select
   `/home/beeboss/Solus/tmp/integration-check-kicad`. This generated scratch folder
   contains an initially empty `integration_check.kicad_pro` and schematic. Do not
   select or modify ForgeTS: its existing working tree has an unresolved conflict.
3. [ ] Verify the companion reports KiCad ready and the local source appears in
   the graph. On this machine KiCad is Flatpak `org.kicad.KiCad`, version 10.0.6.
   The owned launcher must automatically find its CLI and installed symbol library.
4. [ ] Use the scoped Uno/FSR divider for this run. Driver wiring, firmware and
   board access are excluded. Do not infer additional rail loads or current ratings.

## Read and propose

1. [ ] In SOL, read the project components and nets. The empty baseline should be
   empty, not a fabricated robot circuit.
2. [ ] Ask for `Device:R` and `MCU_Module:Arduino_UNO_R3` library definitions.
   Expect actual library pins (2 and 32 respectively), values and fingerprints.
   Check that the full required pin map reaches SOL without result truncation.
3. [ ] Read the schematic geometry and record its current fingerprint. Ask SOL to
   propose a new standalone sheet in the same folder. Expect a concrete review
   card naming the new file, sheet title and before/after fingerprint.
4. [ ] Before approval, inspect the folder: no new schematic or cache should have
   been written by the dry run. Reject the card; the file must remain absent.
5. [ ] Propose again and approve manually. Read the new file back through the
   companion, open it in KiCad, and verify that its sheet exists and parses.

## Build the circuit through approval cards

1. [ ] Propose one real resistor symbol and one connector. Each card must name
   the symbol, reference, value, position and schematic. Approve each manually;
   read back the exact symbol and transformed pin locations after each write.
2. [ ] Propose a wire between two observed pins. Verify its endpoints and route,
   approve, then read back the wire and export the actual netlist. The two pins
   must belong to the same net.
3. [ ] Add a net label at an observed endpoint and a passive between two nets.
   Verify their exact endpoints and net membership after approval.
4. [ ] In a new diagram place the Uno, explicit generic FSR402 representation
   and 10 kΩ resistor. Connect the divider to Uno A0, +5V and ground. Mark only
   deliberately unused pins as no-connect; never suppress a real wiring error to
   pass ERC. Explain any supply flag's electrical assumption.
5. [ ] Run ERC through SOL. Expect `checked:true`, actual error/warning counts and
   `passed:true` only when the check completed without findings. Inspect any
   ignored-check list. Open the saved sheet in KiCad and confirm it looks right.
6. [ ] Wait for the companion change signal. Verify the local/KiCad graph updates
   without manual refresh and contains the actual Uno A0→FSR divider topology.

## Failure and authorization checks

- [ ] Modify the scratch file after a card is shown. Approval must refuse the
  stale fingerprint and perform no write; re-read and propose again to recover.
- [ ] Disconnect the companion before approval. The write must remain unapplied.
  Failed or malformed dry-run responses must never yield argument-only approval.
- [ ] Attempt a path outside the linked folder, a symlink, an existing create
  target or a malformed fingerprint. Expect a failed tool result, no partial file.
- [ ] Attempt a wire crossing an unrelated pin, wire or label. Expect explicit
  refusal rather than an implicit short. Unsupported hierarchical/bus structures
  must fail closed.
- [ ] Check exact pin/wire coordinates with four decimal places at positions over
  100 mm. Saved geometry must match the approved geometry without rounding.
- [ ] Run ERC where the CLI is unavailable or its report is malformed. Expect
  `passed:null` or a failed tool result, never a fabricated pass.
- [ ] Verify another user/project cannot execute this project's confirmation or
  reach the machine's files through its bridge session.

Record every live operation, approval, readback, ERC artifact and graph change.
Automated fixture tests and direct launcher probes are separate evidence from
this authenticated companion journey.

## Visible project-file link

1. [ ] On Home, expand KiCad's existing source. With `project_path` advertised
   by the connector, expect **Link project file**, alongside Sync now.
2. [ ] Open the form. It names that source, explains the linked-folder boundary,
   and requests a relative `.kicad_pro` path. Compare Guide and Expert guidance.
3. [ ] Enter an absolute path, `../` traversal, a schematic filename, or an empty
   path. Save must show an error without making a configuration request.
4. [ ] Cancel a valid draft. Reopen; the stored path must be unchanged.
5. [ ] Save `verified-divider-final/uno_fsr_divider.kicad_pro` when the linked
   folder is the scratch directory described above. Expect one authenticated
   source PATCH containing only `config.project_path`, then **Project link saved**.
   While pending, duplicate submission and closing are disabled.
6. [ ] Reload the source, choose **Edit project link**, and verify the saved path.
   Simulate a failed PATCH; the form stays editable and exposes no raw server error.
7. [ ] Complete an approved schematic change and inspect the resulting source sync
   and persisted nets. Saving the project link alone proves no export or graph update.
8. [ ] A connector without the `project_path` configuration capability must not
   receive this action merely because its provider name is KiCad.

## Authenticated acceptance — 2026-09-12 follow-up

In Workspace W242 Service QA, SOL read the live fixture geometry (fingerprint
`2bc16b05c72bd92b:7c71fe993461f2e0:2a5ae8e35445537c:8130c7d676a60763`)
and native Eeschema 10.0.6 netlist (15,043 bytes). It correctly identified the
divider junction as A1 pin9/A0, RFSR1 pin2, R1 pin1. Home's file chooser imported
`verified-divider-final/uno_fsr_divider.net.xml`; the actual source sync persisted
34 entities and 35 relations with zero errors. Source
`01a098b1-aa10-763c-9c7c-27712ea0ccc8` was then bound using the new visible
Project file control to `verified-divider-final/uno_fsr_divider.kicad_pro`.
A read-only database verification confirmed the same project-scoped source/path
and actual A1/FLG1/R1/RFSR1 component entities. No direct database mutation was used.

Automatic refresh after an approved schematic edit remains a separate unchecked
gate. Proposed acceptance edit: label existing R1 pin1 `SENSE_A0`; this should
preserve topology/counts and ERC while changing the saved schematic fingerprint.

A subsequent SOL turn refreshed geometry successfully, but exhausted the account's
credits before requesting the annotation preview. No label approval card or
schematic mutation occurred. Automatic post-write refresh remains unverified.

## Current checkpoint — annotation and automatic refresh verified

The blocked annotation account above is historical. A read-only audit of persisted
W242 project `01a074e0-3bb4-7317-ba53-7b653bb1f6a8` records confirms the later
successful acceptance on **2026-09-13** (all times UTC):

- [x] Confirmation `01a09a82-d510-7d0f-b302-c2b2264e6181` was approved at
  11:24:22.884933. Tool turn `01a09a82-de76-738d-a413-6b18b63877fa`, recorded at
  11:24:23.030317, returned `ok`, `changed:true`, `dry_run:false` for
  `kicad.add_net_label`, creating label `e247a927-ff59-58b7-a1db-60d07e9b20cc`.
  The schematic fingerprint changed from the previously recorded `2bc16b05…`
  to `4830624646c8eb1b:9897b171d963a5e4:b4d951a0d8f16617:6cfca33274926c4e`.
- [x] Independent SOL geometry readback turn
  `01a09a84-0400-7bab-9216-625c11703ce3` at 11:25:38.176057 returned that same
  fingerprint and the new `SENSE_A0` label at R1 pin1, `(114.3, 80.01)` mm.
- [x] The existing source `01a098b1-aa10-763c-9c7c-27712ea0ccc8` automatically
  reconciled through webhook-triggered sync `01a09a83-06e9-701d-8601-fd1ef334611f`,
  started at 11:24:33.385638 and finished successfully at 11:24:33.809206:
  zero entities created, four updated, zero errors. This was not a manual sync.
- [x] Current source-scoped graph net `01a098b1-aa51-7bfb-b35b-83b699d06417`
  (`/SENSE_A0`) retains `connected_to` relations for A1 pin9/A0, R1 pin1 and
  RFSR1 pin2. The label annotates an already named net; its existence alone
  would not prove the later write. The saved mutation result, changed fingerprint,
  subsequent geometry readback and webhook sync establish that acceptance.

Evidence was recovered from local conversation/tool/sync/graph records, without
provider or companion calls or database mutations. This checkpoint closes the
specific label-write and automatic-refresh gate; it does not mark unrelated
unchecked failure-path or ERC checks as passed.
