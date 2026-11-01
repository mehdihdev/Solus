# Bench view: one team-shared Live Bench view per project (SOLUSDEV-319, ADR-014 2026-10-31)

Routes: [docs/api/bench-view.md](../api/bench-view.md). Architecture:
[docs/architecture/bench-view.md](../architecture/bench-view.md). Mirrors `workspace_layouts`
(one project-owned row, integer version, JSONB body).

## `bench_views`

| Column                     | Type                                            | Notes                                                                                |
| -------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| `project_id`               | UUID PK, FK `projects.id` ON DELETE CASCADE     | One row per project; team scope comes from the project                               |
| `version`                  | Integer, NOT NULL                               | ≥ 0. The row is created by the first write with version 1; no row reads as version 0 |
| `display`                  | JSONB, NOT NULL, default `[]`                   | Array of display entries (below)                                                     |
| `derived`                  | JSONB, NOT NULL, default `[]`                   | Array of derived-signal entries (below)                                              |
| `updated_by`               | UUID FK `users.id` ON DELETE SET NULL, nullable | The user whose request (or whose SOL turn) wrote last. Never exposed by `GET /view`  |
| `created_at`, `updated_at` | timestamptz                                     | `TimestampMixin`                                                                     |

No soft delete: the row belongs to the project and goes with it (cascade). No secret, token or
credential column. No index beyond the primary key (every access is by `project_id`).

**Check constraints:**

- `ck_bench_views_version_nonnegative`: `version >= 0`.
- `ck_bench_views_display_array`: `jsonb_typeof(display) = 'array'`.
- `ck_bench_views_derived_array`: `jsonb_typeof(derived) = 'array'`.
- `ck_bench_views_display_bound`: `jsonb_array_length(display) <= 512`.
- `ck_bench_views_derived_bound`: `jsonb_array_length(derived) <= 32`.

Everything finer (entry shapes, charset, uniqueness, group bounds, expression bounds) is enforced
by the Pydantic models in the service before write and re-validated on read; a row that fails
re-validation on read is logged with the project id and served as the empty view, never as a 500.

**Concurrency:** writers lock the `projects` row `FOR UPDATE` before reading this row (the row may
not exist yet), compare `version`, and write `version + 1`. The live publisher's ORM listener
derives `bench.view_changed {project_id, version, at}` from a new row or a changed `version`.

## JSON shapes

### `display[]` entry

```json
{
  "target": {
    "kind": "signal",
    "device_id": "usb:5A7A/3",
    "signal": "shoulder_lift.position"
  },
  "pinned": true,
  "hidden": false,
  "order": 0,
  "unit": "rad",
  "limits": { "min": -1.6, "max": 1.6 },
  "plot_group": "Shoulder"
}
```

| Field        | Type                                                                                           | Default (entry omitted when every field is default) |
| ------------ | ---------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `target`     | `{"kind":"signal","device_id":str 1–512,"signal":str 1–128}` or `{"kind":"derived","id":UUID}` | required; unique across entries                     |
| `pinned`     | bool                                                                                           | `false`                                             |
| `hidden`     | bool                                                                                           | `false`                                             |
| `order`      | int 0–1023 or null                                                                             | `null` (natural order)                              |
| `unit`       | str ≤ 32 or null                                                                               | `null` (packet unit)                                |
| `limits`     | `{"min": float, "max": float}` finite, `min < max`, \|v\| ≤ 1e12, or null                      | `null` (autoscale)                                  |
| `plot_group` | str 1–64 or null                                                                               | `null`                                              |

Target strings and `plot_group` use the reference charset (printable ASCII 0x20–0x7E except `"`
and `\`). At most 16 distinct `plot_group` values and 8 entries per group. A `derived` target must
name an id present in `derived[]` (deleting a derived signal removes its entries in the same
write).

### `derived[]` entry

```json
{
  "id": "0b9f6c1e-2d0a-4f43-9a51-0f1c3b7d2e88",
  "name": "Lift error",
  "expression": "sig(\"usb:5A7A/3\", \"shoulder_lift.goal\") - sig(\"usb:5A7A/3\", \"shoulder_lift.position\")",
  "unit": "deg",
  "node_count": 3,
  "refs": [
    { "device_id": "usb:5A7A/3", "signal": "shoulder_lift.goal" },
    { "device_id": "usb:5A7A/3", "signal": "shoulder_lift.position" }
  ],
  "created_at": "2026-10-31T21:04:11Z",
  "updated_at": "2026-10-31T21:04:11Z"
}
```

| Field                      | Type                               | Notes                                                                                    |
| -------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------- |
| `id`                       | UUID string                        | Server-generated on create unless supplied by an Undo restore                            |
| `name`                     | str 1–64, printable                | Unique per project, case-insensitive                                                     |
| `expression`               | str 1–512                          | Source text exactly as accepted; parses under docs/api/bench-view.md §4                  |
| `unit`                     | str ≤ 32 or null                   | Display unit of the result; not checked against the inputs' units                        |
| `node_count`               | int 1–64                           | Computed by the server parser; never client-supplied                                     |
| `refs`                     | array 1–8 of `{device_id, signal}` | Distinct references in source order (`refs[0]` is the time base); computed by the server |
| `created_at`, `updated_at` | ISO timestamp                      | Per entry; `updated_at` moves on replace                                                 |

Upper size: 32 entries × (512-char expression + 8 refs × 640 chars + metadata) plus 512 display
entries stays under 1 MiB; the service rejects a body that would serialize above 1 MiB with 422
`validation_error` as a backstop.

## Migration

One Alembic revision creating `bench_views` with the constraints above; downgrade drops it. No
backfill: the per-user `localStorage` signal preferences (`solus.signal.v1:*`, name and unit) are
not migrated. The team view's `unit` supersedes the per-user unit; the per-user display name stays
local (see the wireflow).
