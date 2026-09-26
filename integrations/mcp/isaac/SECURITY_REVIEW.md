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
