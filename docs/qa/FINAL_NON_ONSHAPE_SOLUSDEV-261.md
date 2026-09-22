# Non-Onshape acceptance — SOLUSDEV-261

Status: 2026-09-13. Branch: `SOLUSDEV-261-integration-check`.

KiCad's bounded drawing/verification/graph acceptance and the sampled tool-knowledge
acceptance are complete. Isaac's complete product lifecycle and calibrated routine
ran successfully as integration operations; its strict physical grasp criterion
correctly remained false. Local saved-code/graph/error reporting and the
user-approved build and pytest executions are verified: build exited 0 and all
three tests passed. Expired cards were replaced through fresh previews; expiry
rules were unchanged and the completed failure test was not replayed.

Onshape is paused because the user's API credits are exhausted. GitHub and ForgeTS
remain read-only; GitLab, hardware/XIAO, firmware upload and Live Bench are excluded.

## Capabilities and observed results

| Integration | Capabilities | Actual acceptance evidence | Limits / remaining acceptance |
| --- | --- | --- | --- |
| KiCad | Create supported sheets, place installed symbols, wire observed endpoints, label nets, mark unused pins, edit properties, inspect official netlists, run ERC, bind a project and refresh its graph | SOL created the Uno/FSR divider with 4 symbols, 3 wires, 7 labels and 26 no-connect markers. Saved metadata and R1 edit passed readback. ERC: 0 errors/0 warnings with 4 ignored rules disclosed. The fixed SOL netlist read returned complete official topology: 4 components/30 nets and exact A0/supply/ground membership. UI project binding plus automatic sync persisted 34 entities/35 relations and R1=`10k (1%)`, no sync error. | Unsupported schematic constructs and oversized complete reads explicitly refuse. This is not PCB autorouting or full vendor-editor automation. ERC does not prove current capacity. |
| Local folder / code | Confined file reads/writes with full preview and readback; Python environment/package/script/pytest tools; streamed execution output; static sketch pin/bus/library observations | Four real scratch files were saved through SOL. Automatic graph readback recorded A0 pinMode/analogRead, I2C/UART and Wire.h, incomplete=false. The user's intentional failure command ran, exited 2 and was filed with exact argv/output in Error logging. Reload restores pending cards; a redundant failure card was rejected without execution. The user-approved build exited 0 and pytest reported 3 passed with 3 non-failing configuration warnings. | Native MCP proves output arrives before completion and UI/API tests cover streaming; live incremental UI output was not directly observed during these completed commands. Native folder-picker verification for a durable ForgeTS link is separate. |
| GitHub / local Git | Authenticated source sync and remote code reads; local status/diff/history and repository identity matching; implementation also has separately gated commit/push tools | Real GitHub sync imported 157 entities; SOL read a repository file. Read-only ForgeTS scan matched PotosnakW/ForgeTS_internal to the actual connected source; local branch `vlfh_tsfm` differs from the cloud's `main`. Existing edits and conflict were preserved. | No GitHub writes, commits or pushes were performed. Matching identity does not establish equal branches/revisions. Durable live clone-to-source graph linkage was not newly exercised. GitLab is excluded. |
| Isaac Sim | Owned headless start/stop, pinned SO-101 loading, six graph-bound joint limits, local sensor pose, explicit finite approach/close/lift routine, actual physics readbacks and saved revisions | Full SOL start → model → calibrated sensor → clearance → approach/close/lift → stop passed. Clearance reached targets with no contact/grasp. Bottle routine lifted 37.5209 mm, final bottle force 8.29553 N, retained contact 120/120 hold steps; scene generation 4 saved. Final status stopped/session=null. | Strict targets_reached=false and grasp_observed=false: shoulder-pan error 0.01533077 rad and elbow error 0.01310253 rad exceed the unchanged 0.01-rad threshold. This is a partial physical grasp result, not an integration transport failure. No arbitrary USD/script import, GUI automation or Onshape sensor-placement provenance is claimed. |
| Tool knowledge | Published official-reference notes and Guide explanations for supported KiCad, Git and Isaac workflows | Scoped seed published KiCad 107, code 10 and Isaac 7 entries idempotently. All nine sampled live Guide questions passed with citations and version caveats. | Counts are knowledge rows, not full manuals or distinct controls. Not every new note was retrieved. Installed-version uncertainty stays explicit; published notes alone do not prove execution. |

