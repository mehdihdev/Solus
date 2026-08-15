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
├── PROVENANCE.md            # from PROVENANCE.template.md — provenance, license, sign-offs, tree hash;
│                            #   ONE file per fork, with a SECTION per vendored tree (see two-tree note)
├── SECURITY_REVIEW.md       # dated, filled copies of SECURITY_REVIEW.template.md — APPEND per review,
│                            #   never overwrite (the history of what was reviewed is the point)
├── allowlist.yaml           # curated Solus-owned tool allowlist — single source of truth (below)
├── bin/
│   └── launch               # Solus-AUTHORED pinned entrypoint — the ONLY thing spec.command may name
├── solus/                   # all Solus-authored code: env allowlist, disabled-tool shims,
│                            #   added lockfile if upstream lacks one, wrapper modules
├── upstream/                # verbatim upstream tree at the pinned SHA
│   ├── LICENSE              # retained as-is (MIT or Apache-2.0 only — no other license ships)
│   ├── NOTICE               # if Apache-2.0: preserved verbatim, ships with every distribution
│   └── ...                  # upstream source + upstream's own lockfile
└── vendor/                  # OPTIONAL second vendored tree (two-tree shape, below): a third-party
    ├── LICENSE              #   support LIBRARY the solus/ overlay builds on, verbatim at its own
    └── <lib_package>/       #   pinned SHA — e.g. kicad/vendor/kicad_sch_api/
```

### Two-tree shape (ratified SOLUSDEV-100, F6/F7)

A fork that builds its overlay on a third-party support **library** (not a second server)
vendors that library in a `vendor/` tree **beside** `upstream/`, under the same fork-model
rules — verbatim single import commit at a pinned SHA, F6 exclusion pattern re-evaluated per
tree, every post-import deviation logged. The load-bearing mechanics:

- **One `PROVENANCE.md` per fork, one section per tree.** The vendor tree gets its own
  "Vendored library tree" section carrying its repository, pinned SHA, license verification,
  exclusion/strip rows, and dependency truth — never merged into the upstream rows.
- **Each tree carries its OWN hash**, recomputed independently
  (`git rev-parse HEAD:integrations/mcp/<tool>/upstream` and `…/vendor`). A change to either
  tree voids the fork's shared sign-offs; the sign-off lines pin BOTH hashes.
- The license boundary applies per tree (MIT/Apache-2.0 only). A permissive non-copyleft
  dependency exception (e.g. `sexpdata`, BSD-2-Clause, in the kicad fork) is a human-approved
  row in the vendor section, never a silent import.
- `vendor/` is consumed by `solus/` via `sys.path`, never pip-installed; its pins ride the
  fork's single `requirements.lock.txt`. Nothing under `vendor/` may register MCP tools —
  a fork never gains a second server (`bin/launch` execs the `solus/` entry only).

Reference implementation: `integrations/mcp/kicad/` (upstream `lamaalrajih/kicad-mcp` +
`vendor/` = `circuit-synth/kicad-sch-api`).

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
  into a per-tool private env at **`<tool>/.venv/`**. Never at launch. `bin/launch` performs
  **zero network I/O**.
- **The companion tells the fork where its interpreter is** (CAD-00b). `bin/launch` may not
  resolve one itself: PATH resolution is forbidden, and a PyInstaller-frozen companion's
  `sys.executable` is the *companion binary*, so a launcher that re-execs it re-execs the
  companion. The companion discovers `<tool>/.venv/bin/python`, verifies it resolves inside the
  integrations root and is executable, and passes it as **`SOLUS_MCP_PYTHON`**. A launcher with
  no interpreter exits 78 rather than falling back to an ambient `python3`. See
  `packages/companion/tests/fixtures/mcp_root/mock/bin/launch` for the worked example.
- **cwd is the tool's own directory**, set by the companion.
- **The env allowlist is `<tool>/solus/env.allow`** — one variable NAME per line, `#` comments
  allowed, Solus-authored and reviewed with the fork. Only those names are inherited from the
  host; everything else in the companion's environment stays out. Values Solus *sets*
  (`SOLUS_MCP_PYTHON`, and delivered license credentials once the bridge carries them) are
  applied last, so a hostile ambient value cannot redirect a fork.

