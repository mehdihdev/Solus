# COWORK QA — KiCad integration (consolidated)

Supersedes `COWORK_QA_kicad-connector.md`, `COWORK_QA_kicad-natural-ingestion.md`,
`COWORK_QA_kicad-mcp.md` and `COWORK_QA_kicad-development.md` (kept in place with
detail; this file is the single pass/fail checklist). Automated evidence per item:
`docs/qa/COMPLETION_KICAD_COMPLETE.md` and `docs/qa/KICAD_TEST_AUDIT.md`.

Mark each box PASS / FAIL with a note. Do not mark an unrun step as passed.

## 0. Setup

- [ ] Docker running; `make db-up`; then `pnpm dev:all` (API, worker, companion, desktop).
- [ ] Two users in DIFFERENT teams, each with a project: A (`<TOKEN>`, `<PROJECT_A>`),
      B (`<TOKEN_B>`, `<PROJECT_B>`).
- [ ] KiCad 8/9/10 installed in the standard location (macOS
      `/Applications/KiCad/KiCad.app`; Linux `/usr/bin/kicad-cli`; Windows
      `C:\Program Files\KiCad\<ver>\bin`). A second pass WITHOUT KiCad is in §2.
- [ ] Sample files (all committed):
      `integrations/mcp/kicad/tests/fixtures/solus_sample/` → `solus_sample.net.xml`,
      `.kicad_sch`, `.kicad_pro`; `packages/api/tests/fixtures/solus_sample.net` (S-expr).
      Counts for `solus_sample`: **9 components, 22 nets** (XML and S-expr agree).
      Small design (`KICAD_XML`/`KICAD_SEXPR`/`KICAD_PCB` in
      `packages/api/tests/fixtures/kicad_sample.py`): U1, R1, C1 on VCC/GND/SIGNAL; the
      board adds mounting hole H1 and fiducial FID1 (board alone = 5 components, 3 nets).
      Write them out with
      `uv run python -c "import sys; sys.path.insert(0,'packages/api/tests'); from fixtures.kicad_sample import KICAD_PCB, KICAD_SEXPR; open('sample.kicad_pcb','w').write(KICAD_PCB); open('sample.net','w').write(KICAD_SEXPR)"`.

## 1. Install discovery (new)

- [ ] With KiCad installed, link the local folder containing `solus_sample.kicad_pro`
      (Home → Local folder → Link folder). Companion reports KiCad ready with no env setup.
- [ ] Sync the local KiCad source: export is native (result not marked degraded).
- [ ] Set a hostile `PATH`/`KICAD_CLI_PATH` in the shell that launches the companion
      (pointing at a script that writes a marker file). After a sync the marker file does
      NOT exist (ambient env is ignored).

## 2. Degraded path (no KiCad)

- [ ] Temporarily rename the KiCad install (or use a machine without it). Sync still
      succeeds with `degraded: true` and the reason
      `kicad-cli unavailable (headless posture): kicadxml synthesized from the KiCad-free schematic file parse`.
- [ ] Restore KiCad; next sync is not degraded.

## 3. File-pick ingestion (onboarding "Connect your tools" → KiCad)

- [ ] XML netlist alone → 9 components / 22 nets. Entities visible in Graph/BOM.
- [ ] Default S-expression `.net` alone → identical pin connectivity to the XML.
- [ ] `.kicad_pcb` alone → 5 components, 3 nets; H1/FID1 have no edges.
- [ ] Netlist + board together → reconciled; board adds `layer`; mismatched pair
      shows a `board/netlist mismatch` error and does not corrupt the graph.
- [ ] Re-sync unchanged file → no creates/updates/deletes. Edit a part (change a value,
      remove one part, add one) and re-sync → exact create/update/delete counts; removed
      part's fingerprint link is retracted (no dangling `same_as`).
