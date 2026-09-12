# Environment Configuration Convention (SOLUSDEV-147) — RETIRED

The `.env.mega` + `pnpm env:sync` / `pnpm env:gather` mechanism this page described
was removed in commit 698374c. Nothing generates per-package env files any more.

What replaced it: **one root `.env`**, read directly by absolute path by every process
(FastAPI `core/config.py`, the desktop Vite `envDir`, the web `next.config.mjs`).
Copy `env.example` to `.env` at the repo root and fill it in; see docs/WORKTREES.md §2.
Provider API keys additionally need `make seed-secrets` once per database.
