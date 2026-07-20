# COWORK QA — FP-02 Fingerprint Ingestion (SOLUSDEV-59)

FP-02 is a **library layer** (no UI, no route, no background job yet — the trigger
router is a documented follow-on). QA runs through the test suite and a Python REPL.
Setup: repo on `SOLUSDEV-59-Multimodal-Fingerprint`, `uv sync`, **Postgres running**
(`make db-up`). No API keys needed anywhere.

---

## Flow 1 — Full FP-02 suite + migration reversibility

1. `uv run pytest packages/api/tests/test_ingest.py -q`
   - [ ] All 27 pass. (The session itself proves the migration applies to a fresh DB;
         `test_migration_downgrade_and_reupgrade` proves it reverses and reapplies.)
2. `uv run pytest packages/api/tests -q`
   - [ ] Full suite green — FP-01 and the W0-06 contract tests are untouched.

## Flow 2 — The acceptance walkthrough (match → ingest → resolve), REPL

From `packages/api/` with the dev DB up, in `uv run python` (asyncio REPL:
`python -m asyncio`):

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from solus_api.models import Team, Project, GraphEntity, Domain
from solus_api.fingerprint import scan_project, resolve, SourceRef

engine = create_async_engine("postgresql+asyncpg://solus:solus@localhost:5432/solus")
maker = async_sessionmaker(engine, expire_on_commit=False)
async with maker() as s:
    team = Team(name="QA"); s.add(team); await s.flush()
    project = Project(team_id=team.id, name="QA-FP02"); s.add(project); await s.flush()
    for ref, hints in [("U1", {"part_number": "LM358"}),
                       ("bom:3", {"part_number": "LM358DR"}),
                       ("sch:U1", {"schematic_symbol": "Amplifier_Operational:LM358"})]:
        s.add(GraphEntity(project_id=project.id, source_connector="kicad",
                          external_ref=ref, kind="component", domain=Domain.ELECTRICAL,
                          name=ref, modality_hints=hints))
    await s.flush()
    summary = await scan_project(s, project.id)
    print(summary)
    one = await resolve(s, SourceRef(source_connector="kicad", external_ref="U1"),
                        project_id=project.id)
    two = await resolve(s, SourceRef(source_connector="kicad", external_ref="bom:3"),
                        project_id=project.id)
    print(one.id == two.id, one.kind, one.canonical_key)
    await s.commit()
```

- [ ] `summary` shows `canonical_created=1, linked=3, embedded=0`.
- [ ] `one.id == two.id` is `True`; kind `canonical_part`; canonical_key `LM358`.
- [ ] The canonical row's `attrs["fingerprint"]["modalities"]` has 3 entries; its
      `origin` is `fingerprint`; `source_id`/`external_ref` are NULL; `embedding` NULL.

## Flow 3 — Precision at persistence

- [ ] In the Flow-2 session: every observation row has `canonical_part_id` set AND
      `attrs["fingerprint_link"]` (the ownership stamp).
- [ ] Add an entity with `modality_hints={"datasheet": "lm358.pdf"}` on a NEW
      external_ref (no part number), re-run `scan_project` → that row gets NO
      `canonical_part_id` (datasheet alone never asserts).
- [ ] Change U1's hints to `{"part_number": "TBD"}`, re-run scan →
      `summary.cleared == 1`, U1's FK is NULL and its stamp is gone (retraction);
      the other rows stay linked.
- [ ] Manually set `canonical_part_id` on a hint-less row (no stamp), re-run scan →
      it survives untouched (unstamped = human territory).

## Flow 4 — Idempotency & isolation

- [ ] Re-run `scan_project` twice with unchanged data → second `summary` shows
      `canonical_created=0, canonical_updated=0, cleared=0`; canonical row `version`
      unchanged (no-op run touches nothing).
- [ ] Create a second project with the same `LM358` hints, scan it → a SECOND
      canonical row (different id, same canonical_key). `resolve` with project A's id
      never returns project B's rows — try passing B's entity `graph_entity_id` in a
      SourceRef with A's `project_id` → `None`.

## Flow 5 — Keyless / embedder seam

- [ ] All above ran with no key and `embedding` stayed NULL — that IS Decision 3.
- [ ] Pass `embed=lambda text: [0.5]*1536` (as an async fn) to `scan_project` in a
      fresh project → `summary.embedded == 1`, canonical `embedding` non-NULL, and
      the SAME link outcomes as the keyless run.
- [ ] Pass an embedder that raises → scan still succeeds; embedding NULL.
- [ ] `grep -rn "SOLUS_FINGERPRINT_EMBEDDING_ENABLED\|fingerprint_embedding_enabled" packages/api/src` — flag exists, default False, zero library readers (caller-owned).
- [ ] `docs/api/gateway-embeddings.md` exists (the gateway extension proposal —
      folded from the root temp proposal file in SOLUSDEV-152; no provider
      code in `orchestration/` was touched:
      `git diff main -- packages/api/src/solus_api/orchestration/` is empty).

## Flow 6 — Frozen surfaces intact

- [ ] `git diff main -- packages/api/src/solus_api/fingerprint/contract.py packages/api/src/solus_api/fingerprint/matcher.py packages/api/src/solus_api/fingerprint/normalize.py packages/api/src/solus_api/fingerprint/matching.yaml packages/api/src/solus_api/fingerprint/mock_canonical_parts.json packages/api/tests/fixtures/fingerprint_labels.py` → EMPTY.
- [ ] `git diff main -- DECISIONS.md` → EMPTY (ADR-027 unamended).

## Known scope limits (not defects)

- No trigger: nothing runs `scan_project` automatically yet (router follow-on with
  Job + events + optional escalation identity).
- Embeddings stay NULL until the MO-01 gateway `embed()` extension is approved/built.
- A soft-deleted canonical would leave observation FKs pointing at a tombstone
  (lifecycle follow-on; nothing soft-deletes canonicals today).
- `manufacturer` is never populated (no connector sources it) — recorded as None.
