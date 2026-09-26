# Hardware and Live Bench

<!-- Updated: 2026-09-24 | SOLUSDEV-262 | Scope: reviewed hardware/runtime boundaries -->

Python paths below are relative to `packages/api/src/solus_api`; renderer paths are relative
to `apps/desktop/src/renderer/src`. Provider paths start at `livebench/src/livebench`.
Authority: hardware-onboarding architecture/wireflow, hardware API, bench-scene/bench-runs API,
SOL-window wireflow. The completion report and Cowork QA file distinguish live and fixture proof.

| Entry | Flow / responsibility |
| --- | --- |
| `hardware/hardware_router.py` | Verified member → scoped service → commit/event; device confirmation, part links, wiring and local deployment preparation |
| `hardware/topology.py`, `topology_acceptance.py` | Brain/bus/device projection and explicit evidence acceptance; preserve robot/part/CONFIG identities |
| `hardware/topology_proposals.py`, `local_sources.py` | Account-bound native file capability → bounded extraction → digest-bound review |
| `hardware/cad_suggestions.py` | User graph revision scope + trusted identity edge + unique robot owner → explicit attachment; stale evidence and decline memory |
| `hardware/presence_topology.py` | Typed/schematic/retained-probe observations → graph proposal → actor acceptance; no inferred device drivers |
| `hardware/presence.py` | Accepted target/wiring → retained compiled bytes → complete flash preview → final identity/evidence check → exclusive upload |
| `plugins/arduino/presence.py`, `wiring.py`, `presence_provider.py` | Provider-owned Uno/Nano pins, input-only generation, bounded AVR names in flash, compiler and USB/serial ownership |
| `hardware/companion_deployment.py` | Default-off local factory; actor-owned target/artifact plan; operator allowlist; fresh authenticated post-restart handshake |
| `agent/tools/firmware_presence.py`, `companion_deployment.py`; `agent/runtime.py`, `deps.py` | Register destructive tools only when capability exists; complete central confirmation; no raw write endpoint |
| `deploy/companion.py`, `companion_remote.py` | Provisioned Linux target install/start/rollback/recovery; pinned SSH identity, exact-operation lease; no bootstrap |
| `features/graph/robots/PresenceCard.tsx`, `PresenceWiringCard.tsx` | Explicit profile, three evidence choices, paginated probe runs, separate review/accept/prepare |
| `HostMirrorOffer.tsx`, `FirmwareTelemetryOffer.tsx` in the same directory | Selected LOCAL source/manifest → explicit snippet → forced complete machine-file confirmation; no loop start or flash |
| `features/graph/robots/PartLinkSuggestions.tsx` | Explicit CAD proposal, Accept/Decline and stale-account guards |
| `features/bench/`, `livebench/runs/` | Saved-config sessions, signal/observer UI, retained manifests, playback/sensor timestamps, deterministic findings/comparison |
| `livebench/stream.py`, `graph/telemetry.py` | Session WebSocket: bounded first-frame authentication, central project/graph authorization, memory-backed snapshots at up to 10 Hz, heartbeat and resource limits; no hardware control |
| `features/bench/benchStream.ts`, `BenchRealtime.tsx` | Shared authenticated session feed for main signals, scene and embedded widget; scope masking, bounded reconnect, heartbeat validation and REST fallback |
| `features/bench/retainedSignals.ts`, `DeviceBenchView.tsx` | Bounded established-channel retention through gaps, independent anomaly requests and honest stale values |
| `lib/cspConnect.ts` | Exact configured HTTP(S) API and WS(S) origins in renderer connection policy |
| `features/bench/BenchScreen.tsx`, `DeviceBenchView.tsx`, `bench.css` | One-view panes, presentation pause, responsive eight-second signal grid, persisted names and honest health |
| `features/graph/hardware/HardwareAddPanel.tsx`, `InlineSupplierResults.tsx` | Three inline creation paths; explicit metered supplier search; no library preview modal |
| `hardware/library_router.py`, `library_import.py` | Standalone named part import, scoped idempotency, independent provenance config; legacy robot imports retained |
| `features/workspace/IsaacConnectionPanel.tsx` → `routers/isaac_connection.py` → `services/isaac_connection.py` | Owned bridge probe/status only; bounded evidence, no platform offer or simulator mutation |

Isaac execution is separate from that read-only status panel. The cloud-owned
`agent/tools/isaac_models.py` and `isaac_tools.py` validate v2 graph-bound models,
then dispatch through the existing approval/bridge path to
`integrations/mcp/isaac/solus/`. `services/simulation_models.py` registers a model
root over existing scoped graph bindings; it does not seed a robot template.
The native `assets.py`/`urdf.py` boundary verifies a bounded workspace-relative
URDF/STL closure before the vendor importer runs. `runtime.py` resolves the
machine-owned `SOLUS_ISAAC_RUNTIME` setting; `controller.py` launches only the
owned worker with a closed environment. Missing model/runtime data is refused.
See `docs/api/isaac-development.md` for supported joints, preview limits and the
generic trajectory contract. Automated validation does not establish live vendor
physics behavior on a particular installation.

Shared graph and telemetry boundaries do not acquire vendor-specific register reads. Calibration,
CONFIG membership and imported CAD identity survive rebinding. Linked repositories remain
references; native file grants and LOCAL workspace authority are separate capabilities.

Validation: relevant API/Live Bench suites, full desktop suite, real AVR compiler, provider/vendor
ratchets, and independent code/security/Python/TypeScript reviews. See
`docs/qa/COMPLETION_SOLUSDEV-262.md` for exact results and outstanding live prerequisites.

## First-party BOM Store setup

`extensions/bom_catalog_setup.py` loads the packaged BOM assets and runs bounded startup
provisioning or health checks. `extensions/first_party_catalog.py` owns staff-authorized
immutable publication/review and retained asset validation. `main.py` invokes setup before
serving; workspace installs remain owned by the existing extension lifecycle.
