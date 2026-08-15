# Completion report — SOLUS-RBT-05 Persist the confirmed robot via the fingerprint seam (SOLUSDEV-232)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified against the real test
database through the real FP-02 ingest path. The Phase-0 hard blocker (CTR-08) was confirmed
cleared in code before work began.

## What was built — `packages/api/src/solus_api/livebench/persist.py`

- `persist_confirmed_robot` — RBT-03 confirmations (`ConfirmedMapping`: part number,
  function name, upstream RBT-01/02/04 `ModalityMatch` evidence) → a `FingerprintOutput` →
  **FP-02's `ingest_output`**. Same `kind="canonical_part"` rows, same
  `(project_id, canonical_key)` idempotency, same attrs evidence layout, same
  `canonical_uuid`. **No new identity type, no new table, no new column** (pinned by a test
  that inspects the module's imports and rejects any table definition).
- **The user's confirmation rides the seam as evidence**: a `ModalityMatch` with
  `matched_on: user_confirmation` and the confirmed function name at 0.98 (high, never 1.0 —
  a user can be wrong). SOL's "why is this the elbow" finds the decision beside the wire
  evidence.
- **Honesty boundaries, tested**: a tier-3 confirmation with no part identity is REPORTED
  (`skipped_no_part_identity`), never persisted under an invented part number (fabricated
  keys merge distinct hardware — the false-merge catastrophe class). Unconfirmed/ambiguous
  flow through as FP-02 `unmatched`/`ambiguous` — explicitly unlinked.
- `recognize_robot` — reconnect: freshly observed bus identities (`external_ref →
  part_number`) vs the persisted evidence map. Exact match → recognized, **no
  re-confirmation**; a changed part at a known address, a new device, or a missing device →
  a named diff (`changed/added/missing`) for RBT-03 to **re-propose — never silently kept**.

## Verification

8 integration tests (real Postgres, real ingest): one-canonical-per-part with all three
modalities reconciled, idempotent re-persist, part-less honesty, unlinked unconfirmed,
recognized reconnect, changed-config re-proposal, missing-hardware naming, and the
no-parallel-identity review guard. FP-02 regression (`test_ingest.py`,
`test_fingerprint_hardware_modalities.py`) + bench routes: 51 tests green together.
mypy strict + ruff clean. TDD RED→GREEN.

## Notes for review

- Cross-modality reconciliation happens exactly where FP-02 put it: same part number →
  same canonical row; the persist adapter adds nothing but the confirmation evidence.
- The motor→JOINT graph relation (canonical part → joint entity edge) remains LNK-01
  MATCHED-only stamping territory per the CTR-08 fixture's own note; the confirmed function
  name is recorded on the canonical entity's evidence, ready for that link.
- Tier-3 label persistence for part-less channels is intentionally out: it needs an entity-
  attrs path (LNK), not an identity path — flagged, not smuggled in.
