# Isaac security review — generic model cleanup, 2026-09-24

The current change replaces the pinned model with explicit graph-bound v2 models.
Native assets are UTF-8 declarative URDF plus manifested STL, copied privately
through no-follow descriptors. Every workspace-relative directory is opened from
an owned descriptor. FIFO leaves are opened nonblocking and rejected by regular
file validation. Unknown XML tags/attributes, nested structures, duplicate
singleton elements, DTD/entity/processing declarations, nonfinite values, URLs,
unmanifested meshes and graph/topology/limit mismatch are refused before import.

Independent security review found an encoding-based DTD bypass and blocking FIFO
open. Both are fixed with regression coverage: strict UTF-8 and NUL validation,
a deny-doctype parser target, and nonblocking leaf opens. Re-review passed 54
security/runtime/boundary tests with no remaining blocking scoped findings.
One localized S314 justification documents guarded stdlib XML parsing; no external
parser dependency is assumed inside the user's vendor Python runtime.

Generic trajectories report tracking only. No physical hardware or successful
object manipulation is inferred. Approval scope and ownership isolation remain.
Live generic vendor execution and human release signatures remain outstanding.

## Historical review evidence (2026-09-12; earlier fixed model)

Scope: Solus-authored controller, private JSON-pipe worker, fixed tool schemas,
pinned SO-101 asset closure, native scene adapter, and six centrally gated writes.

Development evidence:

- Raw MCP arguments are strictly validated; no arbitrary method dispatch, code,
  URL, interpreter, script, extension, host, port, PID or environment input exists.
- Native startup and full pinned model import ran on Linux aarch64/NVIDIA GB10.
  Actual joint limits, contact pose and bounded position drive readback were checked.
- Native start/load-preview/load/status/stop through the owned pipe controller ran.
  These were disposable developer fixtures, not self-approved product cards.
- Asset source paths use no-follow descriptors, a complete pinned digest closure,
  bounded reads and a separately verified private copy. No runtime downloads.
- Partial load failure clears model identity and bindings. Applied-but-unverified
  writes retain an explicit uncertain outcome. There is no automatic retry.
- Child environment is built from constants; API/cloud credentials are not inherited.
  Runtime has a private HOME/cache, no controller listener, and owned-process cleanup.
- Independent security review found growing-file and stale-load issues; regression
  tests reproduced both before fixes. The final peer review also reproduced directory-namespace substitution and
  SDK cancellation before targeted fixes: journal links are verified before/after
  publication, and request cancellation closes the exact owned controller.

Declared sandbox posture: installed external Isaac runs with the invoking OS user's
GPU permissions and a closed environment, fixed entrypoint, strict data inputs and
private runtime directory. This is not a network namespace or a complete OS sandbox.
Vendor startup extensions and the full external runtime dependency closure require
release review. Do not claim OS-level network isolation from disabled registry and
telemetry settings alone.

Release gates still pending: final independent review after all root/adapter changes,
offline/reproducible dependency installation and dependency advisory audit, shared
cloud authorization tests, product-flow verification, and both human signatures.

Ordinary verification: 83 tests passed; 786 of 979 source statements covered
(80.29%), excluding native-run coverage. The external NVIDIA adapter remains
primarily covered by recorded native fixtures, not an emulated simulator. Ruff
passes; mypy passes with unavailable external NVIDIA imports ignored.

Independent final peer re-review closed both findings: 30 host artifact, SDK,
controller and worker tests passed; the original directory-substitution sentinel
probe refused publication and preserved the outside sentinel. Request cancellation
is deliberately fail-closed and requires a companion MCP session restart.

# Isaac security review — the user's own stages (SOLUSDEV-322 P4-T1), 2026-11-09 — DRAFT

Append-only entry; nothing above is rewritten. Scope: `solus/{stages,assets,models,actions,
scene,server,controller,runtime,urdf}.py`, `allowlist.yaml`, `solus/env.allow`, `bin/launch`.
Agent-drafted; the two human sign-offs in PROVENANCE.md stay blank.

