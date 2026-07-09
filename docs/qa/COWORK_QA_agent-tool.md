# Cowork QA — SOLUS-W0-04 Agent-Tool Interface Contract

This feature is a **backend contract** (no UI, no HTTP route). It ships the tool-calling
spine the SOL Agent will use: the four envelope shapes, the `Tool` protocol +
`InProcessTool`, the `ToolRegistry` (whose `invoke` never raises), the reference
`get_entity` tool, and the `artifacts` table. Verification is therefore done by running
the migration, the test suite, and a short Python exerciser — not by clicking a UI.

Everything below assumes only this file, a checkout of the repo, and Docker.

---

## Setup (do once)

| #   | Step                                               | Command                                                                                                                   | Expected                                                                                                                                      |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| S1  | Start Postgres+pgvector & Redis                    | `make db-up`                                                                                                              | `solus-db-1` reports **healthy** on `:5432`                                                                                                   |
| S2  | Install the workspace env                          | `uv sync --all-packages`                                                                                                  | completes; installs `jsonschema` + `types-jsonschema`. **Do NOT run bare `uv sync`** — it prunes the shared `.venv` to the empty root member. |
| S3  | Apply the schema (incl. the new `artifacts` table) | `cd packages/api && SOLUS_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus uv run alembic upgrade head` | ends at head `344b7841f6d3`; no error                                                                                                         |

> If `make db-up` is unavailable, any Postgres 16 + pgvector on `localhost:5432` with role
> `solus`/`solus` works. SQLite will NOT work (pgvector columns).

---

## Flow 1 — Migration applies on a fresh DB and reverses

- [ ] **1.1** From `packages/api`, against a throwaway DB URL, `alembic upgrade head` → succeeds; an `artifacts` table exists with columns `project_id, scope, uri, media_type, size_bytes, storage_location, created_by, source_tool, id, created_at, updated_at, deleted_at`.
- [ ] **1.2** `alembic downgrade base` → drops `artifacts` cleanly (no error).
- [ ] **1.3** `alembic upgrade head` again → re-applies cleanly. `alembic heads` shows a **single** head `344b7841f6d3` (down_revision `7ea820a98068`).
- [ ] **1.4** The original W0-01 migration file `7ea820a98068_initial_schema.py` is **unchanged** (this ticket adds a NEW migration, never edits the old one).

## Flow 2 — Full test suite is green (also re-proves the migration)

- [ ] **2.1** `SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test uv run pytest packages/api -q` → **all pass** (149+), 0 failures. The session fixture runs the migration to head on a fresh DB, so a green run also proves the migration applies.
- [ ] **2.2** The five new files run clean: `pytest packages/api/tests/test_shapes.py test_tool.py test_registry.py test_get_entity.py test_artifacts.py -q` → 28+ passed.
- [ ] **2.3** `uv run mypy packages/api/src` → “Success: no issues found”. `uv run ruff check .` → “All checks passed!”.

## Flow 3 — Registry safety contract end to end (the core behavior)

Run this exerciser (from `packages/api`, with `SOLUS_DATABASE_URL` pointed at a DB at head).
It seeds one project + entity, then drives the registry:

```python
import asyncio, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from solus_api.models import User, Team, Membership, Project, GraphEntity, EntityKind, Domain, Role
from solus_api.agent.tools import ToolRegistry, ToolCall, build_get_entity_tool

async def main():
    eng = create_async_engine("postgresql+asyncpg://solus:solus@localhost:5432/solus")
    sm = async_sessionmaker(eng, expire_on_commit=False)
    async with sm() as s:
        u = User(supabase_user_id="qa-"+uuid.uuid4().hex[:8], email="qa@x.com"); t = Team(name="T")
        s.add_all([u, t]); await s.flush()
        s.add(Membership(team_id=t.id, user_id=u.id, role=Role.OWNER))
        p = Project(team_id=t.id, name="P", created_by=u.id); s.add(p); await s.flush()
        e = GraphEntity(project_id=p.id, kind=EntityKind.COMPONENT, domain=Domain.ELECTRICAL,
                        name="IMU_x", attrs={"addr": "0x68"}); s.add(e); await s.commit()
        eid, pid = str(e.id), p.id
    reg = ToolRegistry(); reg.register(build_get_entity_tool(sm, pid))
    print("list:   ", [d.name for d in reg.list()])
    print("valid:  ", (r := await reg.invoke(ToolCall(tool="get_entity", args={"entity_id": eid}))).ok, r.value)
    print("missing:", (r := await reg.invoke(ToolCall(tool="get_entity", args={"entity_id": str(uuid.uuid4())}))).ok, r.error.code.value)
    print("badargs:", (r := await reg.invoke(ToolCall(tool="get_entity", args={"entity_id": "nope"}))).ok, r.error.code.value)
    print("unknown:", (r := await reg.invoke(ToolCall(tool="ghost", args={}))).ok, r.error.code.value)
    await eng.dispose()
asyncio.run(main())
```

