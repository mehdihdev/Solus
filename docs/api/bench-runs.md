# SOLUSDEV-262 — bounded runs and graph-grounded findings

Authority: SPEC§4, attached Phase4, ADR-014/017/026, telemetry-viz-out and sol-artifacts.
Routes under /api/v1/projects/{project_id}/bench; centralized ProjectCtx. All actions require
member role and verified identity. Unknown/foreign run/artifact/robot/session is404.

- POST /runs: {robot_id:UUID, session_id:UUID, name:string1..120}. Start capture from an active
  matching project robot session.201 envelope run summary. No motion or session start.
- POST /runs/{run_id}/stop: finish idempotently and file retained manifest;200 summary.
- GET /runs: bounded list (limit1..50,cursor optional), current project only. Newest creation first, with UUID as the timestamp tie-breaker. The UUID cursor resolves a current-project run; missing, foreign, deleted or unrelated cursors return 404.
- GET /runs/{run_id}: immutable manifest for completed run or explicit running/interrupted state.
- POST /runs/import: {robot_id:UUID, artifact_id:UUID, name:string1..120, origin:recorded|synthetic}.
  Read bounded uploaded run manifest; validate IDs/units/counts; never native paths.201summary.
- POST /runs/compare: {baseline_id:UUID,candidate_id:UUID};200 deterministic comparison, same
  project and robot identity, aligned elapsed time and compatible units. No modelrequired.
- GET /runs/{run_id}/findings:200 evidence-grounded cards and explicit insufficiency reasons.
- POST /runs/{run_id}/narrate: optional batched cheap-tier narration through existing metered
  gateway (TRIVIAL/GENERAL); no finding creation or altered numeric evidence; deterministic
  fallback when unavailable. Existingbudget/rate/auth checks apply.

Run summaries include id, robot/session IDs, name, origin(live|recorded|synthetic), status
(running|completed|truncated|interrupted), start/end timestamps, packetcount/dropcount, artifact
reference when filed. Manifests schema_version1 contain captured timestamped numeric packets,
sensor artifact references with timestamps, accepted part/device mapping and CONFIG/source/code/
CAD revision snapshots. Require finite values, bounded identifiers/strings, strict unknown-field
rejection, at most10000packets/10000sensor references and8MiB serialized manifest, at most4active
runs perproject. Bounds terminate visibly as truncated; never silently call a partial capture whole.

Capture subscribes to the shared ingest seam before recent-buffer reduction. Work perpacket is
bounded; serialize/persist off request/ingest hotpaths in owned bounded tasks. Start persists a
graph run record. Checkpoints persist captured progress periodically; process loss surfaces
interrupted status and exact lastpersisted count, never completed. Stop creates immutable artifact
and uses existing .solus filing to retain it; no global TTL change. Audit identifiers/countsonly.

Analysis uses measured current, observed position, commanded target and explicit graph rating/
configured range. Load-percent is neveramperes; absent current/rating/command yields insufficient
evidence ratherthan inventedstall. Findings name acceptedpart, code/CAD context only when
snapshotted, and numerical evidence. Comparison separates config/source changes from observed
signaldivergence and asserts clampattribution only when supported. Imported recordings remain
user-declaredrecorded orsynthetic, notverifiedlive. Modeloutput isboundeduntrustedprose and cannot
change deterministicfindings, identities, numbers, scope or execute actions.
