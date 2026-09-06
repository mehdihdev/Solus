# Sourcing — database schema (SOLUSDEV-246, STORE ST5)

**Conventions:** ADR-027 (uuid7 keys, JSONB payloads, VARCHAR+CHECK enums) · **Tier:** 1.
**Models:** `packages/api/src/solus_api/models.py` (`SourcingRequest`, `JobKind.SOURCING`) ·
**Migration:** `f0a1b2c3d4e5` (revises `a9c0d1e2f3b4`; recreates the `jobkind` CHECK) ·
**API:** `docs/api/sourcing.md`.

## 1. `jobs.kind` gains `SOURCING`

One Job per sourcing request; the ARQ function `sourcing_request(ctx, request_id)` settles it
(`SUCCEEDED` with candidates — possibly none — or `FAILED` with a typed error).

## 2. `sourcing_requests`

| column                  | type                  | notes                                                                 |
| ----------------------- | --------------------- | --------------------------------------------------------------------- |
| `id`                    | uuid PK               | uuid7                                                                 |
| `project_id`            | uuid FK projects      | the tenancy anchor; every read filters on it                          |
| `created_by`            | uuid FK users         | the metered user                                                      |
| `job_id`                | uuid FK jobs, null    |                                                                       |
| `status`                | jobstatus CHECK       | mirrors the Job                                                       |
| `door`                  | varchar(16)           | `workspace` \| `bom`                                                  |
| `spec`                  | jsonb                 | the `RequirementSpec` + `assembly_name` + `preferences` (never served) |
| `torque`                | jsonb, null           | the derived torque payload                                            |
| `assembly_entity_id`    | uuid, null            | the assembly the torque came from                                     |
| `candidates`            | jsonb                 | `[Candidate]` after the rules pass (included)                         |
| `excluded`              | jsonb                 | `[{candidate, reasons}]`                                              |
| `rules`                 | jsonb, null           | the effective rules snapshot used                                     |
| `model`                 | varchar, null         | the completion's model name                                           |
| `error`                 | jsonb, null           | `{code, message}`                                                     |
| `selected_candidate_id` | varchar(16), null     |                                                                       |
| `selected_entity_id`    | uuid, null            | the planned `part` entity                                             |
| `created_at`, `finished_at` | timestamptz       |                                                                       |

Index: `(project_id, created_at desc)`.

## 3. Graph writes (no new tables)

- Rules layer: one manual `sourcing_rules` entity per project (`domain project`, attrs = the
  rules), created by `PUT …/rules`.
- Selection: a manual `part` entity (`properties.lifecycle = planned`, `sourcing`,
  `vendor_cad_url`, supplier/cost/part number/quantity) and, for the Workspace door, a `contains`
  edge from the chosen `robot_category`.
