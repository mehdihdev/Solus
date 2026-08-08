# Cowork QA — Altium MCP fork + BYO-license flow (SOLUSDEV-102)

Self-sufficient test plan for the vendored Altium MCP server fork
(`integrations/mcp/altium/`), the BYO-license capture flow, and the Altium connector's
export paths. Split per the byo_paid QA scope statement (`integrations/mcp/README.md`):
**Solus holds no Altium license, so nothing requiring a live Altium session is provable
in-house.** Section A runs on any dev machine with the running app and this file. Section B
runs only on a customer machine (Windows + licensed Altium Designer) via
`docs/qa/RUNBOOK_altium-customer-validation.md`.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Section A — In-house (no Altium required)

### Required setup

- Postgres running (`make db-up`); API running:
  `cd packages/api && uv run uvicorn --factory solus_api.main:create_app --port 8000`
  with `SOLUS_SUPABASE_JWT_SECRET` set and
  `SOLUS_BRIDGE_ALLOWLIST_ROOT=integrations/mcp` (the real fork allowlists, altium included).
- Desktop app: `pnpm dev:desktop` (or `dev:all`) against that API; sign in.
- **Two teams**: one on BASIC (the default for a fresh team — `byo_paid_tools: 0`) and one on
  PRO (`byo_paid_tools: unlimited`). Upgrade a team via Billing with Stripe test mode; the plan
  only flips via webhook, so `stripe listen` must be forwarding (`pnpm dev:all` auto-starts it).
  Each team needs a project.
- Companion (terminal), pointed at the REAL integrations tree so `altium` is discovered from
  its `allowlist.yaml`:

  ```
  SOLUS_COMPANION_URL="ws://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/bridge" \
  SOLUS_COMPANION_TOKEN="<TOKEN>" \
  SOLUS_COMPANION_INTEGRATIONS_ROOT="integrations/mcp" \
  SOLUS_COMPANION_WORKSPACE="<an empty scratch directory>" \
  uv run python -m solus_companion
  ```

  Note: the altium server itself will not reach `ready` unless its fork venv exists
  (`.venv/` under `integrations/mcp/altium/`, materialized from `requirements.lock.txt`).
  That is fine — every flow below that needs a state names it; the license flows only need
  the server DISCOVERED, not launched.

- A sample Protel netlist for the connector flows (any small one works):

  ```
  [
  U1
  SOIC8
  NE555
  ]
  (
  VCC
  U1-8
  )
  (
  GND
  U1-1
  )
  ```

### Flow A1 — Fork law suite (run first)

1. [ ] `uv run pytest integrations/mcp/altium -q` — all green (launcher posture, tree hash,
       lockfile, trimming, meta-tool death, confinement, write guards, env allowlist,
       offline degrade).

### Flow A2 — Connect an altium source with an inline Protel export (parse-export path)

1. [ ] In the desktop app (PRO or BASIC team — this path is plan-independent), Sources → add
       an `altium` source. The catalog entry shows config fields `export` and `project_path`;
       no credential is required.
2. [ ] Configure `export` with the sample Protel netlist content (leave `project_path` empty)
       and sync.
3. [ ] The graph shows `component` entities (`U1`), `net` entities (`net:VCC`, `net:GND`), and
       `connected_to` relations carrying pins — the shared electrical shape.
4. [ ] Edge: an `export` over the size cap is refused (`export_too_large`) before parsing;
       binary garbage is refused (`export_invalid`); a malformed node line is skipped with a
       `SyncError`, not a crash. (Deeper parser cases: `COWORK_QA_altium-connector.md`.)

### Flow A3 — Entitlement gating: `bring_your_license` vs `upgrade_required`

1. [ ] With the companion connected to the **PRO** team's project:
       `GET /api/v1/projects/<id>/bridge` shows the `altium` server row with
       `license_state: "bring_your_license"`. In the TopBar Bridge popover the altium row
       shows the **Add license** button.
2. [ ] Repeat with a companion connected to the **BASIC** team's project (its own token +
       project): `license_state: "upgrade_required"`; the popover row shows a non-interactive
       **Upgrade required** note — no Add-license button, no modal.
3. [ ] Free-tier control: the `kicad` row shows `license_state: "ready"` and no license
       affordance on either team.

### Flow A4 — Add-license modal end-to-end (companion running, PRO team)

