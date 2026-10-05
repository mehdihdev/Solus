# Completion report — KiCad integration completion

Branch: `SOLUSDEV-312-realtime-team-sync` (kept per the human; no KiCad ticket number was
given, so commits carry `SOLUSDEV-312:`). Nothing pushed. Governing docs: ADR-031/032/021,
`docs/architecture/change-signal-spine.md`, `docs/api/kicad-development.md`,
`docs/api/artifacts.md`, `docs/contracts/metadata-extraction.md`, the four prior KiCad QA
plans. Consolidated QA: `COWORK_QA_kicad-integration.md`. Test audit: `KICAD_TEST_AUDIT.md`.

## Criteria

| #   | Criterion                 | Status                                    | Evidence                                                                                                                                                                              |
| --- | ------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Install discovery         | Done                                      | `companion/kicad_discovery.py`, `test_kicad_discovery.py`; real run: companion-set `KICAD_CLI_PATH` → `official_kicadxml`, 9 components / 22 nets, not degraded (macOS, KiCad 10.0.1) |
| 2   | Portable tests            | Done on macOS                             | fork suite 451 pass (was 6 failing); `test_live_kicad_write.py` passes with KiCad, skips without. **Linux CI images not run**                                                         |
| 3   | File-pick ingestion       | Done                                      | `test_kicad_audit_file_pick_ingest.py`, `kicadFilesFixtures.test.ts`                                                                                                                  |
| 4   | Hostile input             | Done                                      | `test_kicad_audit_hostile_input.py` (16 hostile inputs + 1001-part)                                                                                                                   |
| 5   | Live export / artifacts   | Existing tests green; Redis budgets added | `test_bridge_artifacts.py`, `test_upload_budget.py`; **real bridge walkthrough not run**                                                                                              |
| 6   | Write path                | Existing tests green                      | `test_write_tool_*`, `test_live_kicad_write.py` (real KiCad round trip)                                                                                                               |
| 7   | Dev tools + change signal | Proven by test                            | `test_kicad_change_signal_graph.py` (frame → persisted topology; team B untouched). **Live desktop walkthrough not run**                                                              |
| 8   | Open-in-KiCad conflict    | Done                                      | guard already existed (`stale_plan`: changed fingerprint or `~name.lck`); now pinned by `test_write_tool_open_in_kicad.py`, documented                                                |
| 9   | Isolation/security        | Done                                      | `test_kicad_audit_isolation.py` (47), `test_kicad_audit_model_context.py`                                                                                                             |
| 10  | Cross-feature             | Done                        | `test_kicad_audit_cross_feature.py`, `test_outcome_and_rate_limit_events.py`                                                                                                                |
| 11  | SOL-100 follow-ups        | Done as approved                          | Redis budgets + eviction test; probe-timeout tests; `modality_hints` NOT exposed (no API doc defines it); worker seam + presigned S3 deferred by human                                |
| 12  | Docs                      | Done                                      | QA consolidated, old plans point to it, artifacts/kicad-development docs updated                                                                                                      |

## Decisions under delegated judgment / deviations

- Discovery sets `KICAD_CLI_PATH` in the companion's declared env; **no `solus/env.allow`,
  `bin/launch` or `allowlist.yaml` change** (the launcher already allows the variable, declared
  env wins over ambient) — so no PROVENANCE allowlist re-review trigger. Differs from the
  approved sketch, which also named an env.allow.
- Real bug fixed: `linking/linker.py` never retracted `same_as` links to soft-deleted parts.
- Review fix: Redis budget calls bounded by a 250 ms timeout (hung Redis stalled uploads).
- Missing KiCad: `extract_project_netlist` returns a clean tool error
  `authoritative_topology_unavailable: kicad-cli is unavailable` (existing behaviour); the
  "degraded" reason strings apply to the other export paths. Not changed.

## Open items for humans

1. ~~Data event gap~~ closed: `source.sync_succeeded`/`sync_failed`/`disconnected` and `rate_limit.exceeded` now emitted (no contract change; names documented in `docs/api/API.md`).
2. Fork tree hash in `PROVENANCE.md` must be re-signed (fork test files changed); both-devs
   signatures, allowlist ratification, push/MR remain human gates.
3. Linux CI images not verified; real desktop/bridge walkthroughs (QA §5, §7) need the Cowork pass.
4. Discovery covers only standard install paths (no Homebrew, Program Files (x86), Flatpak).
5. The 312 branch's Stop gate also fails on pre-existing Onshape/worker/webhook mypy errors.
6. Stale prose: `COWORK_QA_kicad-natural-ingestion.md` Flow 8 lists catalog `config_fields`
   without `project_path`.
