# Completion Report — FP-Fixes + FP-03 Vision Scaffold (SOLUSDEV-59)

Eight commits on `SOLUSDEV-59-Multimodal-Fingerprint` after FP-02's handoff:
FP-fixes (1 + the H6 cleanup), FP-03 (4 + a lint follow-up), and the Phase 4
review fixes (1). Full suite 804 passed / 3 pre-existing skips; mypy --strict +
ruff clean; the eval hard gate is ZERO false merges (35 cases, 21 confusable):

```
FP-01 eval: cases=35 (matched=14 confusable=21)
pair_precision=1.000  pair_recall=1.000  bucket_accuracy=1.000
FALSE MERGES: 0   (hard gate: 0 required)
```

## FP-fixes

### The generalized rule (encoded in matching.yaml + fixture headers)

"Strip ONLY what leaves the part electrically DROP-IN (package, temp, performance
grade — recorded as evidence). NEVER strip what changes FUNCTION or CAPABILITY
(voltage variant, memory/flash code, die revision)." Suffix meaning is STEM-scoped.
Every taxonomy addition needs domain review + a confusable case.

### Taxonomy diff (what became non-strippable and why)

- **Nordic (A1)**: nothing was strippable (no nRF family has ever existed) — now
  DOCUMENTED as never-strippable (QFAA/QFAB encode 512K/64K vs 256K/32K flash/RAM =
  capability = identity) and PINNED by new hard-gate case C20 (plus the C7 note:
  52832 ≠ 52840, model digits are identity).
- **STM32 (A2)**: the enumerated [T6..R7] suffix list became the positional
  `suffix_pattern "[HKRTUVY][367]"` — a new `FamilyRule.suffix_pattern` mechanism
  (named-group combined stem+suffix fullmatch, compiled+validated at load,
  empty-matching patterns rejected). The stem keeps pin-count AND flash size
  (C8 ≠ CB, pinned by C13); an unrecognized tail strips NOTHING. K/V/Y added from
  ST's documented package letters; P (TSSOP) deliberately deferred until pinned.
- Everything else unchanged; ti_linear/ti_jfet B-split re-confirmed (M14/C18).

### The three separator-policy proofs (all pinned in the eval)

Separators are typography: the final base is de-hyphenated AFTER decomposition
(hyphen_suffixes intact) and must RE-PASS the plausibility gate:

1. `MPU-6050` ≡ `MPU6050` — one part (M5, now merged).
2. `AMS1117-3.3` → base `AMS11173.3` ≠ `AMS11175.0` — voltage tokens survive (C9).
3. `AMS1117` ≠ `AMS1117-3.3` — bare stem is a third identity (new C19); report
   note: a bare AMS1117 in a schematic is arguably an "underspecified part" signal
   worth surfacing later.
   Re-gate proof: `10-K`/`4-K7`/`100-PF` de-hyphenate into passive values and die at
   the gate (tested). Base re-spelling re-keys uuid5/canonical_key for MPU/AMS parts —
   dev-only data, documented in the staged ADR amendment.

### Ledger CLOSED (all adjudications applied as labeled)

Second-source merge with manufacturer evidence (M6); datasheet-alone UNMATCHED with
filename extraction still yielding candidates (C3/C11 — extraction ≠ evidence);
B-split holds (M14/C18); and this round's four: C2 ambiguous, C4 unmatched (mock
stays a shape demo), C5 distinct (alternates belong to a future curated feature),
C14 unmatched (part_number fields are never mined). Every `debatable=` now carries a
human adjudication date; new judgment calls get new entries.

### Vocabulary + hook

- `temp-ADR-027-origin-fingerprint.md` (repo root) — the staged Decision C
  amendment blessing `origin="fingerprint"`, in Decision-A format, ready to paste
  into DECISIONS.md. Human steps: paste it; **Mehdi's ADR-028 sign-off on the
  models.py canonical_key edit** remains open from FP-02.
- **H6 fixed and verified**: the human applied the one-line `*/migrations/*`
  exemption (mirroring H9); verified by pipe simulation (exit 0) and a live
  throwaway migration Write that H6 no longer blocks. The temp patch file was
  deleted after application.

## FP-03 — vision scaffold (STRETCH, flag off by default)

### The reframing, enforced structurally

The vision model is an EXTRACTOR: it returns literal marking strings that flow
through the deterministic normalizer/matcher as PHOTO observations. Containment:

1. **Capped**: `weights.photo (0.55) < thresholds.matched` is load-validated — a
   photo match can only ever be LOW_CONFIDENCE, so FP-02's MATCHED-only gate never
   sets `canonical_part_id` from a photo (proven end-to-end in test_ingest).
2. **Never mints**: `_score_photos` intersects readings with part-number member
   bases ONLY (never seeded, never entity-own, never seeds) — a photo with no
   existing part to corroborate contributes nothing.
3. **Never alters**: the photo pass runs last and only appends; structured scoring
   is untouched by construction. Bit-identical eval on/off holds trivially (zero
   photo observations in the fixture) and the real gate is the corpus-wide
   red team: an adversarial extractor reading "LM358" for EVERY image leaves
   structured buckets identical, mints nothing, and any attach is
   PHOTO+LOW_CONFIDENCE (`test_adversarial_photo_cannot_change_structured_buckets`).