1. [ ] Click **Add license** on the altium row. The popover closes; the modal opens and
       outlives it. It shows exactly one **masked** input, labeled with the key name
       `altium_license`.
2. [ ] Submit a dummy value (e.g. `TEST-LICENSE-SENTINEL-1`). The modal shows success naming
       the key: "License submitted (altium_license)…".
3. [ ] Companion side: exactly one `credential_submit` frame per submit; the cloud ack arrives
       and the altium row's detail text becomes "license stored (altium_license)" on the next
       status frame.
4. [ ] Within ~10 s (the pill's poll), `license_state` flips to `"ready"` and the Add-license
       affordance disappears.
5. [ ] Re-submit with a different value: idempotent overwrite — one ack, still `ready`, no
       duplicate rows, no error.
6. [ ] Hygiene: grep the API logs, companion output, and desktop console for the sentinel
       value — it appears NOWHERE. Key names and scope ids only (the
       `bridge.license_credentials_submitted` event included).

### Flow A5 — Malformed / oversize credential handling (dropped, no crash, nothing logged)

Drive the companion's stdin relay directly: run the companion in a terminal and paste lines
into its stdin (the same channel the desktop app uses).

1. [ ] Non-JSON garbage line → dropped and counted; companion keeps running; nothing echoed.
2. [ ] Valid JSON, unknown server (`{"type":"credential","server":"nope","secrets":{"x":"y"}}`)
       → dropped (not in the discovered set); no frame sent.
3. [ ] A raw line over 32 KiB → refused before parsing; companion alive.
4. [ ] Cloud side: a `credential_submit` with an unknown key name gets `ok: false` with
       `"unknown keys: …"` — the WHOLE frame rejected, no partial write; the socket survives.
5. [ ] In all cases: no crash, no traceback on stdout (the MCP/status channel), and no secret
       VALUE in any log line (drop reasons are static strings).

### Flow A6 — Companion offline behavior

1. [ ] Kill the companion. The Bridge pill goes offline; opening the license modal (if still
       reachable via a stale popover) and submitting shows the static
       "companion not running" error in the modal — no crash, value cleared on close.
2. [ ] `GET /bridge` → `connected: false`; no altium row, no license_state (empty servers list).
3. [ ] The stored license is unaffected: restart the companion → altium row returns with
       `license_state: "ready"` (state derives from Secrets Manager, not the session).
4. [ ] In a plain browser (non-Electron dev build, if available): the modal shows the
       desktop-app-required note instead of a submit path.

### Flow A7 — Degraded `export_netlist` → connector inline-export fallback (ADR-030)

Needs the altium fork venv materialized so the server actually launches (still no Altium —
that is the point: the honest in-house default is Altium unreachable).

1. [ ] With the companion running and the altium server `ready`, invoke `altium.export_netlist`
       through SOL (or the registry). The result is the stable degraded envelope:
       `{"degraded": true, "reason": "altium_unreachable"}` — never an exception, never a crash;
       the server stays `ready`.
2. [ ] Configure the A2 source with BOTH `export` (inline content) and a `project_path`, then
       sync with the companion live: the live-acquisition attempt runs first, receives the
       degraded envelope, **declines cleanly**, and the sync succeeds off the inline export —
       same entities as A2, sync not failed, decline visible in API logs with a reason.
3. [ ] Same sync with the companion offline: acquirer declines with "bridge offline"; inline
       export still wins; no error surfaced to the user beyond the source's normal state.

### Flow A8 — Cross-team isolation (highest-severity invariant)

1. [ ] Team A (PRO) stores its license per A4. Team B (also PRO, own user/companion/project)
       polls `GET /bridge` on ITS project: altium is `"bring_your_license"` — team A's stored
       keys are invisible to B.
2. [ ] The storage ref is team-scoped (`mcp-license/<team_id>/altium/altium_license`) and the
       `team_id` binds from the authenticated session, never the frame: there is no way to
       submit into another team's namespace from a companion (code-level check —
       `test_bridge_credentials.py` covers it; spot-check the ack only ever names YOUR team's
       scope).
3. [ ] A non-member of the project: `GET /bridge` → 404 (no existence leak).
4. [ ] Teammate check: user B (member of team A) polling team A's project sees
       `connected: false` while A's companion is live — bridge state is per-user by design;
       license_state still reflects the TEAM's stored keys once B's own companion connects.

### Flow A9 — Edge cases and empty states