The live rail-current analysis also behaved correctly: total demand and capacity
were unknown because qualified current ratings were missing. Its empty declared
subtotal was not presented as zero demand or proof of safety.

## Completed command acceptance

The user approved fresh build and pytest cards on September 13 at 17:36 UTC.
Both actual execution results were persisted at 17:37 UTC:

- Build: exit 0, no timeout, stdout `Build finished successfully`, empty stderr.
- Pytest: exit 0, no timeout, `3 passed, 3 warnings in 3.20s`, empty stderr.
  Warnings concern inherited `asyncio_mode`, `timeout` and `timeout_method`
  options whose plugins are absent from the isolated fixture environment.

The intentional failure check already completed with exit 2. Its redundant card
was rejected without execution. No further approval or rerun is needed for these
command checks. A live reopen check that decided cards stay absent remains in
Cowork QA; automated delayed-response and decided-card regressions already pass.

## Evidence and verification

- Project: `01a074e0-3bb4-7317-ba53-7b653bb1f6a8`.
- KiCad source: `01a098b1-aa10-763c-9c7c-27712ea0ccc8`, linked to
  `verified-divider-product/uno_fsr_divider.kicad_pro`. Auto-sync completed
  `2026-09-13T14:31:26.821459Z` without error.
- [Final drawing](../../tmp/integration-check-kicad/verified-divider-product/render/uno_fsr_divider.svg)
  and [persisted graph proof](../../tmp/integration-check-kicad/verified-divider-product/graph-proof.json).
- Error entry: `01a09b2d-ac1a-709e-bbb7-ecce17badd40`, exact intentional command,
  output and exit 2 at `2026-09-13T14:30:56Z`.
- Successful build approval: `01a09bd7-e091-7d29-aa88-ac19a1ea5d28`;
  result turn: `01a09bd8-17c3-77f1-a44d-1953e63a7bdc`.
- Successful pytest approval: `01a09bd7-f3e9-78c4-bb8e-f506c9f73a86`;
  result turn: `01a09bd8-196a-77b7-89d3-af5204b7b7fb`.
  Approval and execution records were verified with owner-conversation/project
  scoped read-only queries; no command was executed again during verification.
- Final Isaac session: `d186a720-69b7-4ccd-8add-2f4ff78581cf`, now stopped.
  Saved generation-4 artifact digest:
  `72ee0c6f9eff8c39:42e85db54b04a195:d1dcb58f20224498:0c927fec09d1724f`.
- [Detailed live chronology](ACCEPTANCE_SOLUSDEV-261.md),
  [KiCad QA](COWORK_QA_kicad-development.md),
  [code/approval QA](COWORK_QA_code-git-development.md),
  [Isaac reproduction arguments](COWORK_QA_isaac-development.md),
  [knowledge QA](COWORK_QA_integration-tool-knowledge.md).

Focused verification includes KiCad 447 passing tests (one optional skip and one
existing expected failure; new topology module 99% coverage); native/companion
command output 388 passing tests (89.01% coverage); Isaac native 101 passing tests
(85.44% coverage), plus the later native/cloud preview regression; static Arduino
observations 284 passing tests; and approval restoration 113 API/113 frontend
passing tests plus four dedicated cases. These suites overlap other recorded
checks and must not be added into a distinct-test total. Scoped lint/types and
independent Python/TypeScript/security reviews passed.
The final desktop production build also passed for main, preload and renderer.

Key fixes: `1e2ad936` scoped file-preview redaction, `398ae4dd` complete official
KiCad topology, `e1dc8b6b` Isaac preview binding-row budget, `ce652b2e` durable
approval restoration/deduplication, `19ae0814` truthful neutral approval wording.
API/wireflow amendments document restored
owner-private pending cards. Approval, auth, tenant isolation, expiry and single-use
execution remain enforced. No remote push or merge request was created.
