# Provenance — `local`

> Filled from `integrations/mcp/PROVENANCE.template.md` (SOLUSDEV-249). This server is
> **Solus-authored, no upstream, no vendored tree; license MIT (Solus)**. The template's
> upstream fields are answered honestly below rather than dropped, so the reviewer sees the same
> sections on every fork. An unfilled field voids the sign-offs below.

## Identity

- **Server name:** `local` — equals this directory's name and the `server:` field of
  `allowlist.yaml` (`^[a-z][a-z0-9_]{0,31}$`). Composed tool names: `local.scan_folder`,
  `local.folder_digest`, `local.open_in_tool`.
- **Spec location:** none yet — the server is not in `MCP_SERVER_CATALOG`
  (`packages/api/src/solus_api/agent/tools/mcp_servers.py`); the cloud reaches it through the
  bridge's `local.*` dispatch (`docs/api/local-folder.md` §3/§4). Adding a catalog entry is a
  follow-up outside this directory.

## Upstream

- **Repository:** none — Solus-authored, no upstream, no vendored tree. Every file under
  `solus/`, `bin/`, and `tests/` is Solus code.
- **Commit SHA:** n/a (no upstream).
- **Tag / version:** n/a.
- **Fork date:** n/a — authored 2026-09-07 (SOLUSDEV-249).
- **Vendored tree hash:** n/a — there is no `upstream/` or `vendor/`. The reviewed unit is this
  directory itself: reviewers pin `git rev-parse HEAD:integrations/mcp/local` at review time on
  the sign-off lines below, and any later commit touching this directory is a re-review.

## License

- **SPDX:** `MIT` — Solus-authored code under the repository's license; nothing third-party
  ships from this directory (the runtime dependency closure in `requirements.lock.txt` is
  `mcp` and its transitive dependencies, all MIT/BSD/Apache-2.0, materialized at install time,
  never vendored).
- **LICENSE file:** n/a (no upstream tree to retain).
- **NOTICE (Apache-2.0 only):** n/a.
- **Copyright:** Solus, on every file under `solus/`, `bin/`, and `tests/`.

## Local modifications

No `upstream/` exists, so there are no in-tree edits to log. Solus-authored files need no rows.

| Date | File(s) | What & why | Author |
| ---- | ------- | ---------- | ------ |
|      |         |            |        |

Install-time note: `bin/launch` execs the fork-private interpreter
`integrations/mcp/local/.venv/bin/python3`. That virtualenv is NOT committed — `make mcp-forks`
materializes it from `requirements.lock.txt` with hash verification. `bin/launch` performs zero
network I/O and no installs.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives THERE.
  DRAFT until human-ratified at the MR (integrations/mcp/CLAUDE.md rule 2).
- **Exposed / upstream total:** `3 / 3` — there is no upstream surface to trim; the server
  registers exactly the three allowlisted tools (`solus/roster.py`, pinned by
  `tests/test_allowlist_shape.py` and `tests/test_server.py`): `scan_folder`, `folder_digest`,
  `open_in_tool`.
- **Destructive tools:** `open_in_tool` (`requires_confirmation: true` — launches a desktop
  application on the customer machine). `scan_folder` and `folder_digest` are read-only.

## Update / rebase policy

- **CVE intake:** the CI dependency-audit job (CLAUDE.md §7) against `requirements.lock.txt`
  on every pipeline, plus GitHub Security Advisories on `modelcontextprotocol/python-sdk` (the
  `mcp` package) — the only third-party code this server runs.
- **Cadence:** no upstream to diff. A CVE in a pinned dependency → regenerate the lock and
  re-materialize within **14 days**.
- **Rebase procedure:** n/a. Dependency bumps: regenerate `requirements.lock.txt`
  (`uv pip compile --generate-hashes --universal --python-version 3.12` over `mcp==<new>`),
  re-run `tests/test_lockfile.py`, re-run the §1 + §8 checklist, both devs re-sign.

## Security review sign-off

Both lines required before the server ships, and again after any re-review trigger
("reviewed by both devs" — no self-approval, no single-reviewer shipping). Humans fill these.

- **Reviewer 1:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`
- **Reviewer 2:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`

## Re-review triggers (any of these voids the sign-offs above)

- Any change to `solus/` or `bin/launch` — the directory tree hash pinned on the sign-off lines
  makes this mechanical.
- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**. (Removals and
  false→true shrink surface: one reviewer suffices.)
- Any change to the declared env allowlist (`solus/env_allowlist.py`, `solus/env.allow`) or the
  declared sandbox posture.
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- Shipping a Windows launcher (`bin/launch.cmd`) — a new entrypoint is a new review.