## 1. Supply chain

- [x] No upstream, no runtime fetch; `bin/launch` unchanged except the `SOLUS_SIM_ROOTS`
      passthrough (`tests/test_runtime_configuration.py::test_launcher_preserves_runtime_but_drops_python_poison`
      pins the exact exported set).
- [x] Lockfile unchanged (MCP 1.29.0, Pydantic 2.13.4, hash-pinned).

## 2. Least privilege

- [x] Stage paths: every `stage_ref` / `dest` is root-relative, matched by the Strict models
      (`^part(/part){0,15}$`, no leading `-`, no `..`), resolved only under `SOLUS_SIM_ROOTS`
      and opened `O_NOFOLLOW` per component with a regular-file leaf
      (`stages.open_stage_file`); the one write (`save_stage`) goes through
      `stages.write_stage_file` (sibling `O_EXCL` temp + rename; symlink/dir/fifo leaf refused).
      Pinned by `tests/test_stages.py::test_stage_paths_confined_to_sim_roots`,
      `tests/test_server.py::test_stage_paths_confined_to_sim_roots`,
      `::test_save_stage_refuses_a_symlinked_destination_and_leaves_the_target_alone`.
- [x] Models: only from the verified store `.solus/sim/models/<sha256>/` (manifest digest ==
      name, every file's bytes match, nothing outside the manifest, no symlink; re-verified
      before every `spawn_at`), reached `O_NOFOLLOW` step by step from the workspace descriptor;
      the legacy `.solus/isaac/models/<sha>` stays read-only for `load_model`. A model file is
      exactly one top-level `.urdf` or `.usd*`; manifests may name only model/mesh/texture
      suffixes — `.py .so .sh` and extension-less entries are refused
      (`tests/test_assets_runtime.py::test_store_refuses_code_ambiguous_models_and_reserved_names`).
- [x] The worker never sees a tool-supplied path: `open_stage` receives the absolute path the
      controller resolved from a confined root; `spawn_at` receives a sha256 and copies the
      verified closure into its private directory; `save_stage` exports into the private
      directory and the controller copies the bytes into the root.
- [x] No shell: no new subprocess site; Isaac runs only through the existing owned worker.
- [x] Names that could become argv options or USD path syntax are refused by the Strict
      models (`Name`, `PrimPath`, `RelPath`; `extra="forbid"`, `strict=True`).
- [x] `open_stage` opens the stage in place and never saves it
      (`tests/test_actions.py::test_open_stage_does_not_write_the_file`); `save_stage` is the
      only write into the user's files and is statically gated (`requires_confirmation: true`).
- [x] Every mutation honours `dry_run` with a complete preview and a fingerprint; the scene
      generation is bumped before any effect and a stale plan is refused
      (`tests/test_actions.py::test_every_stage_mutation_dry_runs_to_a_complete_preview`,
      `::test_stage_actions_guard_the_scene_generation_and_reject_extra_fields`).
- [x] Bounds: 500 stage files per scan, depth 6; 32 manifest files, 72 KiB chunks, 20 MB per
      file, 32 MB per model; 60 s routines at ≤ 0.25 rad/s; one camera frame ≤ 64×64 and a
      64 KiB base64 cap; ≤ 32 articulations.

## 3. Sandbox posture

Unchanged: the owned worker runs with the invoking user's permissions in a private HOME, its
own process group, closed environment (`HOME PATH LANG TMPDIR`). `gui_attach` is `unsupported`
— a stage the user opened in their own Isaac GUI is never attached; only Solus-started headless
sessions exist. **Residual:** the new vendor calls are unverified on hardware (PROVENANCE.md);
their failure modes on a real installation are reported as `mutation_unverified` /
`action_refused`, never as success.

## 4. Secret hygiene

- [x] `env.allow` gains only `SOLUS_SIM_ROOTS`; `SOLUS_MCP_WORKSPACE` stays companion-SET and
      is not a passthrough name. No new `os.environ` reads beyond `SOLUS_SIM_ROOTS`
      (`stages.stage_roots`). Results carry root-relative paths and chunked digests only.

