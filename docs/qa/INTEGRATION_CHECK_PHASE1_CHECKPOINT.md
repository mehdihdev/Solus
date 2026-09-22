# SOLUSDEV-261 — Phase 1 checkpoint, 2026-09-12

Phase 1 is in progress. This is not a completion report for Onshape development.

## Implemented and verified

- Account document tree: cached root, owned/shared collections, recursive folders,
  explicit refresh, page append and duplicate suppression. Flat account browsing
  no longer reuses the 50-document tracking cap.
- Generic account capability selects the tree; shared UI has no Onshape-name branch.
- Owner authorization precedes cached reads. Cache-only misses do no credential or
  provider I/O. Navigation validates origin, paths and advancing offsets. Corrupt
  cached pages are invalidated and errors preserve existing UI rows for retry.
- Vendor metadata declares supported operating systems. Unsupported applications
  never launch/retry/execute and show neutral availability text; license and
  upgrade actions are hidden for these rows. Compatible failures remain visible.

Live UI evidence from the connected account:

- Owned by me returned six folders and eight root documents.
- `SO101 Assembly.step` returned three successive pages of 20 documents, proving
  browsing beyond the previous 50-item cutoff. All three requests returned 200.
- Shared with me showed six documents, including `Full Hand` and `Elegoo Robot`.
- Collapse/reopen preserved both loaded pages without an additional request.
- The companion popover showed **code READY, kicad READY, local READY**. Fusion,
  Altium Designer, AutoCAD and SOLIDWORKS displayed `is not available on Linux`.
- The remaining bridge attention was the machine service: `no project workspace
  linked`. This is real setup state in the selected QA project, not an OS failure.

## Verification

- Integrated API regression run: **188 passed**, including existing connection and
  connector tests plus tree, auth, cache corruption and OS metadata cases.
- Full companion suite: **310 passed**.
- Full desktop suite after hosted setup changes: **3,644 passed across 357 files**
  with four workers. Electron and renderer typechecks passed.
  A prior unrestricted-worker run had one timing-sensitive hardware test failure;
  it passed in isolation and the final complete run passed. Node/web typechecks
  and scoped lint also passed.
- Independent code/TypeScript, Python and security reviews passed after fixing
  cache response validation, UI complexity and unsupported license actions.
- Tests were run RED before implementation. Coverage tooling is not installed,
  so no coverage percentage is claimed. Ponytail is not available among callable
  tools; code simplification was covered by the fresh review and lint.
- `git diff --check` passed. No remote operations, `.env` changes, contract changes,
  or edits to user CAD documents were performed.

Governing documents: DECISIONS (ADR-019/021/031/032/034/035), existing
`docs/architecture/{local-folders,local-connections,code-environment}.md`,
`docs/api/API.md`, `docs/wireflows/{home,sources-connect-wizard,workspace,local-connections}.md`,
connector/bridge contracts, root and directory agent instructions. Added tier-1
API/wireflow supplements `document-tree.md`; amended platform availability docs.
The provider's global tree endpoint was verified live but is not documented in
its published OpenAPI; strict schema validation makes upstream drift explicit.

## Subsequent implementation and resolved prerequisites

- The user approved the concrete account-grant amendment, recorded in local commit
  `6fdff1c9`. Account-owned hosted OAuth/status/probe and shared grant handling are
  implemented; the backend reports **94 passing focused tests**.
- Account connection continues into hosted authorization in the same flow. Home
  offers recovery for existing connections, with bounded automatic subscription
  checks. Sign-out/unmount cancels stale callbacks. Focused lifecycle and UI tests
  pass; independent code/TypeScript and security reviews passed this hosted scope.
- The user authorized choosing any available document. `Draw Piece` was selected;
  its live feature/geometry identities were read without modifying vendor CAD.
  Import exposed an empty-assembly STEP translation failure. The fix now requires
  a schema-valid empty result at the immutable microversion and preserves malformed
  exports and real failures. Independent Python/code review passed **144 tests**
  across empty handling, connector and authoring suites. The second submission-400
  case also passed independent code/security review. Live retry succeeded: Home
  shows **connected · synced now · 3 entities** for the selected document.
- `uv run --no-sync --package solus-api python scripts/seed-provider-keys.py --only openai`
  successfully populated `openai_api_key` from existing configuration. No secret
  values were printed and no `.env` files were changed. A real SOL read request
  subsequently reached OpenAI embeddings and Responses successfully (HTTP 200).
  Its CAD tools refused the source while its sync status remained error; no CAD
  result or write was fabricated. The second empty-tab case (Part Studio translation
  request HTTP 400) is fixed. The subsequent SOL turn succeeded with live
  `list_elements`, `list_parts`, `get_feature_tree`, `get_mass_properties`,
  `get_part_bounds`, and `list_documents` tool results. It observed Part 1 / JJD,
  four features, bounds **146.05 × 1.50 × 57.15 mm**, and missing mass assignment
  (not a measured zero mass). No CAD modifications were made.
- A requested Extrude 1 depth preview exposed that `get_feature_tree` discarded
  live parameters and `get_feature_specs` returned no extrude parameters. SOL
  correctly refused to queue a proposal without verified depth. Reader corrections
  passed **46 operation tests** after reproducing the failures. The real proposal
  then reached the action gate, but preview fell back to argument rows because its
  feature lookup accepted legacy envelopes only. That inadequate card was rejected.
  Flat/legacy lookup and quantity-expression handling are corrected, with strict
  feature IDs and full parameter-collection validation. Final independent review:
  **94 reader/edit tests passed**, Ruff clean, security findings closed. The corrected
  live card now shows **document: Draw Piece** and **Extrude 1 · depth: 1.5 mm → 2 mm**.
  The user subsequently approved this card in the native app and confirmed the
  resulting depth is **2 mm**. SOL's independent readback returned the actual
  depth expression **2 mm**, part bounds **146.05 × 2.00 × 57.15 mm**, and parts
  microversion `080524ab6c33b2c5f3acfb5b`. The feature-tree result was still truncated,
  so its separate `sourceMicroversion` field was not independently verified.
