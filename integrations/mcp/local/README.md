# `integrations/mcp/local/` — the Solus-authored `local` MCP server

The one Pattern-1 (ADR-031) server with **no upstream**: 100% Solus code, launched by the bridge
companion on the user's machine with `SOLUS_MCP_WORKSPACE` = the folder the user linked to a
project (Home › LOCAL FOLDER). It makes a working copy on THIS machine a graph source: the scan
runs here, the path never reaches the API, and "Open in [tool]" launches the desktop app here.

Authoritative tool contract: `docs/api/local-folder.md` §4 (names, argument and result shapes,
caps, skip list, suffix→tool table, digest algorithm, launch commands, the never-raises rule).

## What is in this directory

| Path                    | Contents                                                                                                                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bin/launch`            | The ONLY entrypoint. Fixed argv, `env -i` scrub to the allowlist declared in `solus/env_allowlist.py`, `PATH=/usr/bin:/bin`, fork-private `.venv/bin/python3`, zero network I/O.        |
| `allowlist.yaml`        | `server: local` + the three tools. `open_in_tool` is `requires_confirmation: true`. Single source of truth for discovery, the cloud ingress gate, and `solus/roster.py`.                 |
| `solus/`                | The server: `server.py` (FastMCP entry), `workspace.py` (fail-closed root + confinement), `toolmap.py`, `gitremote.py`, `scan.py`, `detect.py`, `launch.py`, `roster.py`, `env.allow`.   |
| `requirements.lock.txt` | Hash-pinned `mcp` closure, derived from the altium fork's lock (header explains). `make mcp-forks` materializes `.venv/` from it; `.venv/` is gitignored.                                |
| `PROVENANCE.md`         | Identity, license (MIT, Solus), no-upstream statement, exposed tools, blank sign-offs.                                                                                                   |
| `SECURITY_REVIEW.md`    | DRAFT checklist with pasted evidence — awaiting both human sign-offs.                                                                                                                    |
| `tests/`                | Launcher/allowlist/lockfile/provenance law plus unit tests for every module; `uv run pytest integrations/mcp/local -q`.                                                                  |

## Tools

- `scan_folder {}` — git identity (`.git` dir or worktree `gitdir:` file — a pointer or
  `commondir` redirect may only lead inside the folder or under `$HOME`; `[remote "origin"]` url
  with any `user:token@` userinfo stripped, branch, HEAD as the 12-hex short sha), sorted
  tool-relevant files as
  `{parts, size, hash, tool}` (≤ 2000, then `truncated`) where `parts` is the relative POSIX path
  split into segments and `hash` is a 32-hex blake2b-128 over the bytes (null over 32 MiB), a
  blake2b-128 `digest` over `joined-path:hash-or-size` lines, and the installed-tool probe.
  Paths are split and hashes/shas kept under 40 chars because the cloud's ingress redaction
  masks any 40+ char entropic string. Symlinks are never followed or hashed; the walk stops at
  the cap and hashing stops at the byte budget even if a file grows mid-read. Skips `.git`, `node_modules`, `.venv`, `venv`,
  `__pycache__`, `build`, `dist`, `solus-artifacts`.
- `folder_digest {}` — `{digest, truncated}`, the same digest, for the change-signal comparison.
- `open_in_tool {path, tool}` — argv-list launch of `kicad` / `altium` / `vscode` / `system` on a
  workspace-confined path; `launched: false` with a reason otherwise (a spawn failure answers
  the fixed `launch failed` — OS error text stays in the stderr log). Confirmation-gated.

## Platform notes

- macOS: `/usr/bin/open -a <App> -- <path>`; KiCad probed at `/Applications/KiCad/KiCad.app` or
  `/Applications/KiCad.app`, VS Code at `/Applications/Visual Studio Code.app`.
- Linux: `shutil.which("kicad")` / `which("code")`; `system` → `/usr/bin/xdg-open <path>`.
- Windows: documented install roots (`detect.py`), `system` → `os.startfile`. Altium Designer is
  Windows-only. **No `bin/launch.cmd` ships yet** — the companion refuses the server on Windows
  until a human approves a Windows twin (the altium fork's was a human decision).

## Re-review

There is nothing to re-vendor. Any change to `bin/launch`, the env allowlist, `allowlist.yaml`,
or `requirements.lock.txt` voids the sign-offs in `PROVENANCE.md` (its "Re-review triggers").
