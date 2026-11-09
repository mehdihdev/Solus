# P1 acceptance, live proof (SOLUSDEV-321 plan item 6): in-process, scripted adapters, copy of the dev DB

**Verdicts**

- `what is the stall current of servo 3` : **PASS** . `answer_source.source = graph`, `sources = [config]`, cited `[config:93311442-3323-4f9d-aa57-1ce93e566e8b]` (part `servo 3 (joint 3)`) . model calls **0** by `model call start` log lines, **0** by `credit_ledger` usage rows (and 0 scripted-adapter reaches).
- `what commands actuator 5` : **PASS** . `answer_source.source = graph`, `sources = [graph]`, cited `[entity:b523c68d-70fe-4d5c-a389-7afda8710629]` (code_file `fw/fake_arm.ino`) + `[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]` (part `actuator 5 (joint 5)`), message carries the `commands` edge and ``firmware_symbol `fw/fake_arm.ino:15` `` . model calls **0** and **0** (and 0 scripted-adapter reaches).
- `credit_ledger` delta across the two turns: **0** (global 6 -> 6; seeded user 1 -> 1; usage rows 0 -> 0; balance 1000 -> 1000; spent_total 0 -> 0).

Ready to paste into the SDD ledger:

> P1 acceptance (live, in-process, DB copy `solus_sol`, scripted adapters, egress limited to Postgres/Redis): "what is the stall current of servo 3" -> answer_source=graph, sources=[config], citation [config:93311442-3323-4f9d-aa57-1ce93e566e8b] (`servo 3 (joint 3)`, 2 A), 0 model calls; "what commands actuator 5" -> answer_source=graph, sources=[graph], citations [entity:b523c68d-70fe-4d5c-a389-7afda8710629] (`fw/fake_arm.ino`) + [entity:537cad21-62e3-4a01-b6d1-c422f91b050a] (`actuator 5 (joint 5)`), evidence firmware_symbol `fw/fake_arm.ino:15`, 0 model calls; credit_ledger delta 0 (6 -> 6). Report: `docs/qa/acceptance/P1-acceptance-live.md.

## Run identity

| Item | Value |
| --- | --- |
| Run time | 2026-10-26T22:17:11Z to 22:17:14Z (18:17 EDT), exit 0 |
| Branch | `SOLUSDEV-321-sol-checker-algorithm` |
| HEAD at run time | `5ec6c00b` (reflog: HEAD moved to it at 18:15:28 EDT, two minutes before the run). HEAD at task start was `78840b11`. The three commits in between touch only `apps/desktop/.../features/sol/*` (TypeScript): `git diff --name-only 78840b11 5ec6c00b` lists no `.py`, migration, `pyproject` or `uv.lock` file, and `git status` shows nothing modified under `packages/`, `reasoning/`, `integrations/` or `livebench/`. The Python under test is therefore identical at both shas. |
| Database | `solus_sol` (a copy of the dev DB `solus`), asserted from the server side: `select current_database()` = `solus_sol` |
| Alembic revision | `a32000000006` (head, mergepoint) |
| Redis | `redis://127.0.0.1:6390/0`, the branch container `solus-redis-321` (`redis-cli ping` -> `PONG`) |
| Entry used | The SOL HTTP route, as `tests/test_deterministic.py::test_turn_persisted_with_deterministic_envelope` does: `POST /api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages` (SSE), in process through `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, engine)))`. No listening socket, no port. The app lifespan is not run (ASGITransport sends no lifespan events; the tests' `app` fixture is the same). |
| Harness | `/tmp/claude-1000/-home-beeboss-Solus/b4363425-708a-4a34-be1b-a967e4795b25/scratchpad/p1_accept_live.py` (records) and `.../scratchpad/p1_accept_block.py` (checks and formats; runs nothing live). Raw evidence incl. every captured log line: `.../scratchpad/p1_accept_live_result.json`. |
| Command that ran it | `cd /home/beeboss/Solus/packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' uv run --frozen --no-sync python /tmp/claude-1000/-home-beeboss-Solus/b4363425-708a-4a34-be1b-a967e4795b25/scratchpad/p1_accept_live.py` |

## Environment recipe as executed

1. `solus_sol` did not exist (`select 1 from pg_database where datname='solus_sol'` returned nothing). Created inside the container with the prescribed command under `set -o pipefail`: `docker exec solus-db-1 createdb -U solus solus_sol && docker exec solus-db-1 pg_dump -U solus solus | docker exec -i solus-db-1 psql -U solus solus_sol` -> exit 0, 504 lines of psql output, 0 `ERROR`/`FATAL`. Compared with `solus` afterwards: both `a32000000006`, 57 public tables, 1 user, 5 `credit_ledger` rows, pgvector 0.8.2. `solus` was only read (pg_dump, counts).
2. Per-process exports only, never in a `.env`: `SOLUS_DATABASE_URL` and `SOLUS_REDIS_URL`. `SOLUS_TEST_DATABASE_URL` was never set. The harness refuses to start unless the process holds exactly those two `SOLUS_*` names with exactly the prescribed values.
3. Alembic, from `packages/api`, with `SOLUS_DATABASE_URL` set inline on every command (`migrations/env.py` falls back to `DEFAULT_URL` = the live dev DB `solus` when the variable is unset, so an unset variable would have migrated the wrong database). Run as `uv run --frozen --no-sync alembic ...`:
   - `alembic current` (before): `a32000000006 (head) (mergepoint)`
   - `alembic heads`: `a32000000006 (head)`
   - `alembic upgrade head`: no output, nothing to apply
   - `alembic current` (after): `a32000000006 (head) (mergepoint)`
4. No ports: the harness is in process.

## Why no real provider was reachable (four independent layers)

1. **Scripted adapters.** `LlmRunner(adapters={"anthropic", "openai", "google": RefusingAdapter})`; an adapter records being reached and raises, it never answers. Reached: 0 times.
2. **No credentials in the process.** `Settings(_env_file=None, ...)` (no `.env` read), `SOLUS_SECRETS_KEY` / AWS region / Supabase unset (asserted), `type(app.state.secret_store) == InMemorySecretStore` (asserted), `fingerprint_embedding_enabled = False` (no embedding calls). No key was seeded, read or printed; the JWT secret that signs the harness user's token is `secrets.token_urlsafe(32)`, generated per run.
3. **Egress guard.** `socket.socket.connect`, `connect_ex` and `socket.getaddrinfo` were wrapped before anything was imported: only `127.0.0.1`/`::1` on ports 5432 and 6390 may connect, only `localhost`/loopback may be resolved, every attempt is listed. Observed: 5 attempts, **0 denied**; connects `127.0.0.1:5432` x2 and `127.0.0.1:6390` x1, plus 2 resolves of `localhost`.
4. **The route's own research probe failed closed.** Both message requests logged `solus.deps INFO web research unavailable: ToolException code=unauthorized`: `get_sol_registry` runs the Brave MCP discovery per request and `discover_mcp_tools` raises on the missing key before any process spawn or connection (`mcp_tool.py:641-643`). No search or fetch was possible.

## Seed (fresh, nothing reused)

- user `01a17a4a-037d-7911-8aa1-6f0acd0d8e8c` (token minted the way `tests/conftest.py::make_token` does; first request `/users/me` provisioned the user and the one-time `trial_grant`), `sol_mode = guide` (the default), team `01a17a4a-0399-7d9e-a516-5521fad73616`, project `01a17a4a-03b0-7d92-8b70-0e16cb3b44ee` (created through `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects`)
- fake arm via `tests/fixtures/fake_arm.py::seed_fake_arm(db, project_id, user_id=None)`: robot `57f254f3-bd1a-49af-ad0c-05e9f913da3a`, brain `4d14a9ee-8ed1-4d1e-adce-d5f1e5eb05e3`, bus `561c097e-5138-49e2-8abd-773120a8b7eb`, code_file `b523c68d-70fe-4d5c-a389-7afda8710629`, parts 1..6 `a7efd6c5-42de-436d-84a7-f7c273363a54`, `67791d52-193e-4baf-b8f5-b189a304861c`, `93311442-3323-4f9d-aa57-1ce93e566e8b` (servo 3), `590a9bf8-4ace-4edd-8f77-9f06a31a375a`, `537cad21-62e3-4a01-b6d1-c422f91b050a` (actuator 5), `2bd1aa2a-031f-42a1-b88b-a2aac9f9f32a`
- exactly two turns, each in its own fresh conversation, neither retried

# Result block (generated from the recorded JSON by `p1_accept_block.py`)

### Question: `what is the stall current of servo 3`

- verdict: **PASS**
- conversation: `01a17a4a-05ad-73b7-8593-fa905a463195` (fresh); HTTP 200; SSE frames in order: context_used, answer_source, message, done
- `answer_source`: source = `graph`; sources = ['config']
- citations: `[config:93311442-3323-4f9d-aa57-1ce93e566e8b]`
  - `[config:93311442-3323-4f9d-aa57-1ce93e566e8b]` is part 'servo 3 (joint 3)'
- anchors (`context_used.anchors`): `93311442-3323-4f9d-aa57-1ce93e566e8b` (part 'servo 3 (joint 3)') reason = `name_match`
- anchors_dropped: []; dropped: 0; truncated: False
- layers: `graph` tokens=290 sections=1 empty_reason=None
- message text (verbatim, user is in `guide` mode so the fixed Guide note is appended):
  > Stall current of `servo 3 (joint 3)`: 2 A (its hardware config). This comes from the part's hardware config, set in the robot's hardware settings.
- stored assistant turn attrs: {"aborted": null, "action_mode": "guide", "answer_source": "graph", "citations": ["[config:93311442-3323-4f9d-aa57-1ce93e566e8b]"], "sol_mode": "guide", "sources": ["config"], "tool_calls": 0}
- model calls, way 1 (`model call start` log lines this turn): **0**
- model calls, way 2 (credit_ledger `usage` rows for the seeded user, whole run): **0**; scripted adapter reached: **0**
- checks:
  - [x] HTTP 200
  - [x] frames are exactly context_used, answer_source, message, done
  - [x] answer_source.source == graph
  - [x] answer_source.sources == ['config']
  - [x] citations (answer_source, message, stored turn) all equal the expected ids
  - [x] message text carries the expected fact/evidence
  - [x] anchor is the named part with reason name_match
  - [x] layers == [graph]
  - [x] no tool frame, stored tool_calls == 0, no TOOL turn
  - [x] `model call start` log lines == 0
  - [x] scripted adapters reached == 0

Raw frames as received (`event` name, then `data`):

```json
[
 [
  "context_used",
  {
   "anchors": [
    {
     "id": "93311442-3323-4f9d-aa57-1ce93e566e8b",
     "reason": "name_match"
    }
   ],
   "anchors_dropped": [],
   "dropped": 0,
   "layers": [
    {
     "empty_reason": null,
     "layer": "graph",
     "sections": 1,
     "tokens": 290
    }
   ],
   "sections": [
    {
     "citation": null,
     "kind": "graph",
     "tokens": 290
    }
   ],
   "truncated": false
  }
 ],
 [
  "answer_source",
  {
   "citations": [
    "[config:93311442-3323-4f9d-aa57-1ce93e566e8b]"
   ],
   "source": "graph",
   "sources": [
    "config"
   ]
  }
 ],
 [
  "message",
  {
   "citations": [
    "[config:93311442-3323-4f9d-aa57-1ce93e566e8b]"
   ],
   "content": "Stall current of `servo 3 (joint 3)`: 2 A (its hardware config). This comes from the part's hardware config, set in the robot's hardware settings.",
   "role": "assistant"
  }
 ],
 [
  "done",
  {
   "conversation_id": "01a17a4a-05ad-73b7-8593-fa905a463195",
   "turn_id": "01a17a4a-066c-79de-a5a7-84f07721022e"
  }
 ]
]
```

### Question: `what commands actuator 5`

- verdict: **PASS**
- conversation: `01a17a4a-0680-7200-80f7-f1e9a66ffe15` (fresh); HTTP 200; SSE frames in order: context_used, answer_source, message, done
- `answer_source`: source = `graph`; sources = ['graph']
- citations: `[entity:b523c68d-70fe-4d5c-a389-7afda8710629]`, `[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]`
  - `[entity:b523c68d-70fe-4d5c-a389-7afda8710629]` is code_file 'fw/fake_arm.ino'
  - `[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]` is part 'actuator 5 (joint 5)'
- anchors (`context_used.anchors`): `537cad21-62e3-4a01-b6d1-c422f91b050a` (part 'actuator 5 (joint 5)') reason = `name_match`
- anchors_dropped: []; dropped: 0; truncated: False
- layers: `graph` tokens=296 sections=1 empty_reason=None
- message text (verbatim, user is in `guide` mode so the fixed Guide note is appended):
  > `fw/fake_arm.ino` commands `actuator 5 (joint 5)` — firmware_symbol `fw/fake_arm.ino:15`. This comes from the relations in your project graph, kept current by each sync.
- stored assistant turn attrs: {"aborted": null, "action_mode": "guide", "answer_source": "graph", "citations": ["[entity:b523c68d-70fe-4d5c-a389-7afda8710629]", "[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]"], "sol_mode": "guide", "sources": ["graph"], "tool_calls": 0}
- model calls, way 1 (`model call start` log lines this turn): **0**
- model calls, way 2 (credit_ledger `usage` rows for the seeded user, whole run): **0**; scripted adapter reached: **0**
- checks:
  - [x] HTTP 200
  - [x] frames are exactly context_used, answer_source, message, done
  - [x] answer_source.source == graph
  - [x] answer_source.sources == ['graph']
  - [x] citations (answer_source, message, stored turn) all equal the expected ids
  - [x] message text carries the expected fact/evidence
  - [x] anchor is the named part with reason name_match
  - [x] layers == [graph]
  - [x] no tool frame, stored tool_calls == 0, no TOOL turn
  - [x] `model call start` log lines == 0
  - [x] scripted adapters reached == 0

Raw frames as received (`event` name, then `data`):

```json
[
 [
  "context_used",
  {
   "anchors": [
    {
     "id": "537cad21-62e3-4a01-b6d1-c422f91b050a",
     "reason": "name_match"
    }
   ],
   "anchors_dropped": [],
   "dropped": 0,
   "layers": [
    {
     "empty_reason": null,
     "layer": "graph",
     "sections": 1,
     "tokens": 296
    }
   ],
   "sections": [
    {
     "citation": null,
     "kind": "graph",
     "tokens": 296
    }
   ],
   "truncated": false
  }
 ],
 [
  "answer_source",
  {
   "citations": [
    "[entity:b523c68d-70fe-4d5c-a389-7afda8710629]",
    "[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]"
   ],
   "source": "graph",
   "sources": [
    "graph"
   ]
  }
 ],
 [
  "message",
  {
   "citations": [
    "[entity:b523c68d-70fe-4d5c-a389-7afda8710629]",
    "[entity:537cad21-62e3-4a01-b6d1-c422f91b050a]"
   ],
   "content": "`fw/fake_arm.ino` commands `actuator 5 (joint 5)` — firmware_symbol `fw/fake_arm.ino:15`. This comes from the relations in your project graph, kept current by each sync.",
   "role": "assistant"
  }
 ],
 [
  "done",
  {
   "conversation_id": "01a17a4a-0680-7200-80f7-f1e9a66ffe15",
   "turn_id": "01a17a4a-06d8-7792-8dd8-43d2941eb5e9"
  }
 ]
]
```

### Ledger

- before the two turns: {"global_rows": 6, "user_rows": [["trial_grant", 1000]], "user_usage_rows": 0, "balance": 1000, "spent_total": 0}
- after the two turns:  {"global_rows": 6, "user_rows": [["trial_grant", 1000]], "user_usage_rows": 0, "balance": 1000, "spent_total": 0}
- delta across the run: {"global_rows": 0, "user_rows": 0, "user_usage_rows": 0, "balance": 0, "spent_total": 0}
- global `credit_ledger` rows at harness start: 5 (dev DB copy); +1 `trial_grant` written by `/users/me` provisioning before the turns (`[['trial_grant', 1000]]`)

### Reachability evidence

- capture self-check: {"gateway_logger_enabled_for_info": true, "gateway_logger_propagates": true, "handler_attached": true}; secret store: `InMemorySecretStore`
- egress ledger: attempts=5, denied=[], allowed connects={"127.0.0.1:5432": 2, "127.0.0.1:6390": 1}
- scripted adapters reached (whole run): []
- INFO+ log lines by logger: {"httpx": 7, "solus.auth.admin": 1, "solus.connectors.secrets": 1, "solus.deps": 2, "solus.events": 8, "solus.graph.inference": 7, "solus.main": 1, "solus.services.environment_divergence": 7, "solus.services.environment_spec": 7, "solus.toolkb.sharing": 1}
## Deviations from the brief and observations

1. **`create_app(adapters=...)` does not exist.** The signature is `create_app(settings=None, engine=None)`. The scripted-adapter seam is `app.state.agent_runner = LlmRunner(adapters=...)`, assigned after `create_app`, exactly as `tests/test_deterministic.py::test_turn_persisted_with_deterministic_envelope` and `tests/conftest.py::app` do.
2. **`uv run --frozen --no-sync` and `PYTHONDONTWRITEBYTECODE=1`** instead of bare `uv run`, so the shared `/home/beeboss/Solus/.venv`, `uv.lock` and the repo tree could not be touched (another process may be running the suite on that venv).
3. **Ledger expectation, reworded.** The brief expected 0 `credit_ledger` rows for the seeded user. There is exactly 1 (`trial_grant`, +1000), written by the user's first authenticated request (`/users/me` provisioning) before either turn. Model-call rows (`usage`) are 0, and the user's row count (1 -> 1), the global row count (6 -> 6, the dev copy's 5 plus that grant), `balance` (1000) and `spent_total` (0) did not move across the two turns. Cross-checked from outside the harness with psql: 1 ledger row for the user (`trial_grant|1000|1000`), 0 `usage`.
4. **Log capture is broader than asked.** One INFO handler on the root logger (so every `solus.*` and `solus_api.*` logger), not only `solus_api`; the gateway's logger is actually named `solus.orchestration.gateway`. Self-check recorded: enabled for INFO = true, propagates = true, handler attached = true. No record from that logger appeared in the whole run, and no record at all starts with `model call`.
5. **Guide mode.** A fresh user defaults to `guide`, so both messages end with the fixed Solus-authored Guide sentence; the facts are the same ones Expert mode returns.
6. **Left behind in `solus_sol`:** the fresh user, team, project, fake arm, two conversations (4 stored turns: 2 user, 2 assistant, no tool turn), one `trial_grant` ledger row. `solus` (rev `a32000000006`, 1 user, 5 ledger rows, 132 entities, re-read after the run: unchanged), `solus_sol_p1`, every `solus_test_*` database and the container `solus-redis-1` were not touched. Nothing was dropped or killed. No pytest was run.
7. **Concern for the real-provider session (section 5 step 4), read from the code and not exercised here (no key, by design).** `deps.get_sol_registry` runs `discover_research_tools(...)` -> `discover_mcp_tools(WEB_SEARCH, ...)` on every request that resolves the registry, i.e. every message turn, before the first tier decides (`deps.py:~516`; its docstring, `deps.py:447-463`, calls it "process-spawning" and says "discovery runs per request"). With no Brave key it fails fast, as logged above. With a key seeded it would, per that docstring, start the vendored Brave MCP server and list its tools on every turn, first-tier turns included. That is neither a model call nor a search nor a fetch, but it is not free and it sits on the path of a turn the plan describes as "0 model calls". Worth a look before the live session if latency or process count matters.
8. **Working tree and HEAD.** HEAD moved from `78840b11` to `5ec6c00b` during this task (a concurrent P1-T6 desktop fix, three commits), and again to `9ff211a3` after the run finished; the run itself is pinned to `5ec6c00b` by the reflog timestamps. When this report was last checked, `git status --short` listed only `apps/desktop/src/renderer/src/features/sol/*` entries from that concurrent work, none under `packages/`, and none mine. This task changed no repo file; the only file it wrote under the repository is this report (git-ignored workspace). A `uv run pytest -q` from another process was running at the end; it is not mine and was left alone.
