# SOLUSDEV-260 Phase 4 execution plan

Execute only after Phase 3 verification and commit. Merge `a43578c` into this
feature branch; never push or modify main. This plan is prepared while the Phase 3
full API suite runs, not evidence that the merge has happened.

## Governing design

User Phase 4 packet; ADR-025/031/034; code-environment, sol-in-tools, solus-folder
and workspace architecture; code-environment, hardware and solus API plans;
sol-page and incoming sol-window wireflows; action-gate and agent-tool contracts.
The user has explicitly approved the incoming bridge hello size amendment.

## Tasks and dependency graph

P4-0 (root): merge and reconcile runtime/confirmation/bridge and documentation
conflicts. Keep both MAIN declarations. Freeze the existing asynchronous
`fetch_environments` seam before parallel work. Resolve the solus API prose against
one environment executor and direct per-entity hardware writes.

Then run P4-H and P4-E concurrently with root P4-G:

- P4-H owns API `agent/tools/solus_tools.py`, `make_diagram.py`, their dedicated
  tests. Use runtime aggregation for diagrams; use v2 directly for confirmed
  hardware field updates, preserving unrelated values/provenance and expected
  versions. Preserve the environment linker's callback interface unchanged.
- P4-E owns runtime/confirmation environment wiring, bridge previews, the CODE
  recording service and new I3 observation adapter, corresponding tests, and the
  duplicate companion/machine environment implementation. I3 is the only executor.
  Preserve non-environment machine functionality. Return only observed facts;
  refuse capabilities I3 lacks rather than inventing interpreters/packages or
  retaining another executor. Every create/install/run remains approval-gated.
- P4-G (root) owns `services/solus_config.py`, `solus_graph.py`, corresponding tests,
  renderer CONFIG dispatch and CodeEnvironmentCard. Scope hardware interpretation
  by section so CODE recording and hardware entries coexist. Existing database
  constraints already permit CODE CONFIG null subject/version zero; no migration
  is planned. Root also owns docs and generated schemas.

P4-H + P4-E + P4-G → P4-V (root integrated verification/reviews/live gates).
Root writes exact ownership manifests after the merge; transfer ownership before
any I3 server change or unexpected cross-task file edit. Two implementation workers
maximum; the planner remains read-only. Tests precede fixes.

## Verification targets

Critical regressions: diagram v2 and safe builder failure; approved one-field edit
on firmware-bearing robot preserves unrelated data; preview purity and stale
refusal. Environment: real-shaped I3 observations, absent/malformed probes,
unsupported actions, exact preview/execution argv, decline/stale executes nothing,
one error filing, one advertised executor. CODE/HARDWARE CONFIG creation, rendering,
update and removal coexist without changing hardware retirement security.

Then verify 252's eleven defect regressions, registry dispatch ratchets, one
Alembic head, all affected/full suites and language/security review. Launch this
checkout's real companion and verify hello/fork ownership; seed configured provider
keys without disclosure and attempt the prescribed live SOL/tool/cost/diagram/
datasheet gates. Record native/human/platform prerequisites as unverified with
specific reasons. Existing 252 evidence from another worktree is not this run's
live evidence.
