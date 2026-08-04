# `integrations/mcp/kicad/` — vendored KiCad MCP server fork

Solus-owned fork of [`lamaalrajih/kicad-mcp`](https://github.com/lamaalrajih/kicad-mcp) (MIT),
vendored verbatim at pinned SHA `98c9ea41cb393393a8bafd157a93e84431e00afb` per ADR-031 and the
layout law in `../README.md`. It exposes KiCad project/schematic/PCB operations (project
discovery, netlist extraction, DRC via `kicad-cli`, BOM, thumbnails) to SOL as MCP tools running
on the customer's machine, launched and supervised by the bridge companion.

## What is in this directory

| Path                    | Ownership            | Contents                                                                                                                                                                                                              |
| ----------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `upstream/`             | third-party (frozen) | Verbatim upstream tree at the pinned SHA. Never edit without a `PROVENANCE.md` modification row — prefer `solus/` shims.                                                                                              |
| `bin/launch`            | Solus                | The ONLY entrypoint (`MCPServerSpec.command`). Fixed argv, `env -i` scrubbed environment (allowlist declared in the script), fork-private interpreter `.venv/bin/python3`, zero network I/O, zero installs at launch. |
| `requirements.lock.txt` | Solus                | Fully hash-pinned runtime dependencies, exported from upstream's own `uv.lock` at the pinned SHA. The companion install/update step materializes `.venv/` from it with hash verification (never at launch).           |
| `PROVENANCE.md`         | Solus                | Upstream identity, license, vendored-tree hash, modification log, sign-offs.                                                                                                                                          |
| `tests/`                | Solus                | Launcher/provenance/lockfile law, run by root `pytest`.                                                                                                                                                               |

## How the overlay plugs in (T1b, coming)

The Solus hardening overlay lands beside — never inside — `upstream/`:

- `allowlist.yaml` — the single source of truth for exposed tools and per-tool
  `requires_confirmation`. Until it exists, the fork is PROVISIONAL: companion discovery
  (`solus_companion.config.discover_servers`) keys on `allowlist.yaml`, so the server cannot be
  discovered or wired into any registry.
- `solus/` — Solus-authored shims: env allowlist module, disabled-tool registrations for
  non-allowlisted upstream tools, wrapper modules. `bin/launch` gains its `solus/` wiring then;
  any change to it is a re-review trigger.
- `SECURITY_REVIEW.md` — dated, append-only checklist copies; both dev sign-offs in
  `PROVENANCE.md` pin the tree hash. Nothing ships before that gate.

## How to re-vendor (upstream update / CVE response)

A CVE affecting a shipped code path starts the **14-day** re-vendor clock (ADR-031 /
`PROVENANCE.md` update policy; quarterly diff review otherwise):

1. Clone upstream OUTSIDE the repo; check out the new commit SHA; verify `LICENSE` is still MIT
   (anything else: stop — human/legal decision).
2. Delete and re-import `upstream/` byte-verbatim in a single commit, applying the approved
   exclusions (`.git/`, `CLAUDE.md`, `.claude/`, `agents/`, `.mcp.json`, `.github/`) — one
   `PROVENANCE.md` modification row per exclusion that existed upstream.
3. Regenerate `requirements.lock.txt` from the new upstream lock with hashes
   (`uv export --frozen --no-dev --no-emit-project`).
4. Update `PROVENANCE.md`: new SHA, fork date, and vendored tree hash
   (`git rev-parse HEAD:integrations/mcp/kicad/upstream`).
5. Replay Solus-authored changes (`solus/`, `bin/launch`) and re-run
   `uv run pytest integrations/mcp/ -q`.
6. Re-run the security checklist (scoped rules in `../SECURITY_REVIEW.template.md` §8); both
   devs re-sign `PROVENANCE.md` against the new tree hash. The old sign-offs are void the
   moment the hash changes.
