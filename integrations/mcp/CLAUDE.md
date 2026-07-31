# CLAUDE.md — `integrations/mcp/` (extends the root CLAUDE.md)

Rules for agents working under this directory. The root CLAUDE.md §7 applies in full; these are
stricter, not looser. The layout itself is defined in `README.md`; the templates
(`PROVENANCE.template.md`, `SECURITY_REVIEW.template.md`) are the law for every fork.

1. **Never edit `upstream/` without a PROVENANCE modification row.** Prefer a `solus/` shim over
   an in-tree edit. An `upstream/` change without a row fails review, and it voids the fork's
   sign-offs via the vendored-tree hash.
2. **`allowlist.yaml` and PROVENANCE sign-off lines are human decisions.** Agents may DRAFT an
   allowlist for a new fork, but adding a tool to an existing allowlist, flipping any
   `requires_confirmation` true→false, or writing/altering a sign-off line requires a human — flag
   it in the completion report instead.
3. **No fork ships without the gate.** Both sign-offs in `PROVENANCE.md`, pinned to the current
   tree hash, plus a dated passed checklist in `SECURITY_REVIEW.md`. `SECURITY_REVIEW.md` is
   append-only — never rewrite a past review.
4. **`bin/launch` is the only entrypoint.** No spec, script, or doc in this repo may launch a
   vendored server via `npx`/`uvx`/PATH-resolved names or reach into `upstream/` directly.
   `bin/launch` performs zero network I/O; dependencies come from the committed lockfile at
   companion install time.
5. **License boundary:** MIT or Apache-2.0 upstream only. Anything else — including "just a small
   GPL helper" — is a human/legal decision that does not belong in this directory at all.
6. **Telemetry never rides MCP** (Pattern 2 — `docs/contracts/live-connection.md`). A fork that
   starts streaming sensor/runtime data through a tool interface is a design violation: stop and
   flag.
7. Secrets: key NAMES only, ever, anywhere in this tree (specs, docs, tests). Values live in the
   SecretStore/Secrets Manager and reach a server only through the sanctioned delivery seam.
