# SOLUSDEV-260 Phase 3 execution plan

Begin after Phase 2 commit. Governing docs are hardware/workspace architecture,
API plans and wireflows, hardware-config schema and private local-state contract.

Backend lifecycle/read task: physical_robots.py; hardware bindings.py,
hardware_router.py, ownership.py, store.py; livebench/bench_router.py; legacy
hardware/store/library/bench/detect/attach/ownership tests. Release owner and child
bindings on removal, ignore deleted subjects in conflict checks, remove unused
configured_endpoint_targets, make GET pure/member-authorized, keep absent configs
absent until first PUT, explicitly permit serial-only connections with null hints.
Extend old tests for deleted subjects, version conflicts and unified unassigned
parts; preserve Phase 1 lossless/refusal guards and Phase 2 strict reads.

Private-source task, disjoint from routers: new hardware/local_sources.py and
its tests; desktop hardwareSources.ts/tests; renderer API hardware client/tests
and hardware UI directory, plus SolusNodeContent.tsx and its tests for CONFIG-node
inspection/editing. Existing config client wrappers have no production consumers:
wire a real versioned config view, not only a changed wrapper. Keep private source
controls as a labeled subsection of FromFileModal alongside connector parts.
Read only authenticated account/project sources, verify
bounded regular files/digests and reject symlinks/corruption/newer state. Explicit
relink accepts a migrated opaque reference after the user's picker authorization;
reuse that reference across parts. Wire list/pick/recheck and v2 configuration
read/write with expected versions and honest missing-source status. Paths remain
inside MAIN/local runner. No protected contract change.

The existing preload namespace is `window.solus.hardware.sources`; use its installed
channels. Shared `source:<UUID>` references map to bare UUID IPC keys. Check the
returned project/account and request generation before updating state; an A→B→A
scope change must not revive a stale response. Listing alone does not verify bytes.
Relink changes private authorization only, preserving shared values and provenance.

Root integrates local-reader hints into routers after backend task completes,
regenerates OpenAPI/schema once, and fixes residual lint/type findings outside
owned files. The approved first-PUT alternative avoids creating a config solely
because a robot exists. Code/Python/TypeScript/security review follows integration.

Verification: focused backend and frontend/source suites, then full API, livebench,
companion and desktop suites/build/type checks on this checkout's test databases.
Exercise live create/promote/edit/delete/reclaim/relink, separate real hardware
from fixture evidence, and confirm a single head and no graph junk. Write
COMPLETION_SOLUSDEV-251.md, COWORK_QA_SOLUSDEV-251.md and Phase 3 evidence; remove
A1/A2 manifests only if present and verified. Root records exact ownership manifests
before dispatch. No branch merge for 252 until Phase 3 is verified.

Current hardware availability changed since Phase 0: OS enumeration now exposes
two USB serial adapters (VID 6790, PID 21971), serials 5B42134331 and 5B42135040.
Enumeration alone does not establish arm role, protocol, or streaming. No device
was opened during planning.

Browser baseline on the Phase 1 build: Workspace → Add → Hardware → Detected lists
both adapters from the live API as “USB-serial bridge — MCU unknown”, with distinct
USB serial references. Neither Propose action was pressed. The canvas remains six
entities/five relations/zero sources; Home reports Onshape not connected. This
verifies enumeration-to-UI only, not protocol identification or packet streaming.
