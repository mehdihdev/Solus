# Onshape integration
<!-- Updated: 2026-09-14 | Scope: SOLUSDEV-261 | Token estimate: ~1000 -->

Paths below are relative to `packages/api/src/solus_api/`.

## Acquisition

`connectors/onshape.py` → bounded STEP acquisition/parser → complete `SyncResult`.
Default 256 exportable elements; 100,000 records / 64 MiB staged graph bounds.
Immutable element/metadata reads use `/m/{revision}`. Workspace STEP translations
check the current revision before submission and after download; drift aborts the
complete snapshot. `revision-v2-*` payload keys exclude old associations;
`cad-geometry-v3` cursors force one repair ingestion for existing tracked sources.
`connectors/integration_cache.py` partitions reads by account.
`connectors/onshape_read_cache.py` caches validated immutable donor geometry and
feature specs. `OnshapeConnector.immutable_feature_specs` serves six sites:
`onshape_ops` get/preview/add, `onshape_sketch.observe`, `onshape_cut.observe`, and
`onshape_mates.observe`. Specs bind account, document, element, revision, collection
and default configuration; every operation still observes the mutable tree fresh.
Malformed/partial/nonfinite responses never enter the cache;
`connectors/onshape_mates.py` rereads mutable assembly state per preview/write.
`connectors/onshape_ops.py` verifies generic feature creation by fresh tree readback.

## Assembly reasoning observations

`connectors/onshape_assembly_read.py` provides compact feature health and connector
frames. `connectors/onshape_assembly_geometry.py` measures complete circular edges
and returns bounded coincident/coaxial groups; these are observations, not joint
recommendations. `connectors/onshape_assembly_paths.py` resolves nested occurrences
against exact tracked ancestor revisions and uses root-space leaf transforms.
Pagination binds root state, ancestor identities, donor revisions and measured
circles. `connectors/onshape_circle_geometry.py` verifies native connector frames
and unchanged occurrence poses after writes. SOL chooses joints from observations.
`connectors/onshape_mate_offsets.py` measures axial offsets and primary-axis flips
for revolute mates. `connectors/onshape_fastened_geometry.py` validates the full
XYZ basis and selects a pose-preserving discrete secondary alignment for rigid
mates. `connectors/onshape_mate_repair.py` previews a narrowly scoped correction
of an existing fastened mate against an immutable historical assembly revision;
post-write verification compares every original occurrence pose. Tool success
requires geometric readback, not merely healthy native feature status.

## REST grant and quota identity

`services/connections.py` keeps verified application metadata private and mirrors
it only through source binding. `connectors/registry.py::_onshape_meter` uses the
verified application plus account scope, not current settings alone. Unbound legacy
grants retain their old scope; secret rotation does not create a new ledger.
Old counters/latches remain untouched. Quota health uses the same scope.

## Hosted tools

`connectors/hosted_oauth.py` pins refresh scopes to the admitted descriptor.
`agent/tools/remote_mcp.py` defines the allowlist and vendor endpoint.
`agent/tools/hosted_tools.py` binds inventory/auth to source/project/account.
Hosted service restrictions are separate from private-app REST accounting.
No assumed MCP annual entitlement is derived from one historical usage sample.

## Change notifications

Existing `routers/webhooks.py` → source token and bounded event validation →
`services/onshape_webhooks.py` durable source-config generations/deduplication →
`connectors/worker.py` fresh webhook reconciliation → complete graph snapshot.
Normal ARQ sync wires registration; public HTTPS callback required. Verified
subscriptions suppress routine polling. Local recovery retains later/failed hints.
`services/onshape_write_sync.py` uses the same generation/coalescing mechanism.
`agent/onshape_turn_sync.py` registers durable bounded holds only after normal Build
admission. Successful native writes report deferred graph reconciliation; turn
cleanup releases owned holds and coalesces one sync. Worker claims and recovery
respect live holds; expiry recovers interrupted turns without replaying CAD writes.
`services/connections.py` invalidates callback authority on account revocation.
`core/logging.py` and `core/errors.py` redact callback credentials from logs.

## Authority / verification

ADR-019/035 amendment; `docs/architecture/change-signal-spine.md`;
`docs/api/API.md`, `docs/api/onshape-development.md`.
Tests: `test_onshape_*`, `test_webhooks`, `test_worker`, `test_connections`,
`test_hosted_*`, `test_logging` and `test_errors` in `packages/api/tests/`.
Live checklist: `docs/qa/COWORK_QA_onshape-quota-acceptance.md`.
Observed limits: `docs/qa/ONSHAPE_QUOTA_AUDIT_SOLUSDEV-261.md`.
