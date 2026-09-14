# Isaac security review — 2026-09-12

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
