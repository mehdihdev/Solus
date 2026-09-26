# SOLUSDEV-262 — execution dependencies

## Completion audit continuation

CAD acceptance/decline/manual UI and exact database-copy rediscovery are now verified.
The final brief audit found remaining wiring-generation and onboard deployment fixture gaps.
Complete them before final handoff, under the existing autonomous authorization:

- Root owns wiring proposal/acceptance routes, graph evidence, retained-plan checks and API tests.
- MCU worker owns provider pin validation/generation and real compiler verification.
- Wiring UI worker owns presence card, source/run selection and explicit review/accept controls.
- Onboard worker owns the provisioned-target runner/helper and fixture tests. Root integrates
  its confirmation tool; cloud SSH and initial target enrollment are outside this provider.
- Firmware offer worker owns the selected local sketch telemetry-diff offer, reusing the existing
  forced confirmation setting. Actual local folder selection is still a user prerequisite.

Generator and UI consumers use the documented bounded wiring schema. Independent files permit
parallel work; root revalidates source/run/config before compile and immediately before upload.
Fresh code/security review is required after integration; no motion or flash is needed for tests.

The attached user specification is the new design authority for this ticket. The user restored SPEC.md and it is read as product requirements; this plan does not rewrite it. This is a continuation plan,
not a claim that downstream phases have been implemented.

## Phase 0 ownership

- Orchestrator: baseline inspection, private DB snapshot, read-only capture and QA documents.
- QA helper worker: `scripts/qa_approver.py`, `scripts/tests/test_qa_approver.py`,
  `packages/api/tests/test_qa_approver_decide.py`.
- Fresh code/Python and security reviewers: read-only complete Phase 0 diff.

The helper tests precede implementation. No product startup imports it. The helper requires
an explicit verified serial and trusted stored-action/registered-tool attestation; neither
is supplied for live operation while the Uno and registered flash tool are absent.

## Phase 1: document and stabilize the topology seam first

Amend hardware-onboarding architecture, hardware API, hardware-config schema documentation,
hardware wireflow and workspace navigation diagrams. No protected enum/contract change is
currently required: graph kinds and edge types are strings, and validated role attributes can
represent host/mcu/onboard brains and buses. A controller remains one graph entity, both a device
on an upstream bus and a brain owning a downstream bus. Config remains v2 and entity-owned.

Keep physical connectivity separate from manual robot ownership. One host can control two
robots; show per-robot tree projections of one project host rather than duplicate host entities.
Parts preserve provider-owned attributes, UUIDs, external references and canonical links.
Category filtering must use a safe overlay for imported parts rather than mutate provider data.

Build and test validated topology traversal/apply before parallel extractors. Include tenant
scope, cycles, ambiguous parents, unknown identity, bounded evidence, project locking, expected
versions and reviewed application. Evidence is a proposal until accepted.

Sequential migration ownership spans:

- `services/physical_robots.py`: container queries, create/delete and orphan handling.
- `hardware/ownership.py`: current parent, destination validation and reassignment.
- `hardware/store.py`: category creation, part creation, unassigned queries.
- `hardware/runtime.py`: controller-local owned parts and runtime config assembly.
- `hardware/detect.py`: candidate resolution and confirmation.
- `hardware/connections.py`: controller-associated opening/recovery metadata.
- `hardware/bindings.py`: derived endpoint preservation/cache invalidation.
- New topology service and a single-head Alembic data migration.

Preflight live and historical rows. Preserve root/part/CONFIG entry IDs, firmware, calibration,
provenance, disabled bindings and source identity. Moving a root CONFIG to a controller requires
atomic subject/payload/configures-edge updates without changing CONFIG ID. Do not reuse ordinary
reassignment blindly: it intentionally disables bindings. Verify resolver equivalence before and
after migration. Retire category presentation only once retained parts remain reachable. Refuse
unrepresentable downgrade. Restore the private snapshot into a disposable DB for rehearsal before
changing populated data. Never migrate without a verified snapshot.

## Parallel candidates after topology shape is stable

Disjoint extractor owners can handle firmware, repo config, KiCad and onboard observations.
Reuse existing firmware parser, repo parser registry and KiCad graph/net extraction. Do not add
a second KiCad parser or authorize local file reads from provider paths. Every extractor emits
the same bus/device/protocol/address/part-candidate evidence with explicit provenance.

