# findings.md — Findings as graph nodes (SOLUSDEV-320)

**Last updated:** 2026-10-28. Tier-1 route plan (ADR-032). **Authority:** ADR-001 (graph-centric),
ADR-013 (autocomplete = the checker library), ADR-027 (graph conventions), CLAUDE.md §7 (checker
and model output is untrusted text). Supersedes the `/warnings` rows of API.md §2.7: a finding is
the durable form of a checker `Warning`, an observer event, a run comparison, a SOL diagnosis or a
simulation result, and it lives in the graph so Impact, Focus and SOL reach it through one
traversal. The in-memory `BenchEventRing` (`livebench/bench_router.py`) keeps serving signal
markers; since SOLUSDEV-321 P2-T3 a marker may carry the `finding_id` of the observer finding it
marks, attached server-side only (§5).

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
  headline: str; explanation: ""; detail: ""   # explanation/detail are filled by narration (§5)
  causes_ranked?: [str]      # narration's order of evidence.causes kinds, most likely first
  narration_tokens?: int     # tokens of the one call that narrated it
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

| function                                                                                                     | behaviour                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `raise_finding(session, project_id, spec: FindingSpec)`                                                      | upsert on `canonical_key`. New: the attrs above, `count = 1`. Existing: `count += 1`, `last_seen`, evidence merged (latest 20). Dismissed with `dismissed_until` in the future: stays dismissed, count still increments; past the cooldown it reopens. Resolved: reopens as `open` with `count` continuing. |
| `resolve_finding(session, finding_id, user_id, note, fix_ref)`                                               | `status = resolved`, `resolved_by`, `note`; files ONE `.solus` `errors` entry (`ErrorMeta{entity_id = subjects[0], machine_id when the evidence names one, status = resolved, fix_ref}`) with the note as the fix text; `fixed_by` edge when `fix_ref` is given.                                            |
| `dismiss_finding(session, finding_id, user_id, cooldown_hours=24)`                                           | `status = dismissed`, `dismissed_until = now + cooldown`; creates nothing else.                                                                                                                                                                                                                             |
| `acknowledge_finding(session, finding_id, user_id)`                                                          | `status = acknowledged`.                                                                                                                                                                                                                                                                                    |
| `annotate_finding(session, project_id, finding_id, *, explanation, detail, causes_ranked, narration_tokens)` | the ONE writer of the narration keys: `explanation` (capped at 1,200 chars), `detail` (4,000), `causes_ranked`, `narration_tokens`; attrs reassigned, `version += 1`, status, headline and evidence unchanged; flushes. Resolved → 409.                                                                     |
| `resolve_system_finding(session, project_id, finding_id, *, reason)`                                         | `status = resolved` by Solus, not a person (SOLUSDEV-321 P3-T3): `resolved_by = "system"`, `note = reason`; no `.solus` entry, no activity, no `fixed_by`. Read fresh under the project lock; an already resolved finding is returned unchanged. A later raise reopens it as for `resolve_finding`.         |
| `finding_from_warning(warning, *, source="checker")`                                                         | `rule_id = checker_id`, `subjects = entity_ids`, `severity`, `headline = message`, `evidence`, `domain = warning.domains[0]`.                                                                                                                                                                               |

`FindingSpec(rule_id, severity, source, headline, subjects: list[UUID], evidence: dict,
matrix_cell: MatrixCell | None, domain: Domain, bucket: str | None)`; `extra = "forbid"`.

Evidence merge on a re-raise: every top-level key takes the latest raise's value — lists such as
`also` and `causes` included (SOLUSDEV-321 M71) — and `items` keeps the latest 20 raises whole.
The writers (`resolve`, `dismiss`, `acknowledge`, `annotate`) read the row fresh under the project
lock.

## 3. Routes

All under `/api/v1/projects/{project_id}`, ProjectCtx (non-member → 404); the three POSTs need
MEMBER (viewer → 403) and publish `graph.changed` after commit.

