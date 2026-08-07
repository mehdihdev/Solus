# Multimodal Fingerprint Output — Design Contract (SOLUS-W0-06)

**Status:** Design contract + a committed realistic **mock**. Ships the output shape, the
Pydantic models, this document, and `mock_canonical_parts.json`. The matcher that produces
this shape (FP-01/02) and the linking that consumes it (LNK-01) are separate tickets.
**Authority:** ADR-012 (fingerprint = weighted heuristics + human confirmation), ADR-001
(graph-centric), ADR-027 (`canonical_part_id` self-reference + `SAME_AS` edge), ADR-028
(Week-0 human-owned contract; the CTR-08 enum edit was human-approved in-chat per ADR-032
tier-2 handling). Code: `packages/api/src/solus_api/fingerprint/`.
Amended 2026-08-07 (CTR-08 — hardware-recognition modalities, §6 addendum + §6a).

Consumers — **the mock-and-swap seam.** Cross-domain linking (LNK-01, Mehdi) consumes this
output to connect cross-domain observations of one physical part (the op-amp in the
schematic, the op-amp referenced in code, the op-amp in CAD) to ONE canonical entity via
`graph_entity.canonical_part_id` + a `SAME_AS` edge. Linking must start **now**, before the
matcher (FP-01/02, Pratham) exists, so it builds against the committed mock
(`load_mock_output()`) today; the real matcher must later produce **exactly** this shape.
Therefore the shape is designed for the CONSUMER, and the mock is realistic enough (edge
cases included) that code built on it survives the swap to real data.

---

## 1. Purpose and the mock-and-swap seam

The multimodal fingerprint matches a single **physical part** observed across DIFFERENT
MODALITIES — its part number, datasheet, schematic symbol, CAD model, photo/silkscreen — to
ONE canonical part entity. This contract is the shape that grouping takes; it is **upstream**
of linking and of the graph write.

- **This module does not match anything and does not touch the graph.** It is data shapes +
  a mock only. Matching (FP-01/02) and the graph write of `canonical_part_id` / `SAME_AS`
  (LNK-01) are downstream tickets.
- **The seam:** `load_mock_output()` returns a fully-populated `FingerprintOutput` from the
  committed JSON. LNK-01 develops against it; when FP-01/02 lands, it is swapped in behind
  the same shape with no change to linking. **If the mock omits a hard case, linking built on
  it breaks on real data** — so the mock deliberately carries every edge case (§7).

---

## 2. The shapes

Pydantic v2 value objects, house style `ConfigDict(frozen=True, extra="forbid")`.

**`FingerprintOutput`** — the full matcher output: successful groupings PLUS explicit
unmatched/ambiguous, so the states are never inferred by absence.

| field             | meaning                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| `canonical_parts` | `list[CanonicalPart]` — successful groupings                                  |
| `unmatched`       | `list[SourceRef]` — observations the matcher could NOT confidently assign     |
| `ambiguous`       | `list[AmbiguousObservation]` — partially matched >1 part / between thresholds |

**`CanonicalPart`** — one physical part plus every modality matched to it.

| field           | meaning                                                                        |
| --------------- | ------------------------------------------------------------------------------ |
| `canonical_id`  | UUID — the canonical entity identity (maps to a `CANONICAL_PART` graph_entity) |
| `part_number`   | `str \| None`                                                                  |
| `manufacturer`  | `str \| None`                                                                  |
| `datasheet_ref` | `str \| None`                                                                  |
| `modalities`    | `list[ModalityMatch]` — the observations matched to this part                  |
| `confidence`    | `float` 0..1 — OVERALL confidence this grouping is correct (see §5)            |

**`ModalityMatch`** — one observation matched to a canonical part.

| field        | meaning                                                                                                                                                                                                          |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `modality`   | `Modality` (§6)                                                                                                                                                                                                  |
| `source_ref` | `SourceRef` — ties this match to a real `graph_entity` observation (§3)                                                                                                                                          |
| `confidence` | `float` 0..1 — how sure THIS observation is THIS part                                                                                                                                                            |
| `state`      | `MatchState`: `matched` \| `low_confidence` (§4)                                                                                                                                                                 |
| `evidence`   | `dict` — structured-but-flexible: WHAT matched and HOW, e.g. `{"matched_on": "part_number", "value": "LM358", "note": "exact string match"}`. For debugging and for SOL to later explain WHY things were linked. |

**`AmbiguousObservation`** — an observation that partially matched >1 part / fell between
thresholds.

| field                     | meaning                                               |
| ------------------------- | ----------------------------------------------------- |
| `source_ref`              | `SourceRef`                                           |
| `candidate_canonical_ids` | `list[UUID]` — the canonical parts it might belong to |
| `note`                    | `str \| None`                                         |

---

## 3. `SourceRef` — the resolution mechanism linking depends on

| field              | meaning                                                                     |
| ------------------ | --------------------------------------------------------------------------- |
| `graph_entity_id`  | `UUID \| None` — the observation's `graph_entity` id, if already ingested   |
| `source_connector` | `str \| None` — mirrors `graph_entity.source_connector`                     |
| `external_ref`     | `str \| None` — mirrors `graph_entity.external_ref` (id in the source tool) |