Firmware recognition must distinguish board identity from firmware state. Floating analog pin
values are raw observations, not attached-device identity. A bare-board heartbeat and probe must
have immutable reviewed artifact bytes and identity-resolved upload through a registered
confirmation-requiring tool. The current standalone flash callback is not the decide endpoint.
Host shim is offered as a diff. Onboard deployment is fixture-proven here and live human work.

UI ownership begins after typed shape and API route documentation are stable: brain cards,
brains/buses/devices projection, empty names, one question at a time and category chips.
Migrate imported/provider nodes without rewriting their source-owned fields.

## Phases 2–5

1. W5: verify existing widget graph registration reaches root rendering; add evidence-set decline
   memory and CAD suggestions; API/UI accept, decline, manual attach and no-duplicate proof.
2. L1–L3: brain-fed panels independent of focus; client kinematic viewer with persisted namespaced
   poses and confirmed joint mappings; signal widgets with packet units and persistent rename;
   timestamp-aligned camera/LiDAR fixtures and microversion update.
3. L4–L5: graph-grounded stall evidence and cheap-tier bounded narration; durable artifact runs
   snapshot code/config/parts, compare captured data, explain divergence and scrub playback.
   Real baseline contains no stall; synthetic faults must remain labeled fixtures.
4. S4: surface-aware Guide integration using existing TU09/TU10 surfaces; wire Do-to-Build
   compatibility migration if necessary; read/execute semantics tested and destructive gate intact.
   Existing display labels already say Build. Never approve Onshape writes via the QA helper.

Each phase needs an exact ownership manifest, tests-first implementation and fresh reviews.
Sequence changes sharing ownership/config/runtime contracts; parallelize only disjoint stable
extractor/rendering consumers. No cross-ticket branch work, push, MR or protected-file edits.

## Phase 6

Run full appropriate suites, Ruff, strict mypy, pnpm typecheck, vendor/destructive ratchets,
extended three-machine proof and single-head checks. Classify each acceptance gate as live,
recorded real data, fixture, or human prerequisite; failed/not-run implementation gates remain
explicitly incomplete. Verify helper absent from default configuration and provide a
self-contained Cowork QA document. No prior ticket's green suite counts as this ticket's pass.

## Local software clarification

User clarification: linked repositories are references. Host control software is selected through
the existing local file/folder picker on the companion machine and represented by its authorized
LOCAL source graph entities. A remote repository link does not establish running control code.

## Extraction execution plan

E1 defines the immutable bounded internal evidence model in
`hardware/topology_evidence.py` (complete: 37 tests). E2 consumes that model in Live Bench
firmware/config adapters and extends the existing firmware AST recognizer for bus starts,
analog reads, and includes. E3 consumes the same model for supplied onboard observations and
already-scoped schematic graph relationships. E2 and E3 have disjoint files and can run in
parallel once E1 is stable. E4 extends the common three-machine proof after both are complete.

Adapters do no acquisition or persistence. `None`/unavailable observations are not empty
successful discoveries. Source namespaces and original pin/address evidence survive normalization;
port names, includes and floating inputs never become physical identity claims. Runtime acquisition
and reviewed application need an explicit authorized route plan before integration. Existing
local graph rows alone do not authorize reading paths. All manifests remain scoped to each task.

### Authorized file review implementation

A1 documented the single-file acquisition boundary; A2 adds bounded byte parser entry points;
A3 exposes member-authorized, read-only extraction proposals through private source grants;
A4 reuses the native hardware source picker in brain cards. Same-reference relinks expire review
and require reselection. These proposals do not persist arbitrary topology or operational config.
Remaining acceptance and presence deployment require their own concrete reviewed shapes.

## L2 continuation design (not implemented)

Use the already-planned GET /bench/sim/model and POST /bench/sim/model/rebuild routes for
project-scoped multi-model descriptors and explicit asynchronous regeneration. Model descriptors
include robot/model/source UUIDs, revision, ready/stale/building/unavailable status, bounded
URDF/MJCF artifact reference and confirmed joint/part/device/signal mappings. GET never reads
a native path or rebuilds. Existing one-hour artifact expiry stays intact; regeneration must use
an admitted connector output or explicitly authorized source capability. A linked repository or
Simulation/ graph path does not authorize file reads. The existing singleton vendor model
template is not a generic model-byte producer and its checks must remain intact.

Persist display placement locally by account/project/robot/model using finite translation and
quaternion values, independently of operational CONFIG. The scene is kinematic only, with
namespace isolation, static reasons for unconfirmed mappings, jointless explanation and explicit
stale geometry until a matching new revision is available. Renderer/dependency choice, exact
route schemas/source admission and implementation remain work; this plan does not prove L2.