1. [ ] Fresh team, never-connected companion: Sources and graph screens work; the Bridge pill
       shows offline; nothing altium-related errors.
2. [ ] Disconnect mid-modal: open the Add-license modal, kill the companion, submit → static
       "companion not running"/"companion write failed" error; reopening the modal shows
       cleared inputs (values never persisted).
3. [ ] BASIC team cannot reach the modal at all (A3.2) — the entitlement gate is in the UI
       affordance AND the invoke-time gate, not just one.
4. [ ] Restart the API (registry cache dies): after the companion reconnects, states repopulate
       correctly from the single post-hello status snapshot — no stale `ready` for a server the
       companion no longer offers.

### Cross-feature checks

- [ ] KiCad flows (`COWORK_QA_local-bridge.md`) still pass with the altium fork present in the
      same integrations root — discovery of one fork does not perturb another.
- [ ] The connector-level Altium suite (`COWORK_QA_altium-connector.md`) still passes — the
      MCP fork work did not change the parse-export contract.
- [ ] Data-collection events fire for license submission (key names only) and for sync runs.

---

## Section B — Customer-machine (requires Windows + Altium Designer + customer license)

Run via `docs/qa/RUNBOOK_altium-customer-validation.md` (self-sufficient customer
instructions, including install, license entry, and troubleshooting). These are the flows
ONLY a customer can execute; in-house they are permanently ➖.

### Flow B1 — Real DelphiScript bridge round trip

1. [ ] Companion installed, fork venv materialized, `Altium_API.PrjScr` registered and
       `StartMCPServer` running inside Altium (runbook §3).
2. [ ] `altium` server reaches `ready`; `app_get_status` returns the real Altium version and
       active document; the in-Altium status window shows the request.

### Flow B2 — Real reads: `proj_get_bom` / `proj_get_nets` / project tools

1. [ ] With a real project open and focused in Altium: `proj_get_path`,
       `proj_list_documents`, `proj_get_stats` return values matching the open project.
2. [ ] `proj_get_bom` matches the project's actual designators/footprints;
       `proj_get_component_info` on a known designator is correct.
3. [ ] `proj_get_nets` returns the pin-net table AND does not save dirty documents: make an
       unsaved edit, call the tool, confirm the document is still dirty (the pinned
       `force_recompile=False` — a save here is a FAIL).

### Flow B3 — Non-degraded `export_netlist` + live acquisition

1. [ ] `export_netlist` returns `degraded: false` with Protel `content` (or a workspace
       `artifact_path` for large projects); the netlist matches the open project.
2. [ ] A synced altium source configured with `project_path` acquires the LIVE export (not the
       inline fallback) and the graph reflects the real project.

### Flow B4 — Write tools with confirmation

1. [ ] Ask SOL to set a project parameter (`proj_set_parameter`): the desktop shows an explicit
       confirmation with the concrete action BEFORE anything runs. Decline → nothing changes
       in Altium.
2. [ ] Accept → the parameter is set in the real project; re-read confirms.
3. [ ] `sch_set_components_parameters` on a small batch: same confirmation gate; effect visible
       in the schematic; a batch > 500 or a metacharacter-laden name (`=`, `;`, `~~`) is
       refused BEFORE the tool body runs.

### Flow B5 — Pointer-file confinement with live Altium

1. [ ] The IPC exchange lives ONLY under `<workspace>\.eda-agent-ipc\`; request/response files
       appear there during calls and the bridge round trip completes against it (see the
       runbook's "bridge not responding" note — the DelphiScript side's workspace resolution
       against the confined pointer is a specific validation point).
2. [ ] `C:\ProgramData\eda-agent\workspace-path.txt` is not created or modified by the Solus
       launch (record its pre/post state; pre-existing content from a prior upstream install
       must be reported).
3. [ ] A second Altium session / another checkout cannot repoint the running bridge's
       workspace.

### Flow B6 — Failure tolerance on the real bridge

1. [ ] Close Altium mid-session: tools degrade (`altium_unreachable` from `export_netlist`,
       structured errors elsewhere) — the companion and the desktop app survive; reopening
       Altium and re-running `StartMCPServer` restores service without reinstalling anything.
2. [ ] Upstream is experimental (its own warning): if any tool crashes the DelphiScript
       engine, record WHICH tool and the Altium version — the MCP server and companion must
       survive it and report a structured error, not hang.

Results from Section B feed back to Solus via the runbook's reporting section (key names and
status text only — never license values).
