# Provenance — `brave`

> Filled from `integrations/mcp/PROVENANCE.template.md` (SOLUSDEV-252 P6, lane P6-brave).
> An unfilled field, or a stale vendored-tree hash, voids the sign-offs below.
> **Human decision 2026-09-07:** this Pattern-1 fork is launched **CLOUD-SIDE by the API**
> (`agent/tools/mcp_tool.py::_open_session`), not by the companion — the companion does not
> ship Node. ADR-031 describes Pattern 1 as companion-launched; the cloud-side launch of THIS
> fork is recorded here and in `docs/architecture/sol-research.md`, and needs an ADR-031
> amendment row (orchestrator/human; not written by the lane).

## Identity

- **Server name:** `brave` — equals `MCPServerSpec.name` and this directory's name
  (`^[a-z][a-z0-9_]{0,31}$`; the npm package name `brave-search` carries a hyphen the rule
  forbids, hence `brave`).
- **Spec location:** `packages/api/src/solus_api/agent/tools/mcp_servers.py::WEB_SEARCH` — the
  one spec that binds to this fork (constant name kept: `core/startup_checks.py` and
  `scripts/seed-provider-keys.py` import it).

## Upstream

- **Repository:** `https://github.com/brave/brave-search-mcp-server` — the canonical upstream,
  not a mirror. Vendored from the **npm release artifact**, not a git checkout: the published
  package ships only the compiled `dist/`, and the reviewed code is exactly what runs.
- **Commit SHA:** `none — npm release` — the anchor is the registry artifact:
  `@brave/brave-search-mcp-server@2.1.3`, tarball
  `https://registry.npmjs.org/@brave/brave-search-mcp-server/-/brave-search-mcp-server-2.1.3.tgz`,
  `dist.integrity`
  `sha512-zdbbKxCv16NV1tKUjM06jYVhL/E9JISCSa+cReECFDk9hksvUHLG/NwtbgbXlkEv0TfNqZgA1tIwdrF0ODcI/w==`
  (hex `cdd6db2b10afd7a355d6d2948ccd3a8d85612ff13d24848249af9c45e10214393d864b2f5072c6fcdc2d6e06d796412fd137cda99800d6d23076b174383708ff`),
  `dist.shasum` `d7770c9ba6548d05519526b0ef6b32abbfa8e4a2`. The downloaded tarball's sha512 was
  recomputed locally and matched the registry integrity before extraction.
- **Tag / version:** `2.1.3` — `upstream/package.json` declares the same.
- **Fork date:** `2026-09-07` — when `upstream/` was imported from that tarball.
- **Vendored tree hash:** `2d69236406e2231f08b2122215e09eadeeccd207` — recompute with
  `git rev-parse HEAD:integrations/mcp/brave/upstream`. Any change to `upstream/` changes this
  hash and mechanically voids the sign-offs (`tests/test_launch_entrypoint.py` recomputes it in
  pure Python on every test run).

## License

- **SPDX:** `MIT` — verified against `upstream/LICENSE` and `upstream/package.json`
  (`"license": "MIT"`) before import. Note: the LICENSE file's copyright line reads
  "Copyright (c) 2024 Anthropic, PBC" — the server descends from the MCP reference
  `server-brave-search`; Brave republished it under the same MIT text. Still MIT; retained
  verbatim.
- **LICENSE file:** `upstream/LICENSE` — retained verbatim, never edited.
- **NOTICE (Apache-2.0 only):** n/a (MIT).
- **Copyright:** original headers retained in all `upstream/` files; Solus headers only on files
  under `bin/`, `tests/`, and the Solus-authored `package.json`.

## Local modifications

One row per deviation from a verbatim import of the npm tarball (files under `bin/`, `tests/`,
the fork-root `package.json`/`package-lock.json` are Solus-authored and need no rows). The
import is byte-identical to the tarball's `package/` directory: `dist/` (55 files, including
upstream's 14 `*.test.js` files — kept, never executed), `LICENSE`, `README.md`, `package.json`.

