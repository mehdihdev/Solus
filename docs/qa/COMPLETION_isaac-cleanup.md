# Isaac cleanup and CI lint completion — 2026-09-24

## Result

Merged origin/main into SOLUSDEV-262-livebench-robo-sol-initial at acb3fc60.
Resolved the hardware proposal import conflict by preserving connectionOnly and
using main's deviceCardRules filename. Git autostash restored pre-existing work.
Removed the clean .kilo worktree through Git and removed its parent directory at
the user's request; its parent ignore file was preserved in /tmp.

Isaac now takes its installation from the machine-owned SOLUS_ISAAC_RUNTIME
setting through an explicit companion allowlist and a closed launcher environment.
The controller passes the captured root internally to its fixed worker. Missing
configuration reports unavailable; no developer-machine or ARM64-only fallback.

Version 2 model definitions reference existing authorized project graph entities
and a digest-verified workspace URDF/STL closure. They carry explicit joint
names/endpoints/radian limits and optional sensors. Registration creates only a
model root and containment edges; existing definitions are reused atomically.
The native importer validates XML, topology and limits before importing a private
copy; articulation discovery replaces fixed paths. Generic joint trajectories
report tracking observations, with no inferred grasp/object success. Removed the
pinned model manifest and installer; retained historical license/provenance.
Legacy v1 graph records are preserved and require explicit v2 reimport.

Node complexity fixes extract focused helpers/components while retaining scope,
authorization and existing behavior. No lint thresholds or rules were relaxed;
smoothing remains disabled. A pre-existing rate-limit test was made deterministic
with a module-local clock and explicit window rollover assertion after the
integrated run crossed a wall-clock minute boundary.

## Governing documents and changes

Followed AGENTS, ADR-014/031/032, action-gate/agent-tool/bridge-protocol contracts,
local-machine-actions architecture, isaac-development API plan and local-connections
wireflow. Tier 1 documentation was revised for v2 definitions, supported model subset,
machine runtime configuration and generic trajectories. The existing
POST simulation-models request shape changed from a pinned template selector to
{name, model}; OpenAPI and renderer types were regenerated. No new endpoint,
shared-contract or ADR change was needed. QA steps are in
COWORK_QA_isaac-cleanup.md; livebench code map updated.

## Final verification

- Integrated native/cloud Isaac, connection/tool knowledge and companion runtime:
  271 passed, in explicitly disposable worker databases.
- Full pnpm test: desktop 4,165, shared types 279, web 22, script/environment 25 passed.
- pnpm lint: exit 0, zero errors and 206 warnings.
- uv run --no-sync ruff check .: passed.
- pnpm typecheck: passed, including regenerated client types.
- GitLab Python mypy target: 405 source files passed.
- Native model/scene typing passed with unavailable NVIDIA/omni/pxr imports ignored.
- git diff --check: passed; no merge conflicts remain.
- Fresh general code, TypeScript, Python and security review: scoped approval.
  Security review found and closed encoded-XML DTD bypass and FIFO blocking;
  reviewed regression tests cover both. Final UTF-8 header interoperability was
  re-reviewed with adversarial declarations. Reviews do not certify unrelated
  accumulated branch work.

## Limits

No live GPU/vendor import, physical motion or full robotics demo acceptance was
performed. The native adapter remains Linux/POSIX and vendor-version dependent.
Only bounded declarative URDF/STL fixed/revolute models are supported; existing
complete-preview limits still apply. Runtime configuration and explicit v2 model
registration/assets are needed before using the new execution path.

The existing branch has substantial unrelated uncommitted work which was preserved.
The full Python suite's previous 9,909-pass result predates these changes; the 271-test
integrated result above is the fresh verification for this cleanup. Human review
and publication remain separate. Ponytail is unavailable in this environment;
focused simplification and fresh review were performed with the available tools.
