# sourcing.md — Sourcing Route Plan (one engine, two doors)

**Ticket:** SOLUSDEV-246 (STORE ST5), branch `SOLUSDEV-244-home-h3-root-preferences` (shared).
**Status:** PLANNED → IMPLEMENTED (tier-1 route-plan amendment, ADR-032 — agent-editable, the MR
review is the approval gate).
**Authority:** ADR-027 (graph: the selected part is a manual `part` entity, lifecycle `planned`) ·
ADR-017/018/019/024 (the candidate search is ONE metered `COMPATIBILITY_RESEARCH` completion,
metered to the requesting user) · ADR-025 (roles; member floor on every write) · ADR-035 §`[ext.<id>]`
(the repo's `.solus` `[ext.sourcing]` table is one rules layer) · CLAUDE.md §7 (prompt fencing,
model output is untrusted, no invented facts) · API.md §1 conventions (envelope, errors, 202 + Job,
rate-limit headers) · `docs/wireflows/sourcing.md` (the panel these routes serve) ·
`docs/schemas/sourcing.md` (the `sourcing_requests` table and the `SOURCING` job kind).
**Consumers:** the desktop sourcing panel (`features/sourcing/`), opened from Workspace › Add ›
Hardware › **Find a sourced part** and from BOM › **Find compatible parts**; the SOL tool
`sourcing.derive_torque` (registered for every registry, pure arithmetic, unmetered).

---

## 1. Why this exists

Two doors need the same thing: a requirement in (typed, or derived from a CAD assembly), candidates
with trade-offs out, filtered by the project's compliance/style rules with the reasons visible, and
a selection that enters the graph as a PLANNED part whose vendor CAD model can be fetched. Built
once as a core service + ARQ job; the doors differ only in where the part lands (`door`:
`workspace` lets the caller pick a robot category; `bom` does not).

Honesty rules the whole surface:

- **Torque is arithmetic, never a model.** `POST …/torque` computes `Σ m·g·r × safety` from the
  assembly's placements and masses (or from a plain load/arm). Parts with no mass are NAMED in
  `unknown`, not guessed; the caller may supply masses. The SOL tool is the same function.
- **Candidates are grounded or labelled.** A candidate with an `https://` `source_url` is
  `cited`; without one it is `unverified` and its `cost`, `currency`, `availability` are nulled
  server-side, so no price or stock is ever shown from a model's memory.
- **Exclusions are Solus's words.** The rules pass (`sourcing/rules.py`) is deterministic; an
  excluded candidate carries the rule text (`Supplier 'Acme Motors' is excluded: <reason>`),
  never model prose. Unknown facts (no voltage, no certifications) FLAG, never exclude.
- **Every candidate states `optimizes_for` and `gives_up`.** Required fields; a candidate
  without them is dropped at parse.

## 2. Routes — `/api/v1/projects/{project_id}/sourcing`