- Full feature collections exceeded the model result cap. Exact feature/type reader
  filters are implemented so SOL can request complete parameters without truncation.
  Final independent verification: **112 reader/edit tests passed**, Ruff clean,
  mypy clean in the implementation pass; code/Python and security reviews passed.
- The account-hosted/tree/platform API regression batch passed **82 tests**.
  Remaining CAD operations and full Phase 1 completion are still pending; these
  scoped checks are not a claim that the entire API suite or write matrix passed.
- Added REST operations `list_parts`, `get_part_bounds`, and `insert_part` with
  tracked donor/target boundaries and independent insertion readback. **95 focused
  tests passed** before final security review; bounds schema validation then passed
  **29 authoring tests**. The refresh/revocation race was reproduced and fixed;
  dedicated security re-review passed. These are fixture checks, not live write proof.
- Additional governing supplements: `docs/api/account-hosted.md`,
  `docs/wireflows/account-hosted.md`, `docs/api/onshape-development.md`, and
  `docs/architecture/sol-in-tools.md`.

## Needs you before dependent work

1. **Resolved:** after services restarted, the real Home account row reports
   **FeatureScript ready**. The agent did not operate native consent; the account
   status endpoint returned successfully and the UI rendered its readiness.
   Hosted tool invocation and the complete zero-separate-enable-click journey still
   need live proof; status alone is not a successful tool-call claim.
2. **Resolved:** the user approved **Draw Piece / Extrude 1 depth: 1.5 mm → 2 mm**
   and confirmed the result. The agent never approves these gates itself.

## Follow-up corrections and next phases

- Approval-card polish passed 17 tests and independent code/TypeScript/security
  reviews. Before/After values stay visible; technical identifiers can collapse.
  The backend Guide refusal now says Build mode; internal wire values stay intact.
- Post-write graph-sync scheduling was missing. It now invalidates only the
  written document's signal and queues the existing background ingestion path
  with the deciding user. Five-second scheduling failures preserve the applied
  CAD result. **64 confirmation/sync tests passed**, types passed and independent
  code/Python/security reviews passed. This is not yet a live automatic-resync
  proof: the user's depth write preceded this fix.
- KiCad 10.0.6 is installed as Flatpak. A fresh empty scratch project was created
  at `tmp/integration-check-kicad/`; its initial empty ERC reported zero violations.
  Real library lookup and safe file-edit foundation passed independent security
  review and **53 tests**; native/Flatpak CLI detection brought the focused suite
  to **55 tests**. Drawing operations and live companion proof remain in progress.
- Isaac's built ARM runtime exists at
  `/home/beeboss/isaacsim/IsaacSim/_build/linux-aarch64/release/python.sh` and finds
  `isaacsim` (6.0.1-rc.7). ROS discovery currently shows no simulator topics and
  Foxglove port 8765 is not listening. No live simulation is claimed.
- ForgeTS remains untouched, with an existing unresolved conflict. A serial
  candidate exists at `/dev/ttyACM0`; its board identity has not been established.

Pending human inputs: link the QA workspace's local folder to the scratch KiCad
directory using native Solus Home → Local folder → Link folder; identify the exact
XIAO driver board; identify the board/device on `/dev/ttyACM0`. No physical-device
write has been attempted.

Zero-click hosted FeatureScript live completion, the SOL read/operate/write matrix,
sketch/cut, assembly mating and microversion graph resync remain unverified and are
not represented as finished. Remaining user-flow checklist:
`COWORK_QA_integration-check-phase1.md`.

## KiCad verification checkpoint — 2026-09-12 20:28 UTC

- Eight new owned tools are registered: library/geometry/ERC reads and confirmed
  schematic creation, symbol placement, wiring, labels and no-connect markers.
  Complete dry-run previews are mandatory before parking and again at approval.
  Missing previews cannot fall back to argument-only cards. Stable local refusals
  now become MCP failures. Independent security review passed after all findings
  were corrected.
- Integrated KiCad fork and companion suites: **687 passed, 1 existing xfailed**.
  Cloud bridge/allowlist/confirmation/Onshape write-sync suites: **96 passed**.
  Ruff passed for the KiCad overlay/tests and touched cloud gate modules.
- Restarted only the task-owned development stack. Its authenticated bridge
  advertises 24 total tools, including all 15 KiCad tools. Live SOL reads returned
  `Device:R` with 2 pins and `MCU_Module:Arduino_UNO_R3` with all 32 pins. The latter
  response is 3,784 JSON bytes and arrived without truncation.
- SOL's local scan still found no linked workspace. It correctly skipped
  `integration_check.kicad_sch`; schematic reads/writes through the project-bound
  companion, approval-card visual verification, complete circuit ERC and graph
  topology are still unverified. Native folder selection remains required.
- ERC checks a private schematic snapshot with CLI defaults; it does not apply
  external project-specific ERC configuration. Initial empty-sheet ERC is only
  baseline evidence, never a passing circuit claim.
- Pending design approvals: the exact ADR-014 amendment permitting gated external
  simulator control, and the closed tool-knowledge enum additions for code/Isaac.
  Existing Onshape/KiCad knowledge ingestion can proceed independently through
  the current guard after correcting the seed's vendor prose and KiCad10 range.
