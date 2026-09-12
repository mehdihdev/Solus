# `integrations/mcp/brave/` — vendored Brave Search MCP server fork (cloud-side)

Solus-owned fork of Brave's official
[`@brave/brave-search-mcp-server`](https://github.com/brave/brave-search-mcp-server) (MIT),
vendored verbatim from the npm release `2.1.3` per ADR-031 and the layout law in `../README.md`.
It gives SOL web search and page-content retrieval (`brave_web_search`, `brave_llm_context`,
`brave_news_search`, `brave_summarizer`) for the research loop
(`docs/architecture/sol-research.md`).

**This fork is launched CLOUD-SIDE by the API** (`agent/tools/mcp_tool.py::_open_session`, spec
`mcp_servers.WEB_SEARCH`), not by the bridge companion — the companion does not ship Node, and
the Brave key is a team credential that lives in the cloud SecretStore (`brave_api_key`).

## What is in this directory

| Path                 | Ownership            | Contents                                                                                                                                                                                                                   |
| -------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `upstream/`          | third-party (frozen) | Verbatim contents of the npm tarball (`dist/`, `LICENSE`, `README.md`, `package.json`). Never edit without a `PROVENANCE.md` modification row.                                                                             |
| `bin/launch`         | Solus                | The ONLY entrypoint (`MCPServerSpec.command`). Fixed argv, `env -i` scrubbed environment, Node pinned to `SOLUS_NODE_BIN` or a fixed absolute list (>= 22), key only via `BRAVE_API_KEY`, roster trimmed to the allowlist. |
| `package.json`       | Solus                | Runtime `dependencies` copied verbatim from `upstream/package.json`; no dev deps.                                                                                                                                          |
| `package-lock.json`  | Solus                | Integrity-pinned lock for those dependencies. `scripts/install-mcp-forks.sh` / the API Dockerfile run `npm ci --omit=dev --ignore-scripts` here to materialise `node_modules/` (never committed, never at launch).         |
| `allowlist.yaml`     | Solus                | The single source of truth for exposed tools (4 of upstream's 8) and per-tool `requires_confirmation` (all reads → `false`).                                                                                               |
| `PROVENANCE.md`      | Solus                | Upstream identity (npm version + tarball sha512), license, vendored-tree hash, modification log, sign-offs (blank until both devs sign).                                                                                   |
| `SECURITY_REVIEW.md` | Solus                | Dated, append-only checklist copies with pasted evidence.                                                                                                                                                                  |
| `tests/`             | Solus                | Launcher/allowlist/provenance/lockfile law, run by root `pytest`.                                                                                                                                                          |

## How a call flows

1. SOL's `research` tool (or a direct `brave.*` tool) is dispatched through the registry.
2. `mcp_tool.py` checks the SecretStore ref `brave_api_key` exists (keyless gate — no spawn
   without it), resolves `MCPServerSpec.secret_env` → child env `BRAVE_API_KEY`, forwards
   `SOLUS_NODE_BIN` from the API process if set, and spawns `bin/launch` over stdio.
3. `bin/launch` refuses (exit 78) unless a Node >= 22 resolves from the fixed list or
   `SOLUS_NODE_BIN`, the key is non-empty, and `node_modules/` exists; then execs
   `upstream/dist/index.js --transport stdio` under `env -i` with the declared allowlist.
4. The server issues `GET https://api.search.brave.com/res/v1/...` — its only egress.

## Local development

- Install deps once: `scripts/install-mcp-forks.sh` (needs `node` >= 22 and `npm` on PATH at
  INSTALL time only).
- If your Node 22 is not at `/usr/bin/node`, `/usr/local/bin/node`, or `/opt/homebrew/bin/node`
  (nvm users), export `SOLUS_NODE_BIN=/absolute/path/to/node` in the API process environment.
- Seed the key: `make seed-secrets` (reads `BRAVE_API_KEY` from the root `.env` into the
  SecretStore ref `brave_api_key`; values never enter logs).

## How to re-vendor (upstream update / CVE response)

A CVE affecting a shipped code path starts the **14-day** re-vendor clock (ADR-031 /
`PROVENANCE.md` update policy; quarterly diff review otherwise):

1. `npm view @brave/brave-search-mcp-server@<new> license dist.integrity` — stop unless MIT.
2. `npm pack @brave/brave-search-mcp-server@<new>` into a scratch dir; verify the tarball sha512
   equals the registry `dist.integrity`; extract.
3. Replace `upstream/` with the tarball's `package/` contents in ONE commit (no `node_modules`).
4. Copy `dependencies` from `upstream/package.json` into `./package.json`; regenerate the lock:
   `npm install --package-lock-only --ignore-scripts`.
5. Re-check the tool roster in `upstream/dist/tools/index.js` against `allowlist.yaml` and the
   `BRAVE_MCP_ENABLED_TOOLS` line in `bin/launch`; re-grep egress (`fetch(`) and `process.env`.
6. Update `PROVENANCE.md`: version, integrity, fork date, vendored tree hash; run
   `uv run pytest integrations/mcp/brave -q`.
7. Re-run the security checklist (scoped rules in `../SECURITY_REVIEW.template.md` §8); both devs
   re-sign `PROVENANCE.md` against the new tree hash.