- [ ] Picking `.kicad_sch` or `.kicad_pro`: refused INSTANTLY in the UI with guidance
      (how to export a netlist). Same file POSTed to the API directly: a failed sync with
      guidance, and the previous good graph is intact.

## 4. Hostile input

For each, expect a clean, bounded error (`export_invalid`/422), nothing ingested, API
and worker still up, and the same source recovers on the next valid file:

- [ ] > 7 MiB file; deeply nested S-expression (200k parens); NUL/control characters.
- [ ] XML with DTD, external entity, parameter entity, billion-laughs.
- [ ] Truncated/unterminated file.
- [ ] The 1001-part netlist syncs with zero errors; re-sync is a no-op.
- [ ] `solus_sample_hostile.net.xml` (instruction text in fields): ingests as plain data;
      ask SOL about the part — it does not follow the embedded instructions or change tools.

## 5. Live export over the bridge

- [ ] Companion connected: sync acquires a FRESH export (edit the schematic, save,
      sync → change shows without re-picking a file).
- [ ] Stop the companion: sync degrades cleanly (falls back to committed export), no
      500s, source status reflects it.
- [ ] Artifacts (`docs/api/artifacts.md`): upload accepted; a second fetch of a
      consumed artifact is refused (single use); an expired artifact is refused; >N rapid
      uploads get 429 (budget is shared across API instances via Redis; stop Redis and
      uploads still work with the in-memory limiter).

## 6. Write path (MPN edit)

- [ ] Ask SOL to set R1's `MPN`. It proposes an approval card with before/after; NOTHING
      is written until you approve. Declining leaves the file byte-identical.
- [ ] Approve → only the one property value's bytes change (diff the file).
- [ ] A value with control characters or >64 KiB is refused; file untouched.

## 7. Development tools (read → propose → approve → ERC → commit)

- [ ] Real `kicad-cli` on this OS: geometry/library reads work; ERC runs and reports.
- [ ] Place → wire → label via approval cards; each requires explicit approval.
- [ ] Commit: file written once, verified by read-back.
- [ ] After approval, the companion change signal fires and the persisted graph
      topology updates automatically with no manual sync (new net/edge appears).
- [ ] Team B's sources/graph are untouched by A's change (see §9).

## 8. Open-in-KiCad conflict

- [ ] Open the schematic in the KiCad GUI (creates `~<name>.kicad_sch.lck`). Approve a
      Solus edit → refused with `stale_plan`/"file is open or changed"; file untouched.
- [ ] Close KiCad; re-read; the same edit now succeeds.
- [ ] Save the file from KiCad AFTER Solus read it, then approve a Solus edit → refused
      (changed since read); Solus never overwrites the GUI save.

## 9. Isolation and security

- [ ] As B, call every source/entity/job/artifact route using A's ids and A's project:
      all 403/404; A's data unchanged. Unauthenticated → 401.
- [ ] Workspace confinement: a path outside the linked folder (`../`, absolute,
      symlink) is refused by every KiCad tool.
- [ ] No secrets/tokens in logs or API responses (inspect API and companion logs).

## 10. Cross-feature

- [ ] KiCad components appear in fingerprint proposals; confirming links a KiCad
      component to a CAD part with the same MPN.
- [ ] BOM aggregates by MPN; an unlinked CAD twin stays a separate row.
- [ ] Sources / Connected Accounts show correct status through connected → error →
      recovered, and disconnect shows in the activity feed.
- [ ] With consent on, `source.connected` and `source.sync_started` data events are
      recorded without design content; with consent off, none.

## Known limitations (not bugs)

- Scheduled sweep syncs (no job) emit no outcome event — there is no acting user to attribute.
- Live acquisition runs only in the API process; the worker path uses committed exports.
- Artifacts are served via the API (presigned S3 deferred).
- `modality_hints` are not exposed on entity responses (no API doc defines it).
- Solus never talks to a running KiCad GUI; it only shells out to `kicad-cli`.