- [ ] **3.1** `list` prints `['get_entity']`.
- [ ] **3.2** `valid` → `True` and a dict with `name='IMU_x'`, `attrs={'addr':'0x68'}`, `kind='component'`, `domain='electrical'`, and **no `embedding` key**.
- [ ] **3.3** `missing` → `False`, `not_found`.
- [ ] **3.4** `badargs` (a non-uuid) → `False`, `invalid_args`. Also try `args={}` (missing) → `invalid_args`.
- [ ] **3.5** `unknown` (unregistered tool name) → `False`, `not_found`.
- [ ] **3.6** **None of the four calls raise** — every one returns a `ToolResult`. There is no traceback in any `error.message`.

## Flow 4 — Tenant isolation (highest-severity invariant)

- [ ] **4.1** Seed TWO projects, each with its own entity. Build the tool scoped to project A: `build_get_entity_tool(sm, project_A_id)`.
- [ ] **4.2** Invoke `get_entity` with **project B's** entity id → `ok=False`, `not_found` (NOT `unauthorized`, and NOT the entity — no cross-tenant read, no existence oracle).
- [ ] **4.3** Confirm the model cannot widen scope: `get_entity`'s only argument is `entity_id`; `project_id` is a constructor argument set by Solus code, never present in `ToolCall.args`. Passing `args={"entity_id": <B id>, "project_id": <B>}` → `invalid_args` (extra property rejected), never a cross-tenant read.
- [ ] **4.4** A soft-deleted entity (`deleted_at` set) in the scoped project → `not_found`.

## Flow 5 — Artifact table + scope/access rule

- [ ] **5.1** Insert an `Artifact` via the ORM with only the required fields (project_id, uri, media_type, storage_location, created_by). Re-read it: `scope` is **`PROJECT`** by default (no prompt, silently inherited), `deleted_at` is NULL.
- [ ] **5.2** `artifact_is_accessible(scope=PROJECT, created_by=X, requester_id=Y, requester_has_project_access=True)` → `True`; with `...=False` → `False`.
- [ ] **5.3** `artifact_is_accessible(scope=PRIVATE, created_by=X, requester_id=X, requester_has_project_access=False)` → `True` (creator).
- [ ] **5.4** `artifact_is_accessible(scope=PRIVATE, created_by=X, requester_id=Y, requester_has_project_access=True)` → `False` — a non-creator is denied a PRIVATE artifact **even with project access**.
- [ ] **5.5** `artifact_is_accessible(scope=PRIVATE, created_by=None, ...)` → `False` — an orphaned private artifact (creator deleted) is inaccessible.

## Edge cases / failure paths to exercise

- [ ] **E1** Register two tools with the **same name** → `register` raises `ValueError` (deterministic registry). This is a wiring-time error, correct to raise (not a ToolResult).
- [ ] **E2** Register a tool whose `params` is a **malformed JSON Schema** (e.g. `{"type": "not-a-real-type"}`) → `register` raises `SchemaError` (fail fast at wiring, not first call).
- [ ] **E3** A tool whose handler **sleeps past its `timeout_seconds`** → `ToolResult(ok=False, TIMEOUT, retryable=True)`; the call returns promptly, does not hang.
- [ ] **E4** A tool that raises an **unexpected exception carrying a secret** (e.g. a DSN in the message) → `ToolResult(ok=False, TOOL_ERROR)` with a **generic** message; the secret/DSN text is NOT in `error.message` (it is only in the server log).
- [ ] **E5** A tool that **returns `None`/a non-dict** → `ToolResult(ok=False, TOOL_ERROR)`; `invoke` still does not raise.
- [ ] **E6** Build a `ToolResult` with `ok=True` and no value, or `ok=True` with an error set → Pydantic `ValidationError` (the ok/value/error invariant is enforced).

## Cross-feature interactions

- [ ] **X1** The addition does not disturb existing suites: the full `pytest packages/api` run (Flow 2) includes all prior W0-01/02/03 tests and stays green.
- [ ] **X2** `docs/contracts/model-orchestration.md` (W0-03) is untouched; `docs/contracts/agent-tool.md` (this ticket) reads consistently with it and states that tools and the model router are separate interfaces.

## Not in scope (should be ABSENT — do not test as bugs)

- No MCP/Desktop/Environment tool kinds (documented as future only).
- No S3 bucket, no presigned-URL endpoint, no artifact-upload/creation HTTP flow.
- No HTTP route mounts this registry; it is a standalone contract module like `orchestration/`.
- No SOL reasoning about _how_ to choose a tool.

---

**Pass criteria:** every checkbox above is checked; the full suite, mypy, and ruff are
green; the migration is reversible with a single head; and no `invoke()` path ever raises
or leaks a traceback into a `ToolResult`.
