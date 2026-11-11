# `sim_session` (SOLUSDEV-322 P2-T1)

One row per simulator session the API knows about, written only by
`simulation/sessions_ledger.py:SessionsLedger`. A row Solus wrote when it started the session
(`owner = sol`) is the proof the per-call gate (`agent/dynamic_gate.py`, P2-T2) reads before it
lets an action inside that session through without a card; a session Solus only attached to
(`owner = user`), an id nobody recorded, an ended session or another project's row is never
owned. Where ownership cannot be proven, the answer is a card. The table names no simulator:
`provider` is a string the wrappers pass (`agent/tools/{gazebo,isaac}_tools.py`).

| Column               | Type                                          | Notes                                                                                               |
| -------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `id`                 | uuid PK                                       | uuid7 (`UuidPkMixin`)                                                                               |
| `project_id`         | uuid, FK `projects` ON DELETE CASCADE         | The tenant. Every read and write is scoped by it; a write takes `lock_project` first.               |
| `provider`           | varchar(32)                                   | The ledger's discriminator: which wrapper family started or attached the session.                   |
| `session_id`         | varchar(128)                                  | The companion server's session id, as the wrapper received it.                                      |
| `owner`              | varchar(32), CHECK `sim_session_owner`        | `sol` when Solus started it (`record_owned_start`), `user` when it attached (`record_attached`).    |
| `started_by_call_id` | varchar(128), nullable                        | The dispatching tool call's id (`dynamic_gate.current_call_id`); null for an attach or a card path. |
| `scene_ref`          | varchar(512), nullable                        | One vendor-free column: the world file/name or the stage path.                                      |
| `scene_name`         | varchar(128), nullable                        | The name the running simulator addresses the scene by, fixed when the row is written (P5-T4).      |
| `started_at`         | timestamptz                                   |                                                                                                     |
| `ended_at`           | timestamptz, nullable                         | Set by `end_session` (a `stop`, or a probe that reports the process gone). Null = live.             |
| `created_by`         | uuid, FK `users` ON DELETE SET NULL, nullable | The person whose turn started or attached it.                                                       |

**Indexes.** `uq_sim_session_live (project_id, provider, session_id) WHERE ended_at IS NULL`
keeps one live row per session id; `ix_sim_session_project_provider_ended (project_id, provider,
ended_at)` serves `is_owned`, `running` and `owned_running_count`.

**Rules.** One owned session per `(project, provider)`: `record_owned_start` raises
`OwnedSessionRunningError` (409 `sim_session_running`) while an `owner = sol` row of that
provider is live, or while the same id is live under any owner. `record_attached` on an id
already live returns that row unchanged: an attach never changes who owns a session.
`end_session` on an unknown or already-ended id is a no-op. An ended id may be started again.

**`scene_name`.** A routine's readback is keyed `<scene_name>/<model>/<joint>` from this row and
the request, never from names the companion's result carries (P5-T4 review). An attach records
the world the person named; an owned start records the identifier-shaped world name the fork
resolved from the user's file at that moment, else null — and a null refuses to file runs for
that session rather than believe a later result.

Migrations: `packages/api/migrations/versions/a32200000001_solusdev_322_sim_sessions.py`
(`down_revision = a32100000001`); `a32200000003_solusdev_322_sim_session_scene_name.py` adds
`scene_name` (`down_revision = a32200000002`).
