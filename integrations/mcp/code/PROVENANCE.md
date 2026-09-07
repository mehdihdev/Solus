# Provenance — `code`

> Filled from `integrations/mcp/PROVENANCE.template.md` (SOLUSDEV-250). This server is
> **Solus-authored, no upstream, no vendored tree; license MIT (Solus)**. The template's
> upstream fields are answered honestly below rather than dropped, so the reviewer sees the same
> sections on every fork. An unfilled field voids the sign-offs below.

## Identity

- **Server name:** `code` — equals this directory's name and the `server:` field of
  `allowlist.yaml` (`^[a-z][a-z0-9_]{0,31}$`). Composed tool names: `code.probe_environment`,
  `code.plan`, `code.create_environment`, `code.install`, `code.run`, `code.test`.
- **Spec location:** none — like `local`, the server is not in `MCP_SERVER_CATALOG`
  (`packages/api/src/solus_api/agent/tools/mcp_servers.py`); the cloud reaches it through the
  bridge's `code.*` dispatch (`docs/api/code-environment.md` §4/§5).

## Upstream

- **Repository:** none — Solus-authored, no upstream, no vendored tree. Every file under
  `solus/`, `bin/`, and `tests/` is Solus code.
- **Commit SHA:** n/a (no upstream).
- **Tag / version:** n/a.
- **Fork date:** n/a — authored 2026-09-07 (SOLUSDEV-250).
- **Vendored tree hash:** n/a — there is no `upstream/` or `vendor/`. The reviewed unit is this
  directory itself: reviewers pin `git rev-parse HEAD:integrations/mcp/code` at review time on
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
`integrations/mcp/code/.venv/bin/python3`. That virtualenv is NOT committed —
`scripts/install-mcp-forks.sh` materializes it from `requirements.lock.txt` with hash
verification. `bin/launch` performs zero network I/O and no installs. The installs the server
performs LATER, on confirmation, act on the USER's workspace venv (ADR-031 amendment
2026-09-07) — never on this one.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives THERE.
  DRAFT until human-ratified at the MR (integrations/mcp/CLAUDE.md rule 2).
- **Exposed / upstream total:** `6 / 6` — there is no upstream surface to trim; the server
  registers exactly the six allowlisted tools (`solus/roster.py`, pinned by
  `tests/test_code_allowlist_shape.py` and `tests/test_code_server.py`).
- **Destructive tools:** `create_environment`, `install`, `run`, `test` (all
  `requires_confirmation: true` — they write to, download into, or execute code on the customer
  machine; `run`/`test` are declared interpreter tools per the security template §5).
  `probe_environment` and `plan` are read-only (`plan` is pure).

## Update / rebase policy

- **CVE intake:** the CI dependency-audit job (CLAUDE.md §7) against `requirements.lock.txt`
  on every pipeline, plus GitHub Security Advisories on `modelcontextprotocol/python-sdk` (the
  `mcp` package) — the only third-party code this server runs. The lock is byte-identical to the
  `local` fork's below the header: one advisory triage covers both.
- **Cadence:** no upstream to diff. A CVE in a pinned dependency → regenerate the lock and
  re-materialize within **14 days**.
- **Rebase procedure:** n/a. Dependency bumps: regenerate `requirements.lock.txt`
  (`uv pip compile --generate-hashes --universal --python-version 3.12` over `mcp==<new>`),
  re-run `tests/test_code_lockfile.py`, re-run the §1 + §8 checklist, both devs re-sign.

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
- Any change to the declared env allowlist (`solus/env_allowlist.py`, `solus/env.allow`), the
  pinned binary search roots (`solus/execute.py::SEARCH_ROOTS`), or the declared sandbox posture.
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- Shipping a Windows launcher (`bin/launch.cmd`) — a new entrypoint is a new review.