| Method | Path                                                                  | Purpose                                                                                                                                                                                       |
| ------ | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/findings?status=&severity=&subject=&robot=&cursor=&limit=`          | list; `subject` = an `observed` target, `robot` = findings whose subjects are the robot itself or anything under its containment (depth ≤ 3); default `status=open`; newest `last_seen` first |
| GET    | `/findings/{finding_id}`                                              | one finding with its subjects (`[{id, kind, name}]`)                                                                                                                                          |
| POST   | `/findings/{finding_id}/resolve` `{note: str ≤ 4000, fix_ref?: UUID}` | → `resolved`; the `errors` entry id and `fixed_by` edge id are returned                                                                                                                       |
| POST   | `/findings/{finding_id}/dismiss` `{cooldown_hours?: 1..720}`          | → `dismissed`                                                                                                                                                                                 |
| POST   | `/findings/{finding_id}/acknowledge`                                  | → `acknowledged`                                                                                                                                                                              |

Response shape (`serialize_finding`): `{id, rule_id, severity, source, status, headline,
explanation, detail, causes_ranked, robot_id, subjects: [UUID], evidence, count, first_seen,
last_seen, matrix_cell, domain, dismissed_until, created_at, updated_at}`. `causes_ranked` (`[]`
until narrated) and `robot_id` (`evidence.robot_id` when it is an id, else `null`) are optional
with defaults, so a row older than narration still serializes.

## 4. Events

Project channel, hint-only (ADR-037): `finding.raised {project_id, finding_id, status, at}` on
insert, `finding.updated` on any status/severity/count change and when `explanation` goes from
empty to non-empty (SOLUSDEV-321 P2-T6, Q4c: narration filled it; a `detail` fill or a rewritten
explanation is no hint), `finding.resolved` on resolve.
Derived from the committed `graph_entity` row by `graph/live_publisher.py`, so every writer gets
them for free. The desktop refetches `GET /findings?status=open` on these and on `graph.changed`.

## 5. Producers in this branch

`services/budgets.py` (`rule_id = budget_exceeded`, `source = checker`) is the first production
producer.

**The interaction matrix (SOLUSDEV-321 P3-T3, `checkers/matrix_runner.py`).** After every
`graph.changed`, debounced 10 s per project, the ARQ job `run_matrix_checkers` runs every rule
of `checkers/cells` over ONE bounded read of the project. Without a queue it runs inline. The ARQ
id is `run_matrix_checkers:<project>`, with `keep_result=0`. A change that lands while the
project's job is queued or running is judged at the next change: arq refuses the enqueue while
the job's key lives. The budgets recompute has the same ceiling.

The read holds at most `MAX_MATRIX_ENTITIES` (5,000) entities, in this order: the kinds the facts
are read off (robots, scene models, components, requirements), then the entities a judged
relation touches, then the rest, oldest first. It holds at most `MAX_EDGE_SCAN` edges of the
relations the rules declare. A cap that binds is logged with the project id. A writing run
judges the project's shared view, whatever read scope its caller bound.

Locking: a writing run takes the project lock first, and never waits for an edge row another
writer holds. Such a row is skipped this run (counted and logged once a run) and judged at the
next change.

- A review action that writes edges takes the project lock first, so it waits behind the run. A
  candidate's confirm or decline takes no project lock: it writes its one edge row, and a run that
  meets that row held skips it as above.
- A sync locks edge rows first and the project lock later. It waits at most one run, and the run
  never deadlocks it (the run waits for no row). This says nothing about a sync against another
  writer that holds the project lock and then waits for rows.

Its results are kept on the edges (`docs/api/relations.md` §2) and as findings, all with
`source = checker` and the rule's `matrix_cell`:

- **A `fail`** is raised through `finding_from_warning`, once per (rule, subjects) a run.
  - Its subjects are the rule's, and a result with no subject raises nothing.
  - Lists in its evidence are cut to their first 50 items, with `<key>_count` beside them. A
    spec still refused (past 16 KiB) is logged and skipped, and the run goes on.
  - A rule with `raises_findings = False` keeps its fail on the edge only, when another producer
    already raises that problem.
- **A fact the project does not state** (`unknown_input`) is ONE standing `info` finding per
  (rule, entity), with `bucket = null`, never one per edge.
  - The entity is the result's first subject, e.g. the code file for six goal-less `commands`
    edges. A fact the whole project lacks is about each of the project's robots; with no robot,
    it is a line of the run's report and no finding. So is a missing relation on a truncated run:
    the relation's edges may lie past the cap.
  - The headline: `could not check <rule_id>: <fact> unknown for <entity>; set it in <set_in>`.
  - The evidence holds `missing` (each lacking `{name, set_in}`), `edges` (how many edge
    results said so) and `signal`, the change signal: when each of the project's sources last
    synced (branch snapshots excluded, at most 32). `evidence.missing` is what marks a standing
    info.
  - A run that still lacks the fact raises it again, bumping `count` on the same node, only when
    the signal moved since its last raise. A run no sync caused re-raises nothing and publishes
    no frame; its other evidence (`edges`, `missing`) refreshes at the next sync.
  - It is resolved through `resolve_system_finding` only when a run has judged that entity
    under that rule with no `unknown_input` (for a project-wide fact: when the rule no longer
    lacks it). A run that skipped the entity, because a cap bound or the edge is gone, resolves
    nothing.
  - The narrator never narrates `info`.
- **Nothing is written** by a dry run (`dry_run=True`) or by a run given its own facts (P4's
  backward loop), and a run never publishes `graph.changed`.
- **SOL's `run_checkers`** judges its own graph slice with the matrix (a dry run). It returns
  those fails with the legacy rules' warnings and persists nothing; persistence is the job's.

**Observer findings (SOLUSDEV-321 P2-T3).** A robot bench session's window evaluator
(`livebench/findings/window_evaluator.py`) raises what the live-signal rules
(`livebench/findings/rules/`) find in the session's telemetry. The spec fields:

- `source = "observer"`;
- `bucket` is the bench session's id, so a condition that persists is one node per session whose
  `count` rises with every tick that still shows it, and another session opens its own;
- `matrix_cell` is the rule's;
- `domain` is the first subject's.

Folding: the hits on one subject within one event-time window fold into the highest-precedence
rule's finding, and the other rules' ids ride in `evidence.also`.

The evidence is the rule's own numbers plus:

- `robot_id` and `session_id`;
- `causes`, each `{kind, for, against}`;
- when code commands the part, `code_site {entity_id, source_id, path, line}`, where `source_id`
  is the code entity's own source.

`robot_entity_id` / `evidence.robot_id` is the session's ROOT entity — a robot, or a bare part bound on its own — and `missing_signals` lands on that root.

- **`missing_signals`.** What the rules could not judge for want of a channel, a relation or a
  fact is listed on that root as `attrs.missing_signals`: `"<part>: <need>"`, sorted and
  deduplicated. It is written at a part's first assessment and rewritten when the part's channels
  grow, never once per tick; a relation or fact added during a session shows from the next
  session — the rules themselves use a new fact from their next window.
- **Rejected samples.** A sample dated more than 5 s past the server's clock is dropped before
  any rule reads it, so one bad timestamp cannot blind its channel.
- **CPU budget.** The rules of one window share a budget of 20 ms, or 10 ms for each part the
  session streams when that is more (`observer.cpu_budget_ms` and `observer.cpu_budget_ms_per_part`
  in `orchestration/models.yaml`): six parts get 60 ms. Rules run one after another until it is
  spent; the rest are skipped and counted in one log line a tick, and the next tick resumes at the
  first rule skipped. While at least half of the rules fit, every rule runs in any two consecutive
  ticks.
- **One transaction.** All of a tick's findings are raised in one transaction.
- **Markers.** At a finding's first raise in the session, the bench event ring gets a marker with
  its id on each channel its part streamed.

**Narration (SOLUSDEV-321 P2-T6, `agent/finding_narration.py`).** After each tick's commit the
evaluator hands the ids it raised to the app's one `Narrator`, bound per session to the session's
owner (a session without an owner never narrates). Per robot, ids are kept once each; a flush runs
10 s after the first and calls a model at most once every 60 s. It narrates the findings that are
not `info`, open or acknowledged, and not yet explained (critical first, eight at most), in ONE
`complete(complexity=standard, type=general, purpose="narration", turn_id=None)` billed to the
owner, with the owner's `sol_mode` in the system text. The packet — each finding's latest evidence
and candidate causes, its subjects' envelopes, the 1-hop graph and the prior `errors` entries — is
one fenced data block. The reply is a JSON array, one object a finding; a malformed one or one with
unsafe prose writes nothing and is not retried. A sentence whose number (with its unit) is not among
the packet's evidence and envelope numbers moves to `detail` as `not grounded: …`; `causes_ranked`
must be a permutation of the finding's cause kinds or is dropped; a proposed headline is kept in
`detail` as `suggested headline: …` — the headline is never rewritten. A 402 or 429 skips the
flush, logged once a robot.

## 6. Error catalogue

| HTTP | `error.code`       | Where                                                                                                |
| ---- | ------------------ | ---------------------------------------------------------------------------------------------------- |
| 403  | `forbidden`        | resolve/dismiss/acknowledge as viewer                                                                |
| 404  | `not_found`        | non-member project; unknown, foreign or deleted finding; `fix_ref` not a live entity of this project |
| 409  | `conflict`         | resolve, dismiss or acknowledge on an already resolved finding                                       |
| 422  | `validation_error` | bad status/severity filter, note too long, cooldown out of range                                     |
