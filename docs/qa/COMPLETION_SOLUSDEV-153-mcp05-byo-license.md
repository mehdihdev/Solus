# Completion Report — SOLUS-MCP-05 BYO-license tiering + bridge credential capture (SOLUSDEV-153)

**HUMAN GATE: this ticket ends at a security/credentials review.** Everything below is built
review-ready; nothing ships until both devs sign off on the credential-capture path.

## What was built

### Part A — tier catalog + entitlement/license gates

- **`LicenseTier`** (`free` / `byo_paid`) + `license_tier` / `license_secrets` on `MCPServerSpec`
  (`agent/tools/mcp_tool.py`). `license_secrets` = per-TEAM license credential KEY NAMES —
  distinct from `required_secrets` (MCP-01 cloud-key semantics, unchanged).
- **Catalog** (`agent/tools/mcp_servers.py`): free — KICAD, FUSION (personal/free license), plus
  existing ONSHAPE/WEB_SEARCH; byo_paid — ALTIUM (`altium_license`), SOLIDWORKS
  (`solidworks_serial`), AUTOCAD (`autocad_license`). All new stdio specs PROVISIONAL per the
  MCP-03 rule: `command` points at not-yet-existing `integrations/mcp/<name>/bin/launch` paths —
  nothing can spawn or reach a network in tests. `MCP_SERVER_CATALOG` exported, keyed by name.
- **Entitlement as data (ADR-023)**: `PLAN_LIMITS` gains `byo_paid_tools` — BASIC `0` (blocked),
  PRO `None` (unlimited), ENTERPRISE `{}` untouched (custom per deal).
  `check_can_use_byo_tool` (`services/limits.py`) mirrors `check_can_add_integration`:
  `_locked_limits` → `_limit` → cap ≤ 0 raises the 409 `plan_limit_reached` upgrade error;
  no-subscription stays the existing 402. Never a plan-name branch.
- **Data migration `a7c5d2e91f04`** (revises `20af242f48a0`, single head before and after):
  backfills existing `subscription.limits` JSONB — basic rows gain `byo_paid_tools: 0`, pro rows
  explicit `byo_paid_tools: null`, enterprise untouched; downgrade removes the key. Rationale in
  the migration docstring: `_limit()` treats an ABSENT key as unlimited, so unbackfilled BASIC
  rows would get a paid feature for free (fail-open). The SQL lives in module constants and the
  test executes those SAME statements against seeded rows.
- **Invoke-time gate** (`build_license_preflight` in `mcp_servers.py`, wired in
  `runtime.build_sol_registry`): for byo_paid catalog servers only, BridgeTool.invoke runs the
  preflight FIRST — (a) plan entitlement (APIError → `ToolException(UNAUTHORIZED,
retryable=False)` carrying the upgrade message, never the raw repr); (b) every
  `license_secrets` key present under the tenant ref (missing → "Bring your license: configure
  your <server> license in the Solus companion (missing: <key names>)" — names only, never
  values). Free-tier and uncataloged servers: zero new checks. `secret_store=None` fails CLOSED.
  `build_sol_registry` gains optional `secret_store`, threaded from both `routers/sol.py` call
  sites via the existing `SecretStoreDep`. All MCP imports stay function-local — the reasoning
  layer remains MCP-ignorant.
- **Ref convention**: `mcp-license/<team_id>/<server_name>/<key_name>` — ONE definition,
  `license_secret_ref()` in `mcp_servers.py`, shared by gate (read), capture handler (write),
  and status surface. No drift possible.
- **`GET /bridge` graceful surface**: per-server `license_state` — `ready` /
  `bring_your_license` / `upgrade_required` (read-only; one lazy entitlement read per request;
  values only presence-probed).

### Part B — credential capture at the bridge (cloud side)

- **Frames** (`bridge/frames.py`, contract §4 extension rule — NO protocol_version bump):
  inbound `credential_submit` `{"server", "secrets": {name: value}}`, outbound `credential_ack`
  `{"server", "ok", "stored": [names], "error"}`. Frozen, `extra="forbid"`, control-frame 16 KiB
  cap (pre-parse). `CredentialSubmitData` is unloggable by construction: `__repr__`/`__str__`
  redact the secrets mapping; `hide_input_in_errors=True` keeps values out of validation errors
  (which feed drop-reason log lines). Redaction machinery (`redact_value`/`redact_text`)
  untouched.
- **Handler** (`routers/bridge.py::_handle_credential_submit`): server must be cataloged AND
  byo_paid (else `ok=false` + short static reason); every submitted key ∈ `license_secrets`
  (unknown key rejects the WHOLE frame — no partial writes); then per-key
  `secret_store.put(license_secret_ref(session.team_id, server, key), value)` — **team scope
  from the server-bound session, never the frame**. Idempotent overwrite. Data-collection event
  `bridge.license_credentials_submitted` with key NAMES + scope only. Ack carries names only.
- **Never in cloud logs**: the handler never logs the frame or the secrets dict; rejection log
  lines are our own static reason strings; `parse_frame` failure paths log reasons only (never
  raw bytes) for the new types like every other type. Proven by tests (below).

