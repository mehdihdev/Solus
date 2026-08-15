# Completion report — SOLUSDEV-206 (SOLUS-TU-03): visual-understanding path [RESEARCH-GRADE]

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Commit:** `c43e1aa`
**A spike, not a committed deliverable** (per the ticket) — sequenced last, blocks nothing.

## What was built

`packages/api/src/solus_api/toolkb/ingest/visual.py`:

- `parse_vision_output(raw)` — the **untrusted-output firewall** (CLAUDE.md §7): model output is
  parsed as a JSON array and every proposal must be well-shaped with a valid control-id slug, a
  0..1 locator box, and a unit-interval confidence, or it is dropped. Garbage/prose → `[]`, never
  an error.
- `ingest_visual_proposals(...)` — routes only **above-threshold** (`VISUAL_MIN_CONFIDENCE = 0.55`)
  proposals through the **guard's VISUAL path**, which (a) accepts ONLY controls already documented
  as vendor surface (`is_known_vendor_control`), so vision can **locate** known controls but never
  **introduce** knowledge, and (b) stamps every accepted proposal a low-confidence **CANDIDATE** —
  so **nothing vision produces is ever auto-promoted**; an operator must approve it. Below-threshold
  proposals are dropped before ingestion.
- `build_vision_extractor(...)` — wraps the **MO-01 gateway** (`complete(type=RouteType.VISUAL_LOG,
images=[...])`), never a parallel provider stack; keyless (as on this ARM64 host) → `[]` (no
  signal), mirroring `fingerprint/visual.py`.

## Acceptance (met, as a spike)

- A prototype labels controls from a screenshot with calibrated confidence; low-confidence items
  are dropped/held, **never auto-promoted** into the shared KB (structurally enforced by the guard,
  not by care). Routes through `RouteType.VISUAL_LOG`.
- The end-to-end VLM run needs a vision model key, which this host lacks, so the real extraction is
  exercised only via an injected fake model; the firewall + guard routing — the parts that decide
  what reaches the store — are what the tests pin. This is the honest boundary of a research spike.

## Tests

`tests/toolkb/test_visual.py` — firewall (valid parse, out-of-range locator, bad control-id slug,
confidence out of [0,1], garbage→empty), ingestion (only known controls ingested as candidates, the
undocumented one rejected by the guard, the visual candidate is never served/auto-promoted),
below-threshold drop. 7 tests; full toolkb suite 152 passed; mypy clean.

## Notes / follow-ups

- `visual.py`'s default `surface="toolbar"` / `effect="select"` are placeholders for the spike; a
  real vision path would infer these or leave the control's docs-sourced values authoritative and
  attach ONLY the locator. Deferred with the spike.
- Real-image evaluation (label a meaningful fraction of a tool's toolbar) needs a VLM key + a
  screenshot corpus — out of scope for this host; the pipeline is ready to run when both exist.
