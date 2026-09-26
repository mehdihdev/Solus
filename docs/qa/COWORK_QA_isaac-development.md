# Isaac generic model QA — 2026-09-24

## Setup

Run API, desktop and authenticated companion. Set the machine-owned
`SOLUS_ISAAC_RUNTIME` to the supported installed runtime. Use a disposable linked
workspace with explicit schema-v2 model assets under `.solus/isaac/models/<sha256>/`.
Register a model through POST `/api/v1/projects/{project_id}/simulation-models`
using `{name,model}` and existing live project link/joint/sensor entities. See
`docs/api/isaac-development.md` for fields, manifest digest and safety limits.
Prepare two distinct URDF robot structures and an optional contact sensor.
Do not connect hardware or start Live Bench telemetry for these simulator checks.

## Flows and expected outcomes

1. [ ] Probe/status report installation/owned process; no simulator starts.
2. [ ] Request start, deny once, approve again. Only approved owned process starts.
3. [ ] Load first model: inspect complete graph IDs, URDF identity and limits in
   approval; verify imported names and selected articulation match the model.
4. [ ] Replace with second model after fresh approval. Link and joint counts/names
   come from that model; no default arm, object or gripper appears.
5. [ ] Change one joint's limits within model bounds. Verify exact-index readback
   and unchanged other joints. Outside-model bounds refuse without mutation.
6. [ ] If a sensor was bound, edit its local pose and unit quaternion; verify
   readback. A model without sensors loads normally; unknown sensor edits refuse.
7. [ ] Request `joint_trajectory` with every joint range and complete waypoints,
   bounded duration/speed. Inspect approval and verify observed target errors,
   positions and tracking result. No grasp/object success is claimed.
8. [ ] Stop approved owned process. Independently opened Isaac remains untouched.

## Failure cases

- [ ] Missing runtime/path/asset directory yields actionable refusal, no fallback.
- [ ] Legacy v1, unknown model, cross-project/team root or nested identity refuses.
- [ ] Stale graph/model/scene during approval requires a new review.
- [ ] Missing/modified manifest file, symlink at any ancestor or leaf, FIFO,
  traversal, URL, package URI, non-STL mesh, malformed XML, UTF-16/32 DTD/entity,
  plugin/unknown tag or attribute refuses before vendor import.
- [ ] Joint name, endpoints, limits, duplicate IDs, cycle or multiple root mismatch
  refuses; incomplete waypoint IDs, nonfinite target and overspeed refuse.
- [ ] Denied approval causes no effect; cancellation stops only owned work.
- [ ] Partial mutation/readback failure reports uncertainty and never auto-replays.
- [ ] Project/account switch discards pending results; no cross-project artifact.

## Evidence boundary

Automated native fixtures cover parsing, confinement, lifecycle and mocked vendor
readback. Record live GPU vendor execution separately with runtime/version, two
model names and actual outcomes. Automated tests do not establish native readiness.