| Date       | File(s) | What & why                                                                                                                                                                   | Author        |
| ---------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| 2026-09-07 | none    | No in-tree edits. All Solus behaviour (interpreter pinning, env scrub, key delivery, tool trimming via upstream's own `BRAVE_MCP_ENABLED_TOOLS` knob) lives in `bin/launch`. | P6-brave lane |

Install-time note (not an `upstream/` edit): `bin/launch` requires `integrations/mcp/brave/node_modules/`,
which is NOT committed — `scripts/install-mcp-forks.sh` (and `infrastructure/docker/api.Dockerfile`)
materialise it with `npm ci --omit=dev --ignore-scripts` from the committed, integrity-pinned
`package-lock.json` (generated with `npm install --package-lock-only` against the Solus-authored
`package.json`, whose `dependencies` are copied verbatim from `upstream/package.json`; no dev
dependencies). `upstream/dist` resolves those modules by Node's parent-directory walk.
`bin/launch` itself performs zero network I/O and no installs.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives THERE
  (all `false`: every tool is a read against `api.search.brave.com`). The whole file is
  human-ratified at the MR.
- **Exposed / upstream total:** `4 / 8` — upstream registers `brave_web_search`,
  `brave_local_search`, `brave_video_search`, `brave_image_search`, `brave_news_search`,
  `brave_summarizer`, `brave_llm_context`, `brave_place_search` (`upstream/dist/tools/index.js`).
  Exposed: `brave_web_search`, `brave_llm_context`, `brave_news_search`, `brave_summarizer`.
  Enforcement is fork-side AND cloud-side: `bin/launch` sets `BRAVE_MCP_ENABLED_TOOLS` to
  exactly this roster (upstream's `isToolPermittedByUser` skips registration of the other
  four — `upstream/dist/server.js`), and the API's discovery filter
  (`mcp_tool._stdio_server_allowlist`) skips anything not in `allowlist.yaml`.
- **Destructive tools:** none. Nothing in the exposed roster writes a file, spawns a process, or
  mutates an external system; the only egress is `GET https://api.search.brave.com/res/v1/...`.
- **Cloud-side launch (this fork only):** the API spawns `bin/launch` per call
  (`MCPTool` per-call session), with `BRAVE_API_KEY` resolved from the SecretStore ref
  `brave_api_key` at spawn (`MCPServerSpec.secret_env`) and `SOLUS_NODE_BIN` forwarded from the
  API process environment (`MCPServerSpec.passthrough_env`) when a fixed-path Node is absent.

## Update / rebase policy

- **CVE intake:** GitHub Security Advisories + Dependabot alerts on a Solus-owned watch fork of
  `brave/brave-search-mcp-server`, plus `npm audit --audit-level=high` against
  `package-lock.json` in the CI dependency-audit job (CLAUDE.md §7) on every pipeline.
- **Cadence:** quarterly upstream diff review; a CVE affecting a shipped code path → re-vendor
  within **14 days**.
- **Rebase procedure:** `npm pack @brave/brave-search-mcp-server@<new>` into a scratch dir,
  verify the tarball sha512 against the registry `dist.integrity`, replace `upstream/` with the
  tarball's `package/` contents in one commit, copy `dependencies` into the fork-root
  `package.json`, regenerate `package-lock.json` (`npm install --package-lock-only`), update
  version + integrity + tree hash above, re-run `bin/launch`'s roster against
  `upstream/dist/tools/index.js`, re-run the security checklist (scoped re-review rules in
  `SECURITY_REVIEW.template.md` §8). Step-by-step in `./README.md`.

## Security review sign-off

Both lines required before the fork ships, and again after any re-review trigger
("reviewed by both devs" — no self-approval, no single-reviewer shipping).

- **Reviewer 1:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`
- **Reviewer 2:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`

## Re-review triggers (any of these voids the sign-offs above)

- Any change to `upstream/` (rebase, backport, in-tree edit) — the tree hash makes this mechanical.
- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**. (Removals and
  false→true shrink surface: one reviewer suffices.)
- Any change to `bin/launch`, the declared env allowlist inside it (pinned by
  `tests/test_launch_entrypoint.py`), the `BRAVE_MCP_ENABLED_TOOLS` roster, or the fixed Node
  candidate list.
- Any dependency added or version-changed in `package-lock.json`.
- A published CVE in any dependency at a version the lockfile pins.
- Any change to the egress host (`api.search.brave.com`) in a re-vendored `upstream/`.
