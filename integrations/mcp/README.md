# `integrations/mcp/` — vendored MCP-server forks (SOLUSDEV-153 MCP-03 / SOLUSDEV-157)

Pattern-1 MCP tools are **forked, Solus-owned MCP servers that run on the customer's machine**,
launched and supervised by the bridge companion (BRG-02/SOLUSDEV-161 — its contract is pending
human paste to `docs/contracts/bridge-protocol.md` from the BRG worktree's temp file) and
exposed to SOL through the untouched W0-04 `ToolRegistry` as the `MCPTool` kind
(`packages/api/src/solus_api/agent/tools/mcp_tool.py`, MCP-01). A forked server is **attack
surface on a customer machine**. This directory is where every such fork lives, and nothing ships
from here without the paper trail this README defines: a provenance/license record
(`PROVENANCE.template.md`) and a passed security review (`SECURITY_REVIEW.template.md`), signed by
**both devs**.

Telemetry is Pattern 2 and NEVER rides an MCP tool interface (`docs/contracts/live-connection.md`,
ADR-029/030) — nothing in this directory may touch the telemetry seam.

## Fork model: full vendored fork, not a patch series

Upstream is committed **verbatim in a single import commit** under `upstream/` at a pinned SHA.
Every Solus change lands as later commits touching `solus/` or `bin/` (preferred) or — logged in
PROVENANCE — `upstream/`. Rationale: the vendored tree is the exact code the two reviewers sign
off and the exact code that runs on customer machines; a patch series over a large third-party
tree rots on every rebase and hides the shipped state. The Solus delta stays recoverable
(`git log -- integrations/mcp/<tool>/upstream/` after the pristine import commit, plus the
PROVENANCE modification log).

## Skeleton — one directory per fork

```
integrations/mcp/<tool>/
├── PROVENANCE.md            # from PROVENANCE.template.md — provenance, license, sign-offs, tree hash
├── SECURITY_REVIEW.md       # dated, filled copies of SECURITY_REVIEW.template.md — APPEND per review,
│                            #   never overwrite (the history of what was reviewed is the point)
├── allowlist.yaml           # curated Solus-owned tool allowlist — single source of truth (below)
├── bin/
│   └── launch               # Solus-AUTHORED pinned entrypoint — the ONLY thing spec.command may name
├── solus/                   # all Solus-authored code: env allowlist, disabled-tool shims,
│                            #   added lockfile if upstream lacks one, wrapper modules
└── upstream/                # verbatim upstream tree at the pinned SHA
    ├── LICENSE              # retained as-is (MIT or Apache-2.0 only — no other license ships)
    ├── NOTICE               # if Apache-2.0: preserved verbatim, ships with every distribution
    └── ...                  # upstream source + upstream's own lockfile
```

## Naming rule

The directory name `<tool>` **must equal** `MCPServerSpec.name` and match
`^[a-z][a-z0-9_]{0,31}$` — lowercase `snake_case`, **no dots** (the dot is the separator in the
registry's composed `{spec.name}.{remote_name}` tool names, MCP-01). Length discipline: today's
code gates the **bare** remote name with `_SAFE_REMOTE_NAME` (`[A-Za-z0-9_.-]{1,128}`) at
discovery and does NOT re-validate the composed name — so this layout imposes the bound instead:
**every `allowlist.yaml` entry must satisfy `len(server) + 1 + len(tool) ≤ 128`**, checkable at
review and in the proposed CI. (Code follow-on, tracked in the MCP-03 completion report:
re-validate the composed name in `discover_mcp_tools` so the bound is enforced mechanically.)

## Launcher and spec binding (the CLAUDE.md §7 pinned-binary rule, made mechanical)

- `bin/launch` is a short **Solus-authored** script — reviewed code, not upstream. It execs the
  tool's private-env interpreter against the `upstream/` entrypoint with a **fixed argv**, a
  **scrubbed environment** (only the env allowlist declared in `solus/`, plus spec-declared
  `env`), and cwd = the project workspace the companion passes in. No PATH resolution anywhere.
- `MCPServerSpec.command = "integrations/mcp/<tool>/bin/launch"` (repo-relative). The companion
  resolves it against its verified install root and **refuses any command that does not resolve
  inside `integrations/mcp/`**.
- Dependencies are materialized at companion **install/update time** from the fork's committed
  lockfile with hash verification (`pip install --require-hashes` / `npm ci --ignore-scripts`)
  into a per-tool private env. Never at launch. `bin/launch` performs **zero network I/O**.

## `allowlist.yaml` — the single source of truth for exposed tools

Resolves two holes the bridge contract (BRG-02 §10) assigns to MCP-03: **advertised-descriptor
allowlisting** and the **tool → local-server mapping** (spec.name ↔ this directory;
`{server}.{tool}` qualification).

```yaml
server: delphiscript # == spec.name == this directory's name
upstream_tool_count: 290 # stated so the exposed/total ratio is reviewable
tools:
  - name: run_script # must pass _SAFE_REMOTE_NAME
    requires_confirmation: true # per-tool, Solus-authored; server destructiveHint is UNTRUSTED
    reason: executes arbitrary DelphiScript on the customer machine
  - name: list_units
    requires_confirmation: false
```

Consumers (all read THIS file — a second copy anywhere is a defect):

1. **Discovery filter** (follow-on code in `discover_mcp_tools` after this format is ratified):
   a server-advertised tool not in the allowlist is skipped with a warning; an allowlisted tool
   the server doesn't advertise is a warning; per-tool `requires_confirmation` comes from the
   entry (the spec's blanket flag stays the default for url-transport servers with no vendor dir).
2. **Cloud bridge ingress**: the companion's `hello` tool inventory is validated against this
   file — companion-advertised descriptors outside it never enter a registry or model context.
3. **Fork-side hardening**: where feasible, a `solus/` shim disables non-allowlisted tool
   registrations so unexposed handlers aren't live in-process; where infeasible, the residual is
   recorded in SECURITY_REVIEW.md.

## Provisional servers — what must happen before a stdio spec ships

A stdio `MCPServerSpec` is **PROVISIONAL** (not wireable into any customer-facing registry) until:

1. `integrations/mcp/<name>/` exists with every file above;
2. `command` points at its `bin/launch` — no `npx`/`uvx`/PATH-resolved names anywhere;
3. `PROVENANCE.md` carries both sign-offs and a current vendored-tree hash;
4. `SECURITY_REVIEW.md` contains a passed, dated checklist for the pinned SHA.

Today's `WEB_SEARCH` spec (`mcp_servers.py`, `npx`-launched) is exactly this provisional state —
unreachable in production because the keyless credential gate precedes any spawn, and marked
`TODO(MCP-03)` for vendoring under this process.

Pure-`url` remote servers (e.g. `ONSHAPE`) are outside vendoring — nothing runs on the customer
machine — but their endpoint URL is pinned in the spec and changing it is a review trigger.

## License tiers (MCP-05)

Every catalog spec (`MCP_SERVER_CATALOG` in
`packages/api/src/solus_api/agent/tools/mcp_servers.py`) carries a `license_tier`:

| tier       | servers (current roster)                                           | what it means                                                                                                                                                                                               |
| ---------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `free`     | `kicad`, `onshape`, `fusion` (personal/free license), `web_search` | Usable on any plan. No customer license credential; zero extra checks at invoke time.                                                                                                                       |
| `byo_paid` | `altium`, `solidworks`, `autocad`                                  | **Bring your own license.** The customer's own paid vendor license, plan-entitled (`byo_paid_tools` limit — BASIC blocked, PRO unlimited, ENTERPRISE per deal) AND license-credential gated at invoke time. |

**License credentials are the CUSTOMER's own.** They are captured in the Solus companion
(the `credential_submit` bridge frame — see `docs/contracts/bridge-protocol.md` once the
MCP-05 addendum is pasted), stored per-team in Secrets Manager under
`mcp-license/<team_id>/<server_name>/<key_name>` (`license_secret_ref`, the single
definition both the capture handler and the invoke gate use), and **never appear in cloud
logs** — acks, events, and error messages carry key NAMES only, values only ever live in
the SecretStore.

The graceful states a user sees (`GET …/bridge` per-server `license_state`):
`ready` · `bring_your_license` (entitled, license not yet configured — the companion
prompts for it) · `upgrade_required` (plan does not include BYO-paid tools).

**QA scope statement:** BYO-paid tools (Altium, SolidWorks, AutoCAD) are validated on
customer machines via this flow — they are **NOT on the in-house QA path**. Solus does not
hold Altium/SolidWorks/AutoCAD licenses; in-house QA covers free-tier tools only. A
byo_paid fork still ships with the full paper trail above (provenance, security review,
allowlist), but its end-to-end validation against the real vendor application happens
customer-side, gated by the customer's own license.

## License policy

Forks: **MIT or Apache-2.0 only.** This is deliberately stricter than the repo's general tiers
(`docs/contracts/metadata-extraction.md` §6.6 — Permissive / LGPL / GPLv3-with-sign-off /
Commercial): code that ships to customer machines admits no copyleft or EULA ambiguity, and there
is no sign-off path around it. Apache-2.0 carries the NOTICE-preservation obligation (the fork
ships `upstream/NOTICE` verbatim). Recommended CI (proposed, human-owned `.gitlab-ci.yml`):
spec↔dir↔allowlist name agreement; PROVENANCE tree-hash recompute; a no-`npx`/`uvx` grep over
stdio specs; and the license/SCA audit job CLAUDE.md §7 already promises.