Linking uses `SourceRef` to map each modality match to the **specific** `graph_entity`
observation it corresponds to, so it can set `canonical_part_id` on that entity and/or create
the `SAME_AS` edge (ADR-027). The reference mirrors the graph's own provenance columns, so a
match resolves either by a known entity id or by the connector+tool-id pair a connector will
have written.

**Invariant (validated):** at least one of `graph_entity_id` OR (`source_connector` AND
`external_ref`) must be present, so every observation is resolvable. An all-`None` `SourceRef`
is rejected at construction.

---

## 4. The three states + ambiguous — how linking thresholds

The matcher emits FOUR dispositions, and linking reads them to set its own thresholds:

| disposition        | where it lives                                                   | linking's choice                     |
| ------------------ | ---------------------------------------------------------------- | ------------------------------------ |
| **MATCHED**        | a `ModalityMatch` in `CanonicalPart.modalities`, `state=matched` | link it                              |
| **LOW_CONFIDENCE** | a `ModalityMatch` in `modalities`, `state=low_confidence`        | include or exclude by policy         |
| **UNMATCHED**      | a `SourceRef` in `FingerprintOutput.unmatched`                   | keep as a separate entity            |
| **AMBIGUOUS**      | an `AmbiguousObservation` in `FingerprintOutput.ambiguous`       | defer / ask the user which candidate |

**UNMATCHED is not a `MatchState`.** It is represented explicitly at the top level (a
definitive `unmatched` list), never inferred from an observation's absence — so linking has a
concrete list to keep as separate entities rather than guessing.

---

## 5. Two-level confidence

Confidence is reported at TWO levels, and they are deliberately independent:

- **Per-`ModalityMatch.confidence`** — how sure THIS observation is THIS part.
- **Per-`CanonicalPart.confidence`** — how sure the OVERALL grouping is correct.

This lets linking **accept a part overall yet reject a shaky modality within it** (e.g. take
the canonical grouping but drop a `low_confidence` schematic match), or vice-versa. Both are
bounded 0..1 (validated).

---

## 6. Modalities

`Modality`: `part_number`, `datasheet`, `schematic_symbol`, `cad_model`, `photo`.

**`photo` is declared-but-optional.** It is in the enum and the shape carries it, but the v1
matcher does NOT populate it (visual/silkscreen matching is a later stretch). It is present so
the contract is stable when visual matching arrives — the mock includes a `photo` example to
prove the shape carries it, with an evidence note that v1 won't produce it.

> **§6 addendum — hardware-recognition modalities (2026-08-07, SOLUSDEV-136/CTR-08; enum
> edit human-approved in-chat; tier-1 amendment per ADR-032).** `Modality` gains three
> ADDITIVE members so robot-runtime hardware recognition carries evidence through THIS
> contract instead of a second identity mechanism: `bus_enumeration`, `firmware_symbol`,
> `telemetry_channel`. All three are **declared-but-unscored** in v1 — the same status
> `photo`/`cad_model` established: the shape carries them, and the v1 matcher routes any
> unscored modality to `unmatched` (`_V1_SCORED` fall-through in `matcher.py` — visible,
> never silently dropped). Evidence semantics + honest confidence bands (normative for the
> future runtime scorer; **doc-level for now — no `matching.yaml` weights exist because no
> scorer exists**; the scorer ticket MUST add the load-validated ceilings below, mirroring
> the existing `weights.photo < thresholds.matched` idiom):
>
> | modality            | band       | normative confidence | ceiling the scorer MUST load-validate                                                                                                                                                                                                                    |
> | ------------------- | ---------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
> | `bus_enumeration`   | **high**   | ~0.92                | ≤ `weights.exact_mpn`, < 1.0 — the device asserts its OWN identity (Dynamixel model register, CAN model ID); residual risk is a misflashed/spoofed ID. **May exceed `thresholds.matched`** — unlike photo, this is not inference.                        |
> | `firmware_symbol`   | **medium** | ~0.55                | < `thresholds.matched` — code intent can never assert physical identity; the firmware may be stale or wrong relative to the physical build (mirrors the datasheet ceiling).                                                                              |
> | `telemetry_channel` | **low**    | ~0.30                | < `thresholds.low_confidence` — a channel's shape (rate, range, units) constrains what a part _could_ be; it rarely identifies one. Telemetry corroborates, never attaches; alone it always lands `unmatched` or `ambiguous` (mirrors `generic_symbol`). |
>
> Propose-never-assert holds unchanged: even a MATCHED `bus_enumeration` identifies the
> PART, not which joint it drives — a wrong motor→joint link is the same catastrophe class
> as a false fingerprint merge, so linking still goes through LNK-01 MATCHED-only FK
> stamping and ADR-012 human confirmation. **The invariants of this contract are NOT
> modified by this addendum:** the `SourceRef` resolvability invariant (§3), the 0..1
> confidence bounds and two-level confidence (§5), the four explicit dispositions and
> UNMATCHED-not-a-`MatchState` (§4), the five original modality members and their semantics
> (§6), and `mock_canonical_parts.json` byte-identical. The hardware evidence fixture lives
> at `packages/api/tests/fixtures/hardware_modalities.json` (a bus-enumerated servo
> MATCHED, a firmware-inferred servo LOW_CONFIDENCE, and an ambiguous telemetry channel
> that provably links nothing — ambiguity stays visible).
>
> This contract is versioned by **dated amendments like this one**, not a schema-version
> field: none exists in the doc or on `FingerprintOutput`, and adding one would change the
> serialized shape for zero consumers.

