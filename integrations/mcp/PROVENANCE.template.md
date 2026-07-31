# Provenance — `<tool>`

> Template (MCP-03). Copy to `integrations/mcp/<tool>/PROVENANCE.md` and fill every field.
> An unfilled field, or a stale vendored-tree hash, voids the sign-offs below.

## Identity
- **Server name:** `<tool>` — must equal `MCPServerSpec.name` and this directory's name
  (`^[a-z][a-z0-9_]{0,31}$`).
- **Spec location:** `packages/api/src/solus_api/agent/tools/mcp_servers.py::<CONST>` — the one
  spec that binds to this fork.

## Upstream
- **Repository:** `<https URL>` — the canonical upstream, not a mirror.
- **Commit SHA:** `<40-hex>` — the exact commit vendored. Tags move; SHAs don't.
- **Tag / version:** `<vX.Y.Z or "none">` — human-readable anchor for the SHA.
- **Fork date:** `<YYYY-MM-DD>` — when `upstream/` was imported at that SHA.
- **Vendored tree hash:** `<git tree SHA of upstream/>` — recompute with
  `git rev-parse HEAD:integrations/mcp/<tool>/upstream`. Any change to `upstream/` changes this
  hash and mechanically voids the sign-offs (proposed CI recomputes and fails on mismatch).

## License
- **SPDX:** `MIT` | `Apache-2.0` — nothing else ships as a fork (stricter than
  `metadata-extraction.md` §6.6; no LGPL, no GPL, no sign-off path around it).
- **LICENSE file:** `upstream/LICENSE` — retained verbatim, never edited.
- **NOTICE (Apache-2.0 only):** `upstream/NOTICE` preserved verbatim and shipped with every
  distribution of the fork; write `n/a` for MIT.
- **Copyright:** original headers retained in all `upstream/` files; Solus headers only on files
  under `solus/` and `bin/`.

## Local modifications
One row per in-tree edit to `upstream/` (files under `solus/` and `bin/` are Solus-authored and
need no rows). An `upstream/` edit without a row here fails review; prefer `solus/` shims.

| Date | File(s) | What & why | Author |
|---|---|---|---|
| | | | |

## Exposed tools
- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives THERE.
  This section only summarizes.
- **Exposed / upstream total:** `<n> / <m>` — the ratio a reviewer sanity-checks. Exposing
  everything (m/m) requires a written justification.
- **Destructive tools:** `<names with requires_confirmation: true>`.

## Update / rebase policy
- **CVE intake:** `<the concrete mechanism — e.g. GitHub security advisories + Dependabot on a
  Solus-owned watch fork of upstream>` — name who/what watches, not "we monitor".
- **Cadence:** quarterly upstream diff review; a CVE affecting a shipped code path → re-vendor
  within **14 days**.
- **Rebase procedure:** re-import `upstream/` at the new SHA as a fresh verbatim commit, replay
  Solus-authored changes, update SHA + tree hash above, re-run the security checklist (scoped
  re-review rules in `SECURITY_REVIEW.template.md` §8).

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
- Any change to `bin/launch`, the `solus/` env allowlist, or the declared sandbox posture.
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- For url-transport specs bound to this record: any endpoint URL change.
