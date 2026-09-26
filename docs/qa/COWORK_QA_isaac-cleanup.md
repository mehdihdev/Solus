# Isaac cleanup and Node lint handoff

## Setup

Use the SOLUSDEV-262 feature branch after its local origin/main merge. Install
locked workspace dependencies. Run development PostgreSQL/Redis and the normal
Solus API, desktop and authenticated companion; use a verified project member.
For actual vendor execution, install a compatible Isaac runtime and set the
machine launch setting SOLUS_ISAAC_RUNTIME to its absolute installation root
before starting the companion. No runtime is bundled or silently selected.
Native model tests use synthetic fixtures and do not prove GPU execution.

Create an isolated test project and link a disposable workspace through the
normal native picker. Prepare a small fixed/revolute URDF and STL-only mesh
closure, SHA-256 manifest, and its canonical manifest digest. Place the closure
inside .solus/isaac/models/<digest>/ of that workspace. Create the corresponding
project graph links/joints and optional contact-sensor entities. The v2 model
registration body, numeric bounds and request schema are documented in
../api/isaac-development.md and the generated OpenAPI schema. No executable,
external mesh URL, plugin or script may appear in the model.

## Runtime and authorization

- [ ] Start with the runtime setting absent. Open the Isaac connection panel.
  Expect unavailable/unknown installation, no process launch and no fallback path.
- [ ] Set a valid machine runtime location and restart the companion. Connect
  status monitoring. Expect observations only; no robot, simulation or telemetry
  is created merely by connecting.
- [ ] Ask SOL to start the owned simulator. Inspect its complete preview and
  execute only through the existing central authorization flow. Expect an owned
  session; stop it through the same flow. An independently started Isaac process
  must not be terminated.
- [ ] Try a relative/missing runtime setting. Expect refusal, with no attempt to
  resolve a path inside the project or use a developer-specific installation.

## Generic graph model

- [ ] Register a one-joint model without sensors through the authenticated
  simulation-models endpoint. Expect one model root and containment edges to the
  existing bindings; the original entities remain unchanged.
- [ ] Repeat exactly. Expect reuse, no duplicated entities or creation events.
- [ ] Register a different topology/name. Expect a separate valid model, with
  its supplied names and limits rather than a six-joint default.
- [ ] Submit a foreign-project, deleted or inaccessible binding. Expect refusal
  and no partially created model. Repeat without authentication and as a viewer.
- [ ] Open an old schema-v1 model. Expect an actionable reimport requirement;
  its saved graph must not be silently rewritten or removed.

## Import and execution

- [ ] Request load_model for the valid graph model. Inspect the full preview:
  model, links, joint bounds, optional sensors, asset digest and scene replacement.
  Complete the central authorization flow. Expect the selected model only.
- [ ] Change a graph binding or asset after preview. Expect stale/integrity refusal
  before execution; a prior approval must not be replayable.
- [ ] Try an asset symlink, parent traversal, missing mesh, wrong digest, external
  URL, unsupported joint, XML DTD/entity or unsupported element/attribute. Expect
  refusal before any vendor import. Outside sentinel files must remain untouched.
- [ ] Run an explicit bounded joint_trajectory with the complete model joint set.
  Expect observed joint-tracking results, not an inferred grasp or sensor success.
- [ ] Try incomplete/duplicate targets, excessive speed, nonfinite numbers,
  out-of-model limits or an oversized preview. Expect refusal without stepping.
- [ ] Disconnect or cancel during an operation. Expect bounded cleanup, no
  automatic replay, and an honest uncertain state when execution cannot be verified.

## Existing UI regression

- [ ] Open Hardware → Add after the main-branch filename fix. Expect a visible
  panel and preserved existing project proposals/calibration sources.
- [ ] Open Live Bench and its focused widget, recordings and CAD controls. Check
  project switching, failures and cancellation; helper refactors must preserve
  authorization and stale-response guards. Display smoothing remains disabled.
- [ ] Run pnpm lint, pnpm typecheck and pnpm test. Warnings are reported separately
  from lint errors. Run the focused native/cloud Isaac tests on disposable test
  databases only. Do not infer the full hardware demo has passed from these checks.

## Known limits

The runtime adapter remains Linux/POSIX and version-dependent. The safe initial
model subset is bounded URDF/STL with fixed/revolute joints; unsupported formats
must be explicit errors. Existing preview limits remain enforced. No live GPU
run, physical arm motion, firmware flash or fourteen-channel demo acceptance is
claimed by this cleanup. Historical third-party license/provenance records remain.
