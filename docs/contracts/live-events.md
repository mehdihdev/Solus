# Live change-hint frames (ADR-037, SOLUSDEV-312)

**Owners:** `packages/contracts/python/solus_contracts/live_events.py` (Python) and
`packages/shared-types/src/live-events.ts` (TypeScript). Fixtures shared by both
live in `packages/shared-types/fixtures/live-events/`; the drift guard
(`_fields.json` + `drift.test.ts`) fails either suite when the two disagree.

## Streams

| Stream  | Route                                      | Channels                                                |
| ------- | ------------------------------------------ | ------------------------------------------------------- |
| Project | `GET /api/v1/projects/{project_id}/events` | `project:{id}`                                          |
| Account | `GET /api/v1/users/me/events`              | `user:{me}` + `team:{t}` for every live team membership |

Both are SSE with the ordinary `Authorization: Bearer` header. The `event:` name
is the frame's `type`. On connect each stream first sends `event: ready`
(`ProjectStreamReady` / `AccountStreamReady`, no `type` field) — a client
revalidates everything it shows on every `ready`, because there is no replay.
Idle streams send a `: keepalive` comment every 25 s. Open streams re-verify
access at most every 30 s and immediately on `access.revoked`, and end the
response when access is gone.

## Rules

1. **Hints, not deltas.** Frames carry ids, counts and versions only — never
   names, emails, invite tokens, titles or CAD data. Refetch through the REST
   route you already use.
2. **Routing is structural.** The channel is derived server-side from the
   committed row's scope. Nothing in a frame body decides who receives it.
3. **Committed only.** Frames are queued on the DB session and published after
   commit; a rollback publishes nothing.
4. **Dropping is safe.** A slow subscriber's frames may be dropped; the next
   hint or the next `ready` triggers the same refetch.
5. `hardware.devices_changed` is the one full-list exception (SOLUSDEV-250),
   delivered in-process only.

## Project channel

| type                       | fields                                       | refetch                                 |
| -------------------------- | -------------------------------------------- | --------------------------------------- |
| `graph.changed`            | `project_id, source_id, sync_id, counts, at` | graph snapshot                          |
| `hardware.devices_changed` | `project_id, devices, at`                    | none (full list)                        |
| `layout.changed`           | `project_id, version, at`                    | workspace layout, if `version` is newer |
| `sources.changed`          | `project_id, source_id, at`                  | project sources                         |
| `project.updated`          | `project_id, team_id, at`                    | project detail                          |
| `job.updated`              | `project_id, job_id, status, at`             | the job / anything waiting on it        |
| `access.revoked`           | `user_id, team_id, project_id, at`           | stream closes if access ended           |

## Account stream (team + user channels)

| type                    | fields                              | refetch                              |
| ----------------------- | ----------------------------------- | ------------------------------------ |
| `team.updated`          | `team_id, at`                       | team detail / team list              |
| `team.members_changed`  | `team_id, at`                       | members                              |
| `team.invites_changed`  | `team_id, at`                       | invites (admins only; others ignore) |
| `team.projects_changed` | `team_id, project_id, at`           | team project list                    |
| `team.activity`         | `team_id, project_id, actor_id, at` | activity feed                        |
| `notification.created`  | `user_id, at`                       | notifications                        |
| `membership.changed`    | `user_id, team_id, project_id, at`  | `me`, team list                      |
| `access.revoked`        | `user_id, team_id, project_id, at`  | `me`, team list                      |