### Part C — docs

- `integrations/mcp/README.md` — "License tiers (MCP-05)" section: rosters, customer-owned
  credentials, ref convention, and the QA statement (**byo_paid tools are validated on customer
  machines — NOT on the in-house QA path; in-house QA covers free-tier tools only**).
- `temp-MCP-05-bridge-credential-frames.md` (repo root, human paste →
  `docs/contracts/bridge-protocol.md`): frame table, size cap, validation rules, never-logged
  guarantee, ref convention, §4 extension-rule note.
- This report.

## Verification

- `uv run ruff check .` — clean.
- `uv run mypy packages/api/src` — clean (108 files, strict; fresh `.mypy_cache`).
- `uv run alembic heads` (packages/api) — exactly one head: `a7c5d2e91f04`.
- `uv run pytest -q` — FULL suite green: **1231 passed, 3 skipped** (~4 min). Run twice by the
  finishing session: at the integrated docs head and again at the final consolidated head.
- Desktop preflight for the Stop-gate: `pnpm --filter @solus/desktop run typecheck` green;
  `lint` carries only the pre-existing renderer data-hook failures (deviations, below).

## Never-in-cloud-logs test evidence (`tests/test_bridge_credentials.py`)

- `test_values_never_in_logs_or_outbound_frames` — **the load-bearing assertion**: `caplog` at
  DEBUG across success, unknown-key rejection, AND a strict-validation failure; three sentinel
  values asserted absent from every log record and every outbound frame.
- `test_model_repr_and_str_redact_values` — repr/str/f-string of the payload model never render
  a value (covers accidental `%s` interpolation).
- `test_submit_stores_under_tenant_ref_acks_names_and_overwrites` — ack + data-collection event
  carry key NAMES only; the event payload is asserted value-free.
- `test_unknown_key_rejected_with_no_partial_write` — wholesale rejection; store empty after.
- `test_oversized_submit_closes_4413_and_stores_nothing` — 16 KiB control cap, existing 4413
  path, nothing parsed or stored.
- `test_cross_tenant_isolation_refs_never_collide` — two teams, same server/key → different
  refs; team A's gate ref never reads team B's value.
- `test_malformed_submit_is_dropped_but_socket_survives` — protocol-violation path, no crash.
- `test_gate_round_trip_with_credentials_from_the_wire` — A↔B: BASIC blocked (upgrade message),
  PRO without license told the missing key NAME, PRO after a real `credential_submit` frame
  passes the gate (remaining failure is bridge-offline UNAVAILABLE, i.e. transport, not
  authorization).
- `test_bridge_status_surfaces_all_three_license_states` — `upgrade_required` →
  `bring_your_license` → `ready` over a live socket.

Plus `tests/test_mcp_license.py` (Part A): catalog/tier/ref unit tests; migration
backfill+downgrade executed against seeded rows; limits checks for BASIC/PRO/custom-cap/no-sub;
gate blocks with upgrade message; names missing keys; passes with stored license;
zero-new-checks for free/uncataloged servers; fails closed without a secret store; preflight
runs BEFORE session lookup (entitlement beats "bridge offline"); catalog specs serialize without
leaking anything.

## Delegated-judgment decisions (for the security review)

1. **`license_secret_ref` + catalog live in `agent/tools/mcp_servers.py`** (not `bridge/`): both
   consumers import it function-locally (runtime's registration loop already does this for
   BridgeTool; the WS router mirrors it), so no import cycle and `bridge/` keeps zero MCP
   imports at module scope. Deliverable 6 allowed judgment here — noted.
2. **Gate shape**: a `preflight` callable passed to `BridgeTool` (not a wrapper class) — smallest
   seam; BridgeTool stays transport-only. Preflight runs BEFORE session lookup so an entitlement
   refusal wins over "bridge offline" (a blocked user sees the upgrade path, not a transport
   error).
3. **Fail-closed default**: no `secret_store` wired → every license key counts as missing → the
   paid tool refuses. A paid feature can fail closed, never open (mirrors the migration
   rationale).
4. **`byo_paid_tools` is boolean-shaped** (0 = blocked, positive/null = entitled) rather than a
   count — there is nothing to count; reading it through `_limit` keeps ADR-023 limits-as-data
   and leaves room for a future per-count cap without a schema change.
5. **Unknown-key rejection ack names the unknown keys** — key NAMES travel back to the
   same-tenant companion for a usable error; values never.
6. **Migration SQL as module constants** so the test executes the exact shipped statements —
   no copied SQL drifting from the migration.
7. **`_handle_parsed` became async and takes `app.state`** — the smallest change that gives the
   credential branch the secret store + sessionmaker without threading new globals.

## Companion-side handoff (bridge loop)

`packages/companion/` was NOT touched (bridge loop territory). As of this ticket the CLOUD
accepts `credential_submit` and replies `credential_ack`; the companion-side capture UI that
collects license values from the user and sends the frame is the bridge loop's follow-on.
The frame shapes they build against are in `temp-MCP-05-bridge-credential-frames.md`.

## Deviations / open items

