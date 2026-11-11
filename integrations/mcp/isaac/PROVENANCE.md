# Provenance — isaac

Server `isaac` is Solus-authored under `solus/` and `bin/`; no third-party MCP
server source is vendored. The root-owned companion registry binds its launcher.
The sixteen exposed names are exactly `allowlist.yaml` (SOLUSDEV-322 P4-T1 added the
eight user's-own-stage tools; see "Local modifications"). The original six writes keep their
human-ratified static `requires_confirmation: true`; the new writes are gated per call by the
API-side ownership ledger and only `save_stage` is statically gated. Low-level MCP validates
original JSON arguments before coercion.

The external runtime is the user's installed NVIDIA Isaac Sim
`6.0.1-rc.7+main.0.98701505.local` at the reviewed development installation root.
NVIDIA binaries, extensions, licenses, and acceptance records are not redistributed
or modified. `python.sh`, setup script, version, and interpreter identities form
the observed launch fingerprint. This is not a claim that every NVIDIA dependency
has been independently audited or hashed.

## Local modifications (SOLUSDEV-322 P4-T1, 2026-11-09 — the user's own stages)

No `upstream/` tree exists; every row below is a Solus-authored change under `solus/`,
`bin/` or the paper trail. **Vendor API code added in this change is UNVERIFIED ON HARDWARE**:
the branch was built on a Linux aarch64 host where Isaac Sim does not run, so every new
`isaacsim.*` / `pxr` call (`scene.py` stage surface) is written against the Isaac 4.x/5.x API
the existing `load` already uses and is exercised only against stubs and the fixture runtime
(`tests/test_scene.py`, `tests/conftest.py` fake worker). Live validation on an x86_64 NVIDIA
installation is a release gate, not a claim made here.

| File                            | Change                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `allowlist.yaml`                | + `list_stages open_stage find_articulations spawn_at read_state control save_stage put_asset` (8 entries, flags per the plan: only `save_stage` static true). The existing 8 entries are untouched; they now differ from the gazebo fork's per-call convention — a human decision, flagged in the completion report. |
| `solus/env.allow`, `bin/launch` | + `SOLUS_SIM_ROOTS` passthrough (stage roots; confinement root for every stage path).                                                                                                                                                                                                                                 |
| `solus/stages.py` (new)         | Stage roots, bounded USD scan, fd-relative `O_NOFOLLOW` confinement for reads (`open_stage_file`) and the one write sink (`write_stage_file`). The gazebo `worlds.py` shape, named apart.                                                                                                                             |
| `solus/assets.py`               | + `ModelStore`: the chunked `put_asset` store (`.solus/sim/models/<sha256>.partial/` → verify → ONE atomic rename), `ALLOWED_SUFFIXES` with the USD family; `model_asset_directory` reads `.solus/sim/models/<sha>` first and the legacy `.solus/isaac/models/<sha>` still.                                           |
| `solus/models.py`               | `Sensor.kind` widens to `contact\|imu\|camera` (radius only for contact); `Routine` gains `sweep` and the 60 s ceiling (speed cap 0.25 rad/s); strict argument shapes for the stage tools; `sweep_targets`.                                                                                                           |
| `solus/actions.py`              | `StageState` actions (`open_stage spawn_at control save_stage`, `run_routine` sweep), reads (`find_articulations read_state`), complete dry-run previews, private export for `save_stage`, generation guard on every mutation.                                                                                        |
| `solus/scene.py`                | Stage surface (unverified on hardware, see above); `_import_urdf` factored out of `load`; `run` wall time `duration_s + 10`.                                                                                                                                                                                          |
| `solus/urdf.py`                 | `check_urdf` / `movable_joint_names` factored out of `validate_urdf` for store models (`.stl .dae .obj` meshes).                                                                                                                                                                                                      |
| `solus/server.py`               | 16-tool roster; `open_stage` starts the owned session on a confined stage; `save_stage` copies the worker's private export into the root through `write_stage_file`; refusals carry `code`.                                                                                                                           |
| `solus/controller.py`           | `probe` reports `gui_attach: "unsupported"`.                                                                                                                                                                                                                                                                          |
| `solus/runtime.py`              | Worker `OPERATIONS` += the six stage operations.                                                                                                                                                                                                                                                                      |
| `allowlist.yaml`                | SOLUSDEV-322 P10 (2026-11-10): server-level `exposure: internal` (docs/contracts/bridge-protocol.md). No tool entry changed; the owned `isaac.*` wrappers in `agent/tools/isaac_tools.py` are the only model-facing surface. Ratified in chat on 2026-11-10 by Pratham Madaram.                                       |

## Historical model provenance (no longer an active bundled default)

The previously used official SO-101 geometry source is
https://github.com/TheRobotStudio/SO-ARM100 at commit
`eecbe3e0a9ebb23e25ad7b2759b03884c6660903`,
`Simulation/SO101/so101_new_calib.urdf` plus its thirteen referenced STL files.
The Apache-2.0 license is retained verbatim as `SO101-LICENSE`.
The former pinned manifest and installer were removed in the schema-v2 cleanup.
The following digest is retained solely as historical attribution:
The canonical manifest digest is
`a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9`.
No original geometry bytes are modified. Generated USD is a temporary derivative.

`requirements.lock.txt` reuses the repository's reviewed Code server dependency
closure (MCP 1.29.0, Pydantic 2.13.4) with hash verification. The local private
installation succeeded on 2026-09-12. No pip or extension install occurs at launch.
Schema-v2 assets are now explicitly supplied by each project under its authorized
workspace `.solus/isaac/models/<manifest-sha256>/`. No geometry is bundled,
downloaded or selected by default. Retain historical `SO101-LICENSE` attribution.

Updates require a fresh source revision, explicit manifest/digest review, native
import/physics checks, dependency audit and renewed security review. Quarterly
review and a 14-day response to relevant CVEs follow the shared fork policy;
human maintainers own release sign-off and advisory tracking.

This development implementation and agent tests are not substitutes for the two
human shipping signatures below.

## Security review sign-off

Both lines required before the fork ships, and again after any re-review trigger. The
reviewed tree hash is `git rev-parse <commit>:integrations/mcp/isaac`.

- **Reviewer 1:** Pratham Madaram — 2026-11-10 — tree reviewed: `408fb7e2` (`11344120839e21dcd7972c11dd1c38f978c481a3`) — checklist:
  `SECURITY_REVIEW.md §2026-11-10` (recorded by the agent on the reviewer's instruction in chat)
- **Reviewer 2:** `<name>` — `<date>` — tree reviewed: `<commit>` — checklist:
  `SECURITY_REVIEW.md §<date>` — PENDING: a second human (no single-reviewer shipping)
