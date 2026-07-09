# COWORK_QA — Altium Connector (SOLUSDEV-102, SOLUS-EDA-03)

End-to-end test plan for the Altium connector. v1 **parses a committed Altium
export** (Protel netlist) into the shared electrical graph shape — components +
first-class nets + `connected_to` relations — mirroring the EDA family. The
proprietary/live acquisition path is a **clearly-marked scaffold** (deferred to
post-launch); v1 receives the export CONTENT via config.

Because live acquisition is stubbed, this connector is exercised at the
**library/interface level** (its parser, mapping, and W0-05 interface), not yet
through a running "connect a live Altium source in the UI" flow. The checklist
below reflects that boundary.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Required setup state

- Python backend deps installed (`uv sync` in `packages/api`).
- No DB, network, or credentials required — the connector is a pure file-parse
  unit at this stage (auth_kind = `none`).
- A sample committed Protel netlist (one is embedded in the test suite;
  `tests/test_altium_connector.py::PROTEL_EXPORT`).

---

## Flow 1 — Parse a committed Protel netlist (the core path)

Run: `cd packages/api && uv run pytest tests/test_altium_connector.py -v`

1. **Components become `component` entities.**
   - [ ] Each `[ … ]` block → one `EntityOut(type="component")` keyed by its
         reference designator (`U1`, `R1`, `C1`), `domain=electrical`, with
         `footprint`/`value` in `properties`.
2. **Nets become first-class `net` entities.**
   - [ ] Each `( … )` block → one `EntityOut(type="net")` keyed `net:<NAME>`
         (`net:VCC`, `net:GND`, `net:SIGNAL`).
3. **Connectivity becomes intra-source `connected_to` edges.**
   - [ ] Each component on a net → ONE `RelationOut(type="connected_to")` from the
         component to the net, carrying ALL its pins on that net in
         `properties.pins` (`{net, pins:[…]}`). A multi-pin part (multi-VCC/GND
         IC) is a single edge, not one-edge-per-pin.
   - [ ] Both ends of every relation are entities the connector produced
         (intra-source invariant).
4. **All source_keys are unique**; components and nets never collide (nets are
   namespaced with `net:`). [ ]

## Flow 2 — Conformance suite

Run: `uv run pytest tests/test_altium_connector.py::test_passes_connector_conformance_suite -v`

- [ ] `AltiumConnector` passes `assert_connector_contract` (unique source_keys,
      intra-source relations, `validate_credentials` → `AccountInfo`, `sync` →
      `SyncResult`, JSON-round-trippable cursor, `detect_changes` → bool).

## Flow 3 — Change detection (re-parse-and-diff)

- [ ] `detect_changes` returns **False** when the export content hash matches the
      stored cursor (`content_sha`).
- [ ] Returns **True** when the export content changes.
- [ ] Returns **True** (fail-safe) when the export is unavailable, so a full sync
      decides.

## Flow 4 — Identity

- [ ] `validate_credentials` returns a synthetic `AccountInfo`
      (`login="altium-export"`) — a committed export needs no tool credential.

## Flow 5 — Scaffold boundary (the deferred live path)

- [ ] Calling `sync` with **no** `config["export"]` raises
      `ConnectorError(code="export_unavailable")` with a clear message that live
      repo/tool acquisition is not yet implemented — i.e. the scaffold is explicit,
      not a silent empty result.

## Flow 6 — Registry / catalog

Run: `uv run pytest tests/test_registry.py -v`

- [ ] `build_registry` lists `altium` alongside `github`/`gitlab`.
- [ ] The catalog entry shows `auth_kind="none"`, `config_fields=["export"]`.

## Edge cases & failure paths (security §7 / §9)

Run: `uv run pytest tests/test_eda.py tests/test_protel_netlist.py -v`

- [ ] **Malformed node lines** (no `Designator-Pin` dash) are skipped, not fatal.
- [ ] **Unterminated blocks** (missing `]`/`)`) are ignored without raising.
- [ ] **Orphan nodes** (net references an unknown component) are dropped with a
      `SyncError`, and no dangling relation is emitted.
- [ ] **Duplicate designators / net names** are deduped with a `SyncError`
      (keeps source_keys unique).
- [ ] **Oversized export** (> `MAX_EXPORT_BYTES`) is refused
      (`ConnectorError code="export_too_large"`) before parsing.
- [ ] **Non-text export** is refused (`code="export_invalid"`).
- [ ] Parsing performs **no** eval/exec/subprocess and treats content strictly as
      data.

## v1 limitations to confirm are documented (not bugs)

- [ ] Only the **Protel netlist** format is parsed; SPICE/orcadpcb2 Altium exports
      are a documented later extension.
- [ ] Stock Protel has **no native MPN**, so `modality_hints.part_number` is empty
      in v1 (W0-08 §5.4) — the fingerprint supply-chain channel is intentionally
      unpopulated until a comment-field/ActiveBOM mapping is added.
- [ ] **Live acquisition** (fetch the committed export from the linked repo at a
      ref / direct Altium integration) is a scaffolded post-launch stub.

## Cross-feature interactions (design intent, not yet wired)

- [ ] Entities carry `source_key` == the graph `external_ref` the fingerprint
      (W0-06) and linking (LNK-01) will read — confirmed by shape, exercised once
      ingestion + fingerprint land.
- [ ] The EDA family base (`eda.py`) is the seam KiCad / SPICE connectors will
      reuse (same IR + mapping + scaffold) — confirm no Altium-specific logic leaked
      into `eda.py`.