- **Branch consolidation (done)**: mid-ticket crashes left two defunct agent worktrees holding
  the ticket branch (`agent-ace2c13b9f3540931`) and the interim continuation branch
  `SOLUSDEV-153/mcp-05-byo-license-close` (`agent-a9ec8b525626996c2`); H4 blocks
  `git worktree remove --force`, so the finishing session took the ticket branch via
  `git checkout --ignore-other-worktrees`, fast-forwarded **`SOLUSDEV-153/mcp-05-byo-license`**
  over all interim commits, and deleted the `-verify` interim branch. Owed to the orchestrator:
  remove the two defunct worktrees (their checkouts are now stale) and then delete
  `SOLUSDEV-153/mcp-05-byo-license-close` — it is fully contained in the ticket branch's history;
  deletion stays blocked until its worktree is gone.
- **Prettier mangling of the README root-caused and fixed**: the H7 formatter pass
  (prettier 3.4.0) treats a bare snake-underscore word in markdown prose as an emphasis opener
  and rewrote a cross-line span of the pre-existing "Naming rule" section when the MCP-05 section
  first landed — corrupting the quoted `_SAFE_REMOTE_NAME` character class to `[A-Za-z0-9*.-]`
  and eating spaces around code spans. Fixed by backticking the bare word so the paragraph is a
  prettier fixpoint the hook can no longer rewrite. Gotcha for future .md edits: never leave a
  bare `snake_case` word in prose — backtick it.
- Test fixtures `tests/fixtures/bridge_allowlist/{altium,kicad}/allowlist.yaml` were added so
  the bridge allowlist recognizes those servers in tests — test-only data, not vendor dirs; the
  real vendored forks remain MCP-03 follow-ons.
- `tests/test_shared_models.py::test_plan_default_limits` (not on the ticket's named test list)
  gained the `byo_paid_tools` key — it is the PLAN_LIMITS lock test, so the ticket's own
  ADR-023 data change forced the two-line extension. No other out-of-list file was touched.
- **Pre-existing** desktop `lint` failures (13 errors, react-hooks v7, in graph/settings/sol/
  team/workspace data hooks + `lib/useInterval.ts`) — already flagged in
  `COMPLETION_SOLUSDEV-154-brg03-brg04.md`, untouched by this Python+docs-only ticket; desktop
  `typecheck` is green.
- Human paste owed: `temp-MCP-05-bridge-credential-frames.md` →
  `docs/contracts/bridge-protocol.md` (with the other pending BRG temp files).

---

## Phase-4 review outcome (orchestrator, post-integration — commit ee874fd)

Fresh-context **security-reviewer** and **code-reviewer** passes ran on the integrated diff.
Verdicts: approve-with-fixes / approve; no CRITICAL or HIGH. All MEDIUMs fixed before this gate:

- **M1 fixed** — `credential_submit` is entitlement-gated (a BASIC member can no longer plant or
  clobber the team license); replacement of an already-configured value flags `overwrote` on the
  data-collection event as the tripwire.
- **M2 fixed** — per-connection submit rate bucket (`bridge_credential_submit_rate_per_minute`,
  default 6/min burst 3); unchanged values are not re-written (Secrets Manager quota).
- **M3 fixed** — `GET /bridge` `license_state` and the submit gate use a new NON-LOCKING
  entitlement read (`services/limits.py::user_has_byo_entitlement`); the FOR UPDATE helper had
  pinned the subscription row across Secrets Manager I/O on a poll surface. Cross-team
  `license_state` isolation is now tested directly.
- **L4 fixed** — storage failures become an error ack (socket survives); a wrong-type value
  inside `secrets` is proven leak-free under DEBUG capture; a frame asserting its own scope
  (`team_id`) is proven rejected.

**Accepted-risk / informational findings for the HUMAN GATE to weigh:**
1. Client-side entitlement is inherently soft (security L1): the gate keys off the
   allowlist-gated advertised server name, but the companion controls what an allowlisted tool
   does on the customer's machine — server-side entitlement can never exceed trust in the
   companion. Bounded by the Solus-owned allowlist; stakes are billing evasion on the customer's
   own license/hardware.
2. Migration downgrade strips `byo_paid_tools` from ALL basic/pro rows (not a surgical inverse)
   — restores pre-migration fail-open state on rollback, by design.
3. The 16 KiB control cap for `credential_submit` is enforced after `json.loads` (matches
   existing control-frame behavior; nothing is logged/stored on that path).
4. A multi-key BYO spec could partial-write on a mid-loop storage failure — every current spec
   has exactly one license key (`ponytail:` note at the call site).
5. Housekeeping owed to a human (H4 blocks force ref deletion): four stale `worktree-agent-*`
   branches carry unmerged mid-crash commits — `git branch -D worktree-agent-a96dee01454ea9f50
   worktree-agent-a9ec8b525626996c2 worktree-agent-aaeeaae79f8989097
   worktree-agent-ace2c13b9f3540931` after a glance.

Final gate at `ee874fd`: ruff clean · mypy --strict clean (108 files) · **1238 passed, 3
skipped** on `solus_test_mcp` · tsc clean · single alembic head `a7c5d2e91f04`.
