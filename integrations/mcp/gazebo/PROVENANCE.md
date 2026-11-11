# Provenance — `gazebo`

## Identity

- **Server name:** `gazebo` — equals this directory's name and the allowlist `server` field.
- **Spec location:** none — the fork is discovered by the companion from `allowlist.yaml` +
  `bin/launch` (`solus_companion.config.discover_servers`), like `isaac`; the API never spawns it.

## Upstream

Server `gazebo` is Solus-authored under `solus/` and `bin/` (SOLUSDEV-322); no third-party MCP
server source is vendored, so there is no `upstream/` tree, commit SHA or vendored tree hash.
The external runtime is whichever Gazebo family the USER installed — Classic 11 (`gzserver`,
classic `gz`), Ignition Fortress (`ign`) or the new family Garden/Harmonic/Ionic/Jetty (`gz`) —
found ONLY in the directories `SOLUS_GAZEBO_PATH` names. Gazebo binaries, plugins and worlds are
not redistributed or modified. This is not a claim that any Gazebo dependency has been audited.

- **Repository:** n/a (Solus-authored)
- **Commit SHA / Tag:** n/a
- **Fork date:** 2026-11-09
- **Vendored tree hash:** n/a (no upstream).
- **Reviewed tree hash:** `git rev-parse <commit>:integrations/mcp/gazebo` — at the P3-T3 draft
  commit `b6f32d04` it was `924733a2ef6d42ea49a6256a039f27a3bc79d844`; at the reviewed commit
  `408fb7e2` (after the P9 fixes and the P10 `exposure: internal` key) it is `d6e1a8e4383ba4828d2fc905b679eb8755068fdf`. The sign-off
  lines below pin that hash; any later change under `solus/`, `bin/`, `allowlist.yaml` or the
  lockfile changes it and voids the sign-offs.

## License

- **SPDX:** Solus proprietary (no upstream). Gazebo itself (Apache-2.0) is the user's install.
- **LICENSE / NOTICE:** n/a — nothing third-party ships from this directory.

## Local modifications

No `upstream/` tree; every file is Solus-authored.

| File             | Change                                                                                                                                                                                                                                                                            |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `allowlist.yaml` | SOLUSDEV-322 P10 (2026-11-10): server-level `exposure: internal` (docs/contracts/bridge-protocol.md). No tool entry changed; the owned `gazebo.*` wrappers in `agent/tools/gazebo_tools.py` are the only model-facing surface. Ratified in chat on 2026-11-10 by Pratham Madaram. |

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; the 13 names are `probe list_worlds
open_world attach list_models spawn joint_state set_joint_targets control run_routine stop
save_world put_asset`.
- **Exposed / upstream total:** 13 / 13 (Solus-authored surface; nothing hidden). The server
  (`solus/gazebo_server.py`) advertises exactly `tool_args.ARG_MODELS` — pinned equal to the
  allowlist by `tests/test_gazebo_server.py::test_exact_roster_matches_the_allowlist_and_schemas_are_closed`
  and, over the real stdio transport, by `test_stdio_server_answers_initialize_and_advertises_the_allowlisted_roster`.
- **Destructive tools (static `requires_confirmation: true`):** `save_world` — it writes the
  running world back into the user's own file. Every other mutating tool (`open_world spawn
set_joint_targets control run_routine stop`) is gated PER CALL by the API-side ownership ledger
  (`docs/contracts/action-gate.md`, SOLUSDEV-322): no card inside a Solus-started world, always
  a card inside a user-started one. `put_asset` was approved in-chat (plan §1.3 Q1) as an
  additional entry and is listed separately in the completion report.

## Environment passthrough (Q4)

`bin/launch` execs `solus/gazebo_server.py` (the `solus-gazebo` stdio MCP server) under `env -i` and re-exports BY NAME `SOLUS_MCP_WORKSPACE` plus
exactly the variables listed in `solus/env.allow`: `SOLUS_GAZEBO_PATH SOLUS_SIM_ROOTS
GZ_CONFIG_PATH GZ_SIM_SYSTEM_PLUGIN_PATH GZ_SIM_RESOURCE_PATH GZ_PARTITION GZ_IP IGN_CONFIG_PATH
IGN_GAZEBO_SYSTEM_PLUGIN_PATH IGN_GAZEBO_RESOURCE_PATH IGN_PARTITION IGN_IP GAZEBO_MODEL_PATH
GAZEBO_PLUGIN_PATH GAZEBO_RESOURCE_PATH GAZEBO_MASTER_URI GAZEBO_IP LD_LIBRARY_PATH` (the three
`*_IP` names pin the transport interface; added in P9-T6 after a multi-homed host made every
local service call time out). `SOLUS_MCP_WORKSPACE`
is deliberately NOT in `env.allow`: the companion SETS it (only when a project folder is
linked), and `env.allow` names what the companion may copy from its own ambient environment —
listing it there would let an ambient value reach the launcher when no folder is linked and
defeat the exit-78 guard. `LD_LIBRARY_PATH` is a recorded residual (SECURITY_REVIEW.md).

## Dependencies

`requirements.lock.txt` is a byte-identical copy of the isaac fork's reviewed closure (MCP
1.29.0, Pydantic 2.13.4, hash-pinned). Nothing installs at launch; `make mcp-forks` materializes
the private `.venv` from this file with `--require-hashes` (ADR-031).

## Update / rebase policy

- **CVE intake:** the shared fork policy — pip-audit over `requirements.lock.txt` in CI plus the
  maintainers' advisory watch for `mcp` and `pydantic`; Gazebo CVEs are the user's install.
- **Cadence:** quarterly review; a CVE affecting a shipped code path → re-pin within **14 days**.
- **Rebase procedure:** n/a (no upstream); a lockfile change is a re-review trigger.

## Security review sign-off

Both lines required before the fork ships. Human maintainers own release sign-off; agents
draft and never sign.

- **Reviewer 1:** Pratham Madaram — 2026-11-10 — tree reviewed: `408fb7e2` (`d6e1a8e4383ba4828d2fc905b679eb8755068fdf`) — checklist:
  `SECURITY_REVIEW.md §2026-11-10` (recorded by the agent on the reviewer's instruction in chat)
- **Reviewer 2:** `<name>` — `<date>` — tree reviewed: `<commit>` — checklist:
  `SECURITY_REVIEW.md §<date>` — PENDING: a second human (no single-reviewer shipping)

## Re-review triggers

- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**.
- Any change to `bin/launch`, `solus/env.allow`, or the declared sandbox posture.
- Any dependency added or version-changed in the lockfile; a published CVE at a pinned version.