## `allowlist.yaml` — the single source of truth for exposed tools

Resolves two holes the bridge contract (BRG-02 §10) assigns to MCP-03: **advertised-descriptor
allowlisting** and the **tool → local-server mapping** (spec.name ↔ this directory;
`{server}.{tool}` qualification).

```yaml
server: delphiscript # == spec.name == this directory's name
# NOTE: no extra fields — `ServerAllowlist` (packages/api/src/solus_api/bridge/
# allowlist.py) is extra="forbid". The exposed/total tool ratio is recorded in
# PROVENANCE.md ("Exposed tools"), NOT here (T1b finding, SOLUSDEV-100).
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

---

## Vendor-run servers: when NOT to fork (CAD-02)

Not every tool becomes a fork. Autodesk ships its own MCP server that runs **on the customer's
machine** — Preferences → General → API → "Fusion MCP Server (Runs locally on this device)",
default port **27182**, available on the free **Personal** tier. Solus connects to it as a client.
There is nothing to vendor: no `bin/launch`, no private env, no `PROVENANCE.md`, and no fork
security review, because no upstream code is being taken.

Declare one with a `url:` in its `allowlist.yaml` instead of a launcher:

```yaml
server: fusion
url: http://127.0.0.1:27182/mcp
tools:
  - name: get_design_info
    requires_confirmation: false
```

Everything else about the allowlist is unchanged — it is still the single source of truth for which
tools are exposed, and per-tool `requires_confirmation` is still Solus-authored.

### Loopback only — this is a security boundary, not a convention

The companion runs **inside the customer's network**. A companion that will dial an arbitrary URL is
an SSRF primitive reachable through whatever can influence an allowlist file, with the cloud
metadata endpoint (`169.254.169.254`) as the classic target. So a `url:` is validated at discovery
and again at connect: `http`/`https` only, host matched exactly against the loopback names or inside
`127.0.0.0/8`. A hostname that merely *starts* with `127.0.0.1` is a different host and is refused.
A non-loopback url refuses the whole server rather than downgrading it to stdio.

### Why the companion is a LICENSING requirement, not an optimisation

This is the durable answer to "why not just run Fusion in the cloud and skip the companion?"

**Autodesk prohibits hosting or multiplexing a licensed seat.** Running Fusion server-side and
exposing it to multiple Solus users through one installation would breach the EULA regardless of how
the networking is arranged. Solus is permitted to drive a customer's own locally licensed instance
as an external client calling *their* loopback — which is precisely what the bridge already does, by
construction.

The legal route for any future **cloud-side** Fusion automation is the **Fusion Automation API via
APS** (pay-per-use), not the local MCP server. If someone proposes moving this into the cloud, that
is the API to reach for, and it is a different integration.

### Personal-tier commercial use

Fusion **Personal** forbids commercial use and generating more than $1,000/year. A paying Solus
customer driving a free-tier Fusion for business work violates Autodesk's terms, and Autodesk
explicitly recommends that integrations warn about it. Solus shows a plain notice at connect and
does **not** block the connection — the licence is the customer's to hold, and refusing to connect
would neither enforce it nor help them.

### Dynamic tooling: never hardcode tool names

The Fusion server is closed source and its tool set is dynamic. Names and schemas come from
`tools/list` at connect. Because there is no source to read, the only honest source for test
fixtures is a **live `tools/list` capture** against a real install — a cheap human step, since the
free tier suffices. Fixtures invented from documentation would be exactly the fabricated-data
failure the vendoring rules exist to prevent.

### Marketplace manifests (informational)

Autodesk's MCP **Tool Manifest** requirements — declaring `tools`, `resources`, `prompts`,
`external_endpoints`, `autodesk_apis_used`, `ai_llm_providers` — apply **only** to servers submitted
for Design-and-Make Marketplace certification. Solus connects to a customer's own local Fusion and
publishes nothing, so CAD-02 is not gated by them. Worth knowing anyway: `allowlist.yaml` is already
manifest-shaped (server, tools, per-tool reason), so publishing later would be a translation rather
than a redesign.
