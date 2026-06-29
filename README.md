# Solus

Solus is a cross-domain development workspace for robotics teams. It builds a unified graph — the Robotics Context Model — across the tools a team already uses (GitHub, GitLab, KiCad, Onshape, ROS), then reasons over that graph to catch cross-domain problems before they break the robot.

## Getting started

- `make bootstrap` — set up the workspace (dependencies, tooling).
- `make dev-api` — run the FastAPI backend.
- `make dev-desktop` — run the Electron desktop app.

See [`CLAUDE.md`](./CLAUDE.md) for how development works in this repository.

## Run the whole stack (one command)

`pnpm dev:all` brings up Postgres (Docker), the FastAPI backend (`:8000`), and the
Electron desktop app together. Ctrl+C tears them all down.

**Prerequisites:** Docker, [`uv`](https://docs.astral.sh/uv/), pnpm, Node ≥ 22.

**First-time setup:**

1. `pnpm install`
2. Backend env — `cp packages/api/.env.example packages/api/.env`, then set
   `SOLUS_SUPABASE_JWT_SECRET` (Supabase dashboard → Project Settings → API → JWT Secret).
3. Frontend env — `cp apps/desktop/.env.example apps/desktop/.env`, then set
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for the **same** Supabase project.
4. `pnpm dev:all`

The desktop app signs in via Supabase, the backend validates that token, and onboarding
creates a real personal team + project and saves your SOL mode. (Without Supabase env the
app still runs in dev-bypass auth for UI-only work, but API calls are rejected.)

Individual pieces: `pnpm db:up` / `pnpm db:down` (Postgres), `pnpm dev:api` (backend only),
`pnpm dev:desktop` (app only).
