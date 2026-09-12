# Personal source revision API — SOLUSDEV-260

All routes under `/api/v1/projects/{project_id}/sources/{source_id}` use ProjectCtx,
require membership, and reject foreign/disconnected/internal source IDs. The user
identity comes from authentication. A selection only affects that user's reads.
All successful payloads below are inside the standard `{data: ...}` envelope.

- `GET /revisions?page=1`: `{supported: boolean, kind: "git_branch"|null,
  items: [{name: string, commit: string}], next_page: integer|null}`. Provider page
  size 100, bounded page index; only the already-attached repository is addressed.
- `GET /view`: `{base_source_id, status: "default"|"pending"|"ready"|"failed",
  source_id, branch: string|null, commit: string|null, error: string|null}`.
  source_id always names the active ready graph source; pending/failed work retains
  the last successful view. Error messages are sanitized.
- `PUT /view` body `{branch: string}`: validates the ref and schedules bounded
  immutable snapshot acquisition, returning the view with 202. No Source.config
  change. Repeated requests are idempotent or supersede pending work safely.
- `DELETE /view`: clears only the caller's selection; returns the default view.

Unsupported providers return supported=false for discovery and a structured 400
for selection. Deleted branches/provider failures leave the prior view usable.
Existing graph/entity/search responses retain real UUIDs; default requests resolve
the caller's effective view. The source response includes enough base provenance
for the picker to stay attached after the selected root changes. The OpenAPI schema
is regenerated for the typed desktop client after these routes are implemented.
