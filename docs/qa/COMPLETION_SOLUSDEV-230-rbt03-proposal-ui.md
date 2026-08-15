# Completion report — SOLUS-RBT-03 Proposed robot mapping + one-click confirmation (SOLUSDEV-230)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified (13 component tests;
722 desktop tests green).

## What was built — `widgets/livebench/recognition/`

- `RecognitionPanel.tsx` — the confirm surface: a proposal table with per-row honest
  confidence (`92% · bus-enumerated`, `55% · firmware`, `—` for unknown), expandable evidence
  (value + honesty note + provenance, e.g. `src/arm.ino:11`), **one-click Accept per row**,
  **Accept-all that only touches proposed rows and never unknowns**, one-click Reject, and an
  inline name+Save edit that costs exactly one interaction — rejecting/editing is as cheap as
  accepting. Decisions flow out through `onDecision(id, decision)`: the seam RBT-05's
  persistence consumes. Local state only — this ticket is the surface, not the store.
- `proposals.types.ts` — `MappingProposal`/`ProposalEvidence`/`Decision`: evidence-shaped rows
  mirroring the CTR-08 kinds.
- `proposals.constants.ts` — **fixtures for all four tiers**: (1) bus+firmware+repo
  near-automatic; (2) firmware-only inferred; (3) **bare serial, no repo — six unnamed
  channels the user names**, the primary product case; (4) ROS/URDF as a labeled bonus.

## Invariants proven in tests

- **No proposal is auto-accepted** — a 0.92 bus-enumerated row still renders `proposed` and
  `onDecision` fires only on user action.
- **Unknown renders explicitly unknown** with NO accept button; saving an empty name is a
  no-op (an unknown cannot be silently blanked in). Unlinked-in-graph enforcement lands with
  RBT-05's persistence (unknowns simply never produce an accept/edit decision to persist).
- Tier 3 flow: the user names a channel → `{kind: 'edit', functionName}` — confirm, not author.
- All four tiers render a usable screen.

## Notes for review

- No wireflow exists (flagged, as with LB-05); the table structure follows the ticket's
  acceptance list. Visual polish (hover-reveal vs click-reveal evidence) chosen as click for
  testability + touch friendliness — judgment noted.
- The panel is a component, not a second widget: it mounts inside the livebench widget's flow
  when the recognition path (RBT-01/02 output → proposals) is wired end-to-end with RBT-05.