## 5. Open for the human reviewers

- `run_routine` now accepts up to 60 s; the allowlist `timeout_seconds: 55` (human-ratified,
  left unchanged) caps a routine the API will wait for at ~45 s wall time. Raising it to ≥ 75
  is an allowlist decision.
- The existing 8 entries keep static `requires_confirmation: true` while the API gates them
  per call (P2-T3); the gazebo fork's convention is per-call (false). Aligning them is a
  human allowlist decision.

Ordinary verification at this entry: `uv run pytest -q integrations/mcp/isaac/tests` → 199
passed; ruff and `mypy packages/api/src` clean; API `tests/test_isaac_tools.py`,
`tests/test_isaac_connection.py` and the hygiene ratchets green.

# Isaac security review — `spawn_at` model type (SOLUSDEV-322 P5-FIX), 2026-11-09 — DRAFT

Review leftover from P5-T4: `_copy_stored` returned a stored `.usd*` model as
`(model_file, None)` and `scene.spawn_at` handed that file straight to `AddReference`. The
store accepts `.usd*` manifests (`model_file_ambiguous` only asks for exactly one model file),
so a verified store entry could reference arbitrary USD into the user's open stage without the
URDF checks (`check_urdf`: declarative XML, manifested meshes, movable joints).

- [x] `spawn_at` spawns only the URDF models Solus generated. A stored model whose model file
      is not `.urdf` is refused with `{ok: false, code: "unsupported_model_type", reason:
    "Solus spawns only the URDF models it generated; open the user's own USD through
    open_stage instead"}` before any scene call, at dry run and at the write alike; no scene
      generation is spent (`tests/test_actions.py::test_spawn_at_refuses_a_stored_usd_model`).
- [x] The refusal is typed (`actions.RefusedError`) and the worker answers its `.result` as-is;
      nothing raises across the wire. The user's own USD stays reachable only through
      `open_stage` (confined to `SOLUS_SIM_ROOTS`, never saved implicitly).

Verification at this entry: `uv run pytest -q integrations/mcp/isaac/tests` → 202 passed.

# Isaac security review — `exposure: internal`, ratification and sign-off 1 (SOLUSDEV-322 P10), 2026-11-10

Append-only entry; nothing above is rewritten. Scope: `allowlist.yaml` (server-level
`exposure: internal`, commit `e5266473`) and the reviewed tree at `408fb7e2` (`11344120839e21dcd7972c11dd1c38f978c481a3`).

- [x] `allowlist.yaml` server-level `exposure: internal` ratified by Pratham Madaram in chat
      (integrations/mcp/CLAUDE.md rule 2). The sixteen entries are unchanged; the original
      eight keep their human-ratified static `requires_confirmation: true`. Loader test:
      `packages/api/tests/test_bridge_internal_exposure.py`; runtime drops the raw specs by flag
      AND by name (`tests/test_sol_runtime.py`, both paths).
- [x] The API wrappers' per-call hooks honour an `Approval required` preview row from this fork
      (`dynamic_gate.APPROVAL_REQUIRED_LABEL`, commit `b743b0c2`): such a row cards even on a
      Solus-owned session. This fork emits no such row today.
- [x] Reviewer 1 sign-off recorded in `PROVENANCE.md` against `408fb7e2`.
- [ ] Reviewer 2 — a second human; the fork does not ship on one signature.
- [ ] Still open for the human reviewers (§5 of the 2026-11-09 entry): `run_routine`
      `timeout_seconds: 55` versus the 60 s routine cap, and aligning the original eight
      entries' static flag with the gazebo fork's per-call convention — allowlist decisions.

Verification at this entry (P10 rerun, `docs/qa/acceptance/P8-suites.md` §"P10 rerun"):
`uv run pytest -q integrations/mcp/gazebo/tests integrations/mcp/isaac/tests integrations/mcp/tests`
→ 506 passed; Isaac remains fixture-only on this aarch64 host.
