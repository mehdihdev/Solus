# LNK-09 — Integrations checkpoint gate (SOLUSDEV-114) — PREPARED, AWAITING SIGN-OFF

Prepared by LANE A (agent), 2026-08-08. **HUMAN GATE — both devs sign off; the agent
prepares and does not self-approve.**

## Acceptance status per integrations-stage ticket

| Ticket | Status | Evidence |
|---|---|---|
| LNK-03 ingestion | **Done (closed as built)** | `apply_sync_result` + `detect_changes` + worker (SOLUSDEV-103/104); Jira closed with rationale 2026-08-08 |
| LNK-06 telemetry plumbing | **Done, merged** | `graph/` package + 40 tests; LB-06 packet ratified (SOLUSDEV-126) and merged into the lane branch; Jira comment recommends human transition → Done |
| LNK-01 mock linking | **Done** | `linking/linker.py` + 15 tests; mock e2e (16 edges, 3 domains); completion report |
| LNK-02 real-FP swap | **Done** | swap at the data-source boundary only; 10 more tests; Phase-4 adversarial review: 6 findings confirmed & fixed |
| IMP-01 impact engine | **Done** | `impact/engine.py` atop `load_neighborhood`; 11 tests; hero-shaped ≥2-domain acceptance |
| IMP-02 consequences | **Done** | checker-backed provider + gateway narration w/ marked template fallback; 13 tests incl. §7 red team |
| LNK-08 integrations QA | **Done** | `test_integrations_stack.py`: 4 connector families ingest → FP → link → checkers on seeded bug → graph API returns linked result |

Full `packages/api` suite green in the lane worktree (see completion reports). The 15
"baseline red" tests from the pre-work H10 run were traced to an environment
misconfiguration (exported `VIRTUAL_ENV` pointing at the `/home/beeboss/Solus` worktree),
not code — `packages/api` is fully green under the correct venv.

## Deferred items (owner + date)

| Item | Owner | Target |
|---|---|---|
| **Altium fingerprint channel gap**: protel parser leaves `modality_hints` empty (comment → `properties.value` only), so Altium observations can never match/link. Pinned by `test_integrations_stack.py`. | LANE G (EDA) | next EDA ticket batch |
| LANE 0 partial unique index for source-less linker edges `(project_id, src_id, dst_id, relation_type) WHERE source_id IS NULL AND deleted_at IS NULL` (`models.py`/migrations are `@shared`) | LANE 0 | before multi-writer linking load |
| Extract one shared public fingerprint gather (`scan_project` + `link_from_fingerprint` currently mirror it; drift risk flagged in code) | LANE 0 | with the index ticket |
| Connector EDA attribute extraction (`checkers/attributes.py` keys) — until then checkers fire only on seeded/manual attrs | LANE G | per checkers roadmap |
| Impact HTTP route (`docs/api/API-implementation.md` §14, PLANNED) + live-gateway narration wiring | LANE A + LANE B | when the Impact widget goes live-data |
| CI lane-check branch-name mismatch: CODEOWNERS expects `SOLUSDEV-63-lane-graph`, worktree is on `SOLUSDEV-63-solus-graph` | humans | before MR |
| LB-06 packet promotion into `packages/contracts/` (ADR-032 tier-2, human approval) | humans | pre-Live-Bench |

## Live Bench prerequisites — confirmed ready

- Telemetry plumbing (LNK-06): shipped and merged; `TelemetryPlumbing.ingest` +
  W0-07 `get_telemetry` + bounded buffers; ratified LB-06 packet with msgpack codec and
  golden/hostile fixtures on this branch.
- Graph: unified store (Decision A), connector ingestion, fingerprint collapse, linker
  `same_as` edges, bounded subgraph read (`GET /projects/{id}/graph`) all live; impact
  engine consumes the same traversal.

## Go / no-go

**Prepared recommendation: GO**, with the deferred list above explicitly carried, not
silently pushed.

- [ ] Dev 1 (Pratham) — sign-off
- [ ] Dev 2 (Mehdi) — sign-off
- Decision recorded: ____ (go / no-go, date)
