# Cowork QA — Local Bridge / Companion (SOLUSDEV-154: BRG-01/02/03/04)

Self-sufficient test plan for the local-bridge feature: a companion process on the user's machine
hosts local MCP tool servers and connects them to the cloud so SOL can call local tools.

## Required setup

- Postgres running (`make db-up`), API running:
  `cd packages/api && uv run uvicorn --factory solus_api.main:create_app --port 8000`
  with `SOLUS_SUPABASE_JWT_SECRET` set (any value; mint matching HS256 tokens below) and
  `SOLUS_BRIDGE_ALLOWLIST_ROOT=packages/companion/tests/fixtures/mcp_root` (exposes the mock
  server — no CAD tool needed).
- A user with a team + project (sign up / use the desktop app once), and a valid access token
  for them (real Supabase token, or HS256-signed with the same secret: claims `sub`, `email`,
  `aud=authenticated`, `exp`).
- Companion (terminal):
  `SOLUS_COMPANION_URL="ws://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/bridge" \
 SOLUS_COMPANION_TOKEN="<TOKEN>" \
 SOLUS_COMPANION_INTEGRATIONS_ROOT="packages/companion/tests/fixtures/mcp_root" \
 uv run python -m solus_companion`
- Desktop app (for UI flows): `pnpm dev:desktop` with the backend above; sign in as the user.

## Flow 1 — connect + tool exposure

1. [ ] Start API, then companion. Companion log shows connect + hello_ack (registered).
2. [ ] `GET /api/v1/projects/<id>/sol/tools` (Bearer token) lists `mock.echo`, `mock.add`,
       `mock.boom`, `mock.sleepy` — and does NOT list `mock.badschema` (gated).
3. [ ] `GET /api/v1/projects/<id>/bridge` → `connected: true`, `companion_version` set,
       servers list shows `mock` as `ready` (after the first status snapshot).
4. [ ] In the desktop app TopBar, the Bridge pill shows "Bridge" (ready); its popover lists
       `mock — ready`.

## Flow 2 — live tool round-trip through SOL

1. [ ] In the app's SOL chat (or `POST .../sol/conversations` + message), ask something that
       invokes `mock.echo` (or drive the registry from a python shell per the completion report).
2. [ ] The result returns; companion log shows the tool_call; `mock` flips busy→ready in the
       pill during a `mock.sleepy` call.
3. [ ] `mock.boom` produces a structured tool error in the SOL stream — never a crash/traceback.

## Flow 3 — offline / not-launched / busy distinction (BRG-03 AC)

1. [ ] Kill the companion (Ctrl-C). Within ~60 s `GET /bridge` → `connected: false`; the pill
       shows "Bridge offline"; a SOL call to `mock.echo` fails fast with a retryable
       "bridge offline" (`unavailable`) error — the app stays fully usable on synced graph data.
2. [ ] Restart the companion → pill returns to ready without any duplicate entities appearing
       anywhere (spot-check an entity list count before/after).
3. [ ] Edge: start a second companion for the same user+project (same command, second terminal)
       → the FIRST one is superseded (closes, does not reconnect); only one stays live.

## Flow 4 — auth boundaries (security)

1. [ ] Companion with a garbage/expired token: connects are rejected (4401 in its log); nothing
       appears in `GET /bridge`.
2. [ ] A token for user B (non-member) against A's project URL: rejected (4404); B's
       `GET /bridge` on that project returns 404.
3. [ ] Teammate check: user B (member) polling `GET /bridge` sees `connected: false` while A's
       companion is live — bridge state is per-user by design.
4. [ ] Grep the API logs for the token string and any tool arguments/results: none present.

## Flow 5 — desktop bundling (BRG-04, Linux best-effort)

1. [ ] `make companion-bin` → `dist/companion/solus-companion` exists; running it bare prints a
       config error (expected — it needs env), proving the binary boots.
2. [ ] `SOLUS_COMPANION_DEV_CMD="uv run python -m solus_companion" pnpm dev:desktop` with the
       companion env vars set: the app auto-starts the companion (pgrep solus/python), the pill
       goes ready after sign-in (token relayed over stdin), quitting the app kills it (pgrep
       empty), `kill -9` the app then relaunch reaps the orphan.
3. [ ] KNOWN GAP: `electron-builder --dir` currently fails under the pnpm workspace (pre-existing
       packaging-infra issue, see COMPLETION_SOLUSDEV-154-brg03-brg04.md) — full AppImage
       validation is deferred to the packaging ticket. Mark this step blocked, not failed.

## Cross-feature checks

- [ ] Sources/graph screens work identically with the bridge offline (no coupling regression).
- [ ] `GET /sol/tools` with the companion disconnected shows only `get_entity` (no stale bridge
      tools).
- [ ] Rate-limit sanity: a companion flooding frames gets disconnected (4429 in its log), the
      API stays healthy.