---

## 6a. Canonical names — the one identity, its three names, and the names that do not exist

_(Added by the CTR-08 amendment above.)_ Hardware recognition (and every other consumer)
resolves observations through ONE identity value that deliberately carries three names —
ADR-027: "one value, three names":

| where          | name                        | role                                    |
| -------------- | --------------------------- | --------------------------------------- |
| connector emit | `EntityOut.source_key`      | what a connector calls the observation  |
| graph column   | `graph_entity.external_ref` | where the write seam stores it          |
| this contract  | `SourceRef.external_ref`    | how a match resolves back to the entity |

The write seam maps `source_key → external_ref`; a consumer holds `SourceRef.external_ref`,
the (`source_connector`, `external_ref`) pair, or `graph_entity_id` — nothing else.

**Names that do NOT exist — do not invent, alias, or shim them:**

- **`EntityOut.source_id`** — not a field. `graph_entity.source_id` exists but is the ORM
  FK to `sources` (connector-runtime provenance/idempotency plumbing), NOT identity.
  Reaching for "source_id" as an identity handle is the trap that produces a shim — and the
  shim is the second identity mechanism this contract exists to prevent.
- **A string-typed `source_ref`** — `ModalityMatch.source_ref` is an OBJECT of type
  `SourceRef` (`graph_entity_id` / `source_connector` / `external_ref`), never a bare
  string.

---

## 7. The mock fixture — `mock_canonical_parts.json`

A realistic `FingerprintOutput` with **10 canonical parts** (LM358, TL072, NE555, AMS1117,
MPU-6050, ATmega328P, STM32F103C8T6, LM7805, BME280, 74HC595), each with 2–3 modalities and
realistic confidences, realistic connectors (`kicad`/`onshape`/`github`) and refs (`U1`, an
Onshape part id, a photo path). Self-consistent UUIDs (`…-01xx` canonical, `…-02xx` entities)
so the ambiguous candidates reference real canonical ids. It bakes in every case linking must
handle:

| hard case linking must handle             | where in the mock                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------------- |
| Clean high-confidence match               | **LM358** — 3 modalities all `matched`, overall 0.98                                  |
| Low-confidence modality in a matched part | **NE555** — `schematic_symbol` `low_confidence` (0.55)                                |
| Partial disagreement across modalities    | **AMS1117** — part_number `AMS1117-3.3` vs schematic silk `AMS1117-5.0`, overall 0.70 |
| Photo modality (shape carries it)         | **MPU-6050** — a `photo` `ModalityMatch`                                              |
| Explicit unmatched observations           | `unmatched` — 2 `SourceRef`s (`kicad/U9`; an Onshape body)                            |
| Ambiguous between >1 canonical part       | `ambiguous` — a dual-op-amp symbol, candidates `[LM358, TL072]`                       |

`load_mock_output()` loads and validates it (the sibling `mock_canonical_parts.json`), the
same way `load_orchestration_config()` loads `models.yaml`.

---

## 8. Functional vs. future in W0-06

| Component                                                       | W0-06 status                   |
| --------------------------------------------------------------- | ------------------------------ |
| The shapes (`FingerprintOutput` + the five nested models)       | **Functional**                 |
| `SourceRef` resolvability invariant + `confidence` bounds       | **Functional (validated)**     |
| Committed mock covering all six hard cases + `load_mock_output` | **Functional**                 |
| The fingerprint matcher (FP-01/02) producing this shape         | **Separate ticket**            |
| Cross-domain linking (LNK-01) consuming it                      | **Separate ticket**            |
| `photo` modality populated by the matcher                       | **Future (visual matching)**   |
| Writing `canonical_part_id` / `SAME_AS` to the graph            | **Downstream (linking's job)** |

---

**Cross-references:** ADR-012 (fingerprint matching), ADR-001 (graph-centric), ADR-027
(`canonical_part_id` self-reference + `SAME_AS` edge; `graph_entity.source_connector` /
`external_ref` provenance), ADR-028 (human-owned contract). Code:
`packages/api/src/solus_api/fingerprint/` (`contract.py`, `mock_canonical_parts.json`).
Downstream: FP-01/02 (matcher — must produce this shape), LNK-01 (linking — consumes it and
writes the graph). Sibling contracts: `agent-tool.md`, `model-orchestration.md`.