All routes: `ProjectCtx` (member of the project's team). Writes require `member`
(`require_role(ctx, Role.MEMBER)`; viewers get 403). Every list and read is project-scoped.

| Method | Path                                  | Description                                                                                                                                               | Metering                        |
| ------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| GET    | `/rules`                              | The effective rules: defaults ← repo `.solus` `[ext.sourcing]` (the `solus_project_toml` connector row) ← the project's manual `sourcing_rules` entity     | none                            |
| PUT    | `/rules`                              | Save the project-level layer (the manual `sourcing_rules` entity); returns the effective set. Member floor.                                               | none                            |
| POST   | `/torque`                             | Derive torque from an assembly (`assembly_entity_id`, optional `pivot_mm`, `masses`) or a spec (`load_kg` + `arm_m`); `safety_factor` 1.0–10 (default 1.5) | none                            |
| POST   | `/requests`                           | `202` — create a sourcing request + `SOURCING` Job; ARQ `sourcing_request` (inline when no redis). 10/min/user (`429` + `Retry-After`). Member floor.     | one `COMPATIBILITY_RESEARCH` completion, to the caller |
| GET    | `/requests`                           | The project's requests, newest first (`limit` ≤ 100)                                                                                                      | none                            |
| GET    | `/requests/{request_id}`              | One request (poll target). `404` across projects.                                                                                                        | none                            |
| POST   | `/requests/{request_id}/select`       | `201` — the chosen candidate becomes a manual `part` (lifecycle `planned`) under `category_entity_id` (workspace door) or the project; `404` unknown candidate. Member floor. | none                            |

### 2.1 Bodies

`TorqueBody` (extra forbidden): `assembly_entity_id?: uuid` · `pivot_mm?: [x,y,z]` · `masses?:
{<entity uuid>: kg}` (≤ 500) · `load_kg?` (0–100 000) · `arm_m?` (0–1000) · `safety_factor` (1.0–10,
default 1.5). `422 validation_error` when neither an assembly nor a load+arm is given.

`RequestBody` = `TorqueBody` + `spec: RequirementSpec` (`text` ≤ 2000, `protocol?`, `voltage_v?`,
`load_kg?`, `arm_m?`, `part_class` default `motor`) + `door: "workspace" | "bom"` (default `bom`) +
`preferences?: {section: string ≤ 2400}` (the user's `~/.solus/preferences.json` sections, ranking
context only — never echoed back; stripped from `spec` on read).

`SelectBody`: `candidate_id` (16 hex) · `category_entity_id?: uuid` (must be a `robot_category`
of this project) · `quantity` (1–100 000, default 1).

`SourcingRules` (GET/PUT): `excluded_suppliers: [{name, reason}]` · `required_certifications:
[str]` · `max_voltage_v: number | null` · `allowed_protocols: [str]` · `preferred_suppliers: [str]`.
The repo table uses scalar strings (`excluded_suppliers = "Acme Motors: export controlled; Foo"`);
`rules_from_repo_table` parses them.

### 2.2 Responses

`torque` (POST /torque and `request.torque`): `{static_torque_nm, required_torque_nm,
safety_factor, loads: [{name, mass_kg, lever_arm_m}], unknown: [name], assumptions: [str],
assembly?: name, parts?: [{entity_id, name, mass_kg | null, position_mm | null}]}`.

`request`: `{id, project_id, status: queued|running|succeeded|failed|cancelled, door, spec,
torque | null, assembly_entity_id | null, candidates: [Candidate], excluded: [{candidate,
reasons: [str]}], rules | null, model | null, error: {code, message} | null, job_id,
selected_candidate_id | null, selected_entity_id | null, created_at, finished_at | null}`.

`Candidate`: `{id (sha16), name, manufacturer, part_number, supplier, torque_nm, cost, currency,
weight_kg, protocol, voltage_v, availability, certifications: [str], source_url, vendor_cad_url,
optimizes_for, gives_up, notes, grounding: cited|unverified, flags: [str]}`. Non-`https://` URLs
are dropped at parse. At most 8 candidates per request.

`POST /requests` → `{request, job_id}`. `POST …/select` → `{entity, request}` where `entity` is
the new part: `origin manual`, `type part`, domain `electrical` for sensors/controllers/power/wiring
categories else `mechanical`, `properties.lifecycle = "planned"`, `properties.sourcing = {request_id,
candidate_id, grounding, optimizes_for, gives_up, source_url}`, `properties.vendor_cad_url`,
`properties.supplier/unit_cost/currency/part_number/quantity` when known; a `contains` edge from
the category when one was given. The BOM's design-row reader shows the manual part's own
lifecycle/supplier/cost, so the part appears PLANNED in the BOM without an overlay.

### 2.3 Failure modes (typed, never a 500)

The engine `run_request` never raises: `insufficient_credits` (ADR-018 gate), `rate_limited`
(frequency / trial caps), `model_unavailable` (provider or parse failure) settle the request as
`failed` with `error.code/message` and mark the Job `FAILED`; an empty candidate list is a
`succeeded` request with `candidates: []` (empty beats invented).

## 3. SOL tool

`sourcing.derive_torque` (`sourcing/tools.py`): `{assembly_entity_id, pivot_mm?, masses?,
safety_factor?}` → the `torque` payload above, read-only, tenant-scoped through the same service
as the route. Registered for every registry (no `user_id` gate: it needs no credentials).

## 4. Data events (ADR-011)

Server: `sourcing.requested` `{request_id, door, has_assembly, has_torque}` ·
`sourcing.rules_updated` `{excluded, certifications, max_voltage_v, protocols}` ·
`sourcing.selected` `{request_id, candidate_id, entity_id, grounding, door}`. The completion itself
is metered and logged by the gateway (`context = COMPATIBILITY_RESEARCH`).

## 5. Prompt hygiene (CLAUDE.md §7)

`sourcing_prompt(nonce, spec=, torque=, rules=, preferences=, assembly_name=)` fences every
user-influenced value (`spec.text`, assembly names, part names, preferences) in `data_block`s; the
model is asked for JSON only; `parse_candidates` is a tolerant extractor that drops anything
malformed, over-long, or with a non-https URL. The rules pass runs AFTER parsing, in Python.
