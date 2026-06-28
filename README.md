# Solus

Solus is a cross-domain development workspace for robotics teams. It builds a unified graph — the Robotics Context Model — across the tools a team already uses (GitHub, GitLab, KiCad, Onshape, ROS), then reasons over that graph to catch cross-domain problems before they break the robot.

## Getting started

- `make bootstrap` — set up the workspace (dependencies, tooling).
- `make dev-api` — run the FastAPI backend.
- `make dev-desktop` — run the Electron desktop app.

See [`CLAUDE.md`](./CLAUDE.md) for how development works in this repository.