### Gateway vision extension (in-ticket, not its own ticket — rationale)

`ImageBlock{media_type, data: bytes}` + `images:` threaded
complete()→stream()→dispatch→`ProviderAdapter.stream`, with per-adapter content
builders as testable pure functions (Anthropic base64 source blocks, OpenAI
data-URL image_url, Gemini Part.from_bytes). ~55 source lines, images-absent path
byte-identical (regression-tested), SDK-import ratchet untouched, routing untouched
(visual.py passes `type=VISUAL_LOG` explicitly). It becomes its own ticket the
moment scope grows to artifact byte-fetching, image preprocessing, image token
estimation, or multi-turn vision — **the ArtifactRef byte-fetch remains deferred
(W0-04)**: visual.py accepts bytes / local Path from trusted callers only; ALL
ArtifactRef storages are warn+inert (hardened in Phase 4 — finding 2 below).

### Extractor prompt + client discipline

Extraction-only prompt (literal characters, EVERY plausible reading, ≤8, JSON
array, "[] if nothing legible", image content de-authorized as instructions);
magic-byte sniffing (PNG/JPEG/WebP — sniff authoritative, no pillow), 5MB cap with
pre-read size checks; strict parse with a per-candidate MPN-charset firewall,
dedupe-by-max-confidence; ANY failure (unreadable image, model error, parse
surprise, missing key) returns [] — keyless inertness is proven through the REAL
gateway with an empty SecretStore (no network). Identity required (ADR-018): vision
runs only from the future authenticated trigger router, gated by
`SOLUS_FINGERPRINT_VISION_ENABLED` (default off, caller-read). No committed photo
files: tests mock the extractor; the manual-demo two-liner is in visual.py's
docstring (needs `google_api_key`).

## Phase 4 verification

A 5-lens adversarially-verified review workflow (21 agents: taxonomy-domain,
security §7 incl. the new image surface, spec-compliance vs both verify lists,
python, gateway-chokepoint; every finding refuted by a 3-vote adversarial panel)
ran over the integrated FP-fixes + FP-03 diff. Four findings survived; all four
are fixed and pinned by tests:

1. **CRITICAL (taxonomy) — de-hyphenation could MINT a taxonomy-known identity.**
   `LM358-8` de-hyphenated to `LM3588` (a real, DISTINCT boost-converter part)
   and MATCHED it at 0.95; same shape for `ATMEGA328-P` → `ATMEGA328P`. Fix: a
   collision guard in `_strip_separators` — if the de-hyphenated form fullmatches
   any taxonomy family stem OR decomposes under the taxonomy, the hyphenated base
   is kept whole (a hyphen is only typography when removing it lands on nothing
   we know). The adjudicated merges are unaffected: MPU6050 / NRF52832QFAA match
   no family. Pinned by new hard-gate case **C21-lm358-8-vs-lm3588** (cases
   34→35) and `test_dehyphenation_never_mints_a_known_identity`.
2. **HIGH (§7) — ArtifactRef LOCAL uri was a path-traversal / cross-tenant
   exfiltration hazard.** Resolving a metadata-carried `file://` uri to a
   filesystem read would let a crafted traversal/symlink uri read arbitrary
   files — another tenant's images included — and ship their bytes to a provider.
   Fix: ALL ArtifactRef storages are now inert (warn + no-signal) until the
   team-scoped, artifact_id-based byte-fetch exists (W0-04); trusted callers pass
   bytes/Path directly. Pinned by `test_all_artifact_refs_are_inert`
   (traversal / local / s3 refs → `[]`, zero gateway calls).
3. **MEDIUM (ledger) — adjudication markers incomplete.** M7 still carried an
   open "adjudicate together with C9" imperative after that adjudication closed;
   several closed cases lacked dated markers. Fix: M7 rewritten as
   adjudicated-by-the-generalized-rule; dated markers added to M14/C8/C12/C15/C18.
4. **MEDIUM (gateway) — the Gemini content path, the ONE provider VISUAL_LOG
   actually routes to, was the only untested content builder.** Fix: extracted
   `gemini_contents(query, images, types_module)` as a pure function (SDK types
   module injected, keeping the import ratchet intact) with stub-based tests for
   the bare-string and Part.from_bytes shapes.

Post-fix gate: 804 passed / 3 skipped, mypy --strict + ruff clean, hard gate
ZERO false merges on 35 cases.

**Known flake (pre-existing, NOT this ticket):**
`test_sources.py::test_disconnect_cascades_entities_by_default` failed once
(404) during an H10 gate run mid-ticket; it passes 3× in isolation, 10/10
in-file, and the full suite has been green on every run since. The files
involved were last touched in SOLUSDEV-102. Flagged for a look, not papered
over.

## Human steps

1. Paste `temp-ADR-027-origin-fingerprint.md` into DECISIONS.md (ADR-027, after
   Decision A); delete the temp file.
2. Mehdi: ADR-028 second-founder sign-off on the FP-02 `models.py` edit.
3. Adjudicate the gateway-embeddings proposal (still pending from FP-02).
   _Resolved in SOLUSDEV-152: accepted in principle, folded into
   `docs/api/gateway-embeddings.md`; implementation deferred to MO-01._
4. Review both prior completion reports if not yet done; then push + MR.
