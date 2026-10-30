# findings.md — Findings as graph nodes (SOLUSDEV-320)

**Last updated:** 2026-10-17. Tier-1 route plan (ADR-032). **Authority:** ADR-001 (graph-centric),
ADR-013 (autocomplete = the checker library), ADR-027 (graph conventions), CLAUDE.md §7 (checker
and model output is untrusted text). Supersedes the `/warnings` rows of API.md §2.7: a finding is
the durable form of a checker `Warning`, an observer event, a run comparison, a SOL diagnosis or a
simulation result, and it lives in the graph so Impact, Focus and SOL reach it through one
traversal. The in-memory `BenchEventRing` (`livebench/bench_router.py`) is untouched and keeps
serving signal markers.

## 1. The node

`graph_entity` with `kind = "finding"`, `origin = "system"`, `domain` = the finding's domain,
`canonical_key = sha1(project_id, rule_id, sorted(subjects), bucket)` (hex; unique per project
through `uq_graph_entity_project_canonical_key`). `name` is the headline (≤ 512, untrusted text).

```text
attrs:
  rule_id: str              # checker_id, observer rule, "budget_exceeded", …
  severity: info | warning | critical          # checkers/interface.py:Severity
  source: observer | checker | run_compare | sol | simulation
  status: open | acknowledged | dismissed | resolved
  headline: str; explanation: ""; detail: ""   # explanation/detail are filled by SOL later
  evidence: dict             # the producer's structured evidence (≤ 20 merged items kept)
  count: int; first_seen: iso; last_seen: iso
  matrix_cell: MatrixCell | null
  dismissed_until?: iso; acknowledged_by?: uuid; resolved_by?: uuid; note?: str
```

Machines: a `machine` node belongs to the member who first registered it (`attrs.owner_user_id`); another member's `PUT …/machines/{companion_id}` answers 404 and writes nothing. Member and machine `canonical_key`s are prefixed `member:` / `machine:`.

Edges: `observed` finding → each subject (blame order preserved in `attrs.subjects`), written
through `graph/edges.py` with `origin = "system"` and `EdgeEvidence(kind=checker, ref=rule_id)`;
`fixed_by` finding → the fix entity when `resolve` names one.

## 2. Service (`graph/findings.py`)

| function | behaviour |
| --- | --- |
| `raise_finding(session, project_id, spec: FindingSpec)` | upsert on `canonical_key`. New: the attrs above, `count = 1`. Existing: `count += 1`, `last_seen`, evidence merged (latest 20). Dismissed with `dismissed_until` in the future: stays dismissed, count still increments; past the cooldown it reopens. Resolved: reopens as `open` with `count` continuing. |
| `resolve_finding(session, finding_id, user_id, note, fix_ref)` | `status = resolved`, `resolved_by`, `note`; files ONE `.solus` `errors` entry (`ErrorMeta{entity_id = subjects[0], machine_id when the evidence names one, status = resolved, fix_ref}`) with the note as the fix text; `fixed_by` edge when `fix_ref` is given. |
| `dismiss_finding(session, finding_id, user_id, cooldown_hours=24)` | `status = dismissed`, `dismissed_until = now + cooldown`; creates nothing else. |
| `acknowledge_finding(session, finding_id, user_id)` | `status = acknowledged`. |
| `finding_from_warning(warning, *, source="checker")` | `rule_id = checker_id`, `subjects = entity_ids`, `severity`, `headline = message`, `evidence`, `domain = warning.domains[0]`. |

`FindingSpec(rule_id, severity, source, headline, subjects: list[UUID], evidence: dict,
matrix_cell: MatrixCell | None, domain: Domain, bucket: str | None)`; `extra = "forbid"`.

## 3. Routes

All under `/api/v1/projects/{project_id}`, ProjectCtx (non-member → 404); the three POSTs need
MEMBER (viewer → 403) and publish `graph.changed` after commit.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/findings?status=&severity=&subject=&robot=&cursor=&limit=` | list; `subject` = an `observed` target, `robot` = findings whose subjects are the robot itself or anything under its containment (depth ≤ 3); default `status=open`; newest `last_seen` first |
| GET | `/findings/{finding_id}` | one finding with its subjects (`[{id, kind, name}]`) |
| POST | `/findings/{finding_id}/resolve` `{note: str ≤ 4000, fix_ref?: UUID}` | → `resolved`; the `errors` entry id and `fixed_by` edge id are returned |
| POST | `/findings/{finding_id}/dismiss` `{cooldown_hours?: 1..720}` | → `dismissed` |
| POST | `/findings/{finding_id}/acknowledge` | → `acknowledged` |

Response shape (`serialize_finding`): `{id, rule_id, severity, source, status, headline,
explanation, detail, subjects: [UUID], evidence, count, first_seen, last_seen, matrix_cell,
domain, dismissed_until, created_at, updated_at}`.

## 4. Events

Project channel, hint-only (ADR-037): `finding.raised {project_id, finding_id, status, at}` on
insert, `finding.updated` on any status/severity/count change, `finding.resolved` on resolve.
Derived from the committed `graph_entity` row by `graph/live_publisher.py`, so every writer gets
them for free. The desktop refetches `GET /findings?status=open` on these and on `graph.changed`.

## 5. Producers in this branch

`services/budgets.py` (`rule_id = budget_exceeded`, `source = checker`) is the first production
producer. `finding_from_warning` is ready for the checker tool and system proving; wiring the
`run_checkers` tool to persist findings is the SOL branch's work.

## 6. Error catalogue

| HTTP | `error.code` | Where |
| --- | --- | --- |
| 403 | `forbidden` | resolve/dismiss/acknowledge as viewer |
| 404 | `not_found` | non-member project; unknown, foreign or deleted finding; `fix_ref` not a live entity of this project |
| 409 | `conflict` | resolve, dismiss or acknowledge on an already resolved finding |
| 422 | `validation_error` | bad status/severity filter, note too long, cooldown out of range |
