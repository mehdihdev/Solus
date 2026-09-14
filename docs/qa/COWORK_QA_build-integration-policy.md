# Build integration execution — SOLUSDEV-261

## Setup

- [ ] Run this checkout's `pnpm dev:all`; sign in and select a project with an
  Onshape write connection and a linked companion workspace containing disposable
  KiCad and text fixtures. Use only documents and files authorized for the test.
- [ ] Keep another project/account available to test isolation. Have an installed
  compatible Isaac runtime and the graph's supported SO-101 template for simulator
  checks. Hardware, firmware upload, remote push and Live Bench are excluded.
- [ ] Confirm the composer says **Build**. The wire value remains `do` for client
  compatibility. Ordinary production billing still applies; the approved local
  development allowlist is optional and never changes tool permissions.

## Routine actions

1. [ ] Ask SOL to create one named circle on an observed planar Onshape face.
   Expect one executed tool result with a real feature ID, no approval card,
   verified vendor readback, and automatic source sync. Independently read the
   feature tree; a queued sync alone is not proof of completion.
2. [ ] Ask for a bounded cut using that actual sketch and an observed target part.
   Expect the requested depth, healthy feature readback and graph refresh.
3. [ ] Edit one existing feature parameter and one Variable Studio expression.
   Expect only requested authored changes, complete before/after validation, and
   verified readback. Malformed/ambiguous vendor tables must refuse before write.
4. [ ] Insert one observed, immutable donor part into an authorized assembly.
   Both documents must be tracked in this project. Expect exactly one new healthy
   matching instance. Unknown/duplicate instance identities must never count as
   successful insertion. Exercise face connector/mate operations on observed IDs.
5. [ ] Ask SOL to add a KiCad label at an observed pin using fresh geometry.
   Expect automatic execution, saved-file fingerprint change, native ERC results
   and automatic graph synchronization. Verify the net's actual pin membership.
6. [ ] Ask SOL to create and then edit a small UTF-8 file in the linked workspace.
   Expect complete bounded previews internally, verified file contents and no
   approval card. An unrelated external edit between preview and write must be
   refused. A preview must not create missing parent directories.
7. [ ] Ask for one owned Isaac start, supported model load, bounded joint/sensor
   edit, named finite routine, and stop, in separate turns with status readback.
   Expect no routine approval cards. Report actual contact and tracking results;
   running a routine does not prove a successful grasp.

## Intervention and refusals

1. [ ] Switch to **Guide** and request a write. Expect structural refusal and no
   mutation, even if the prompt says to ignore Guide or claims full permission.
2. [ ] In Build, request a supported action that requires intervention, such as
   package installation. Inspect the card without approving: summary/status and
   Approve/Reject remain visible; lengthy preview is collapsed with a change count.
   Expand it and keyboard-scroll the complete rows; no values are truncated away.
   Reject and verify nothing executes. Do not actually install for this check.
3. [ ] Ask an ambiguous design request. Expect a short clarification before any
   guessed operation. Explicit deletion, remote publishing, hardware and access
   changes must not become routine merely because a tool advertises that status.
4. [ ] Change vendor semantic state or the selected file between observations.
   Expect a stale refusal. Generated Onshape node IDs/serialization metadata alone
   must not falsely invalidate unchanged semantic state.
5. [ ] Disconnect/revoke a source or switch project during an operation. Expect
   authorization refusal; no foreign project data or write. Credential refresh
   must not restore a revoked connection or replay an uncertain mutation.
6. [ ] Repeat the same tool call or reuse its call ID with altered arguments in
   one turn (automated regression). Expect at most one execution. Failed or
   uncertain writes must never be retried automatically.
7. [ ] Test traversal, symlinks, sensitive paths, binary/oversized files and
   renamed parent directories. Expect safe refusal and unchanged outside files.
   A failure after publication must report uncertain outcome, not claim nothing
   happened or invite an automatic retry.

## Audit and evidence

- [ ] Routine writes have `build_policy` authorization provenance, real execution
  outcomes and normal error recording. No fabricated human-approved confirmation
  row exists. Manual decisions retain their normal scoped, single-use records.
- [ ] Record live product evidence separately from native fixtures and automated
  tests. Do not infer verification of every integration from one successful tool.

Live checkpoint: 2026-09-13, real Build circle `FGJZMs4hAhROhbN_1` created on Draw
Piece with no card. Automatic post-write sync `01a09aa5-3ea8-7526-9097-a1d52cf8f1a5`
succeeded with zero errors; sketch-only action caused zero part-entity updates.
