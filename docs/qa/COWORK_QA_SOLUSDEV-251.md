# SOLUSDEV-251 integrated QA on SOLUSDEV-260

## Setup and evidence rules

- [ ] Use `/home/beeboss/SOLUSDEV-260`, its own `.env`, database `solus` on
  127.0.0.1:5432, Redis 6379, API 8000 and renderer 5173. Do not edit another
  checkout or stop processes you did not start. API `/readyz` must report database OK.
- [ ] Confirm Alembic has one head, `a26000000003`. The Phase 2 snapshot and migration
  evidence are in `PHASE2_SOLUSDEV-260.md`; never downgrade the real database for QA.
- [ ] Sign in normally. The current account is pmadaram, project **My first robot**.
  Authentication is distinct from an integration connection. Use a separate viewer
  and another team's project for permission tests; never borrow their private files.
- [ ] For file-picker checks use the actual Electron app. A normal browser must show
  that local files are unavailable and disable picking. MAIN IPC tests are fixture
  evidence, not proof that the native dialog was exercised.
- [ ] Two real USB devices have serials `5B42134331` and `5B42135040`. Identify their
  physical leader/follower roles with the user. No motion/flashing is authorized by
  this test plan. Interrogate only through the application's passive/ping flow.
- [ ] Keep real hardware and user-created `.solus` nodes. Use a disposable isolated
  test database for synthetic corruption/race cases, or a transaction that is always
  rolled back. Do not leave placeholder graph nodes in the real project.

## Configuration and ownership walkthroughs

1. [ ] Open Workspace → Add → Hardware → Detected. Verify enumeration shows both distinct USB
   serials without opening ports; unknown board/protocol facts remain unknown.
2. [ ] Create a named real robot or robot-owned part through the existing authored
   flow. Blank names must fail visibly. Refresh and verify identity persists.
   Standalone creation is API-only; use fixture check A below.
3. [ ] Read an unconfigured subject twice. Expect no CONFIG entry/node, no version
   increment, and no graph change. Deleting a CONFIG must not make a later read
   recreate it. Legacy GET also requires MEMBER permissions.
4. [ ] Use fixture check B below for first-save API semantics (there is no editor for
   an absent CONFIG yet). For UI editing, use an existing CONFIG created through
   hardware confirmation or fixture setup. Open that CONFIG node: show its subject and current values,
   not the note editor. Change one field and save; expect exactly that change and a
   higher version. Identity, firmware, calibration and provenance remain intact.
5. [ ] Keep two config views open. Save in one, then save the stale other view.
   Expect an honest conflict and preserved draft; never silently overwrite.
6. [ ] Promote an existing part's lifecycle on a firmware-bearing robot. Verify
   owner identity, protocol, bus map, firmware and disambiguation survive. Repeat
   the equivalent legacy PUT, reviewed detect confirm and library-import regression
   on fixtures if real hardware/library data is unavailable.
7. [ ] Detach/reassign a part. Its UUID, config entry, values, source identity and
   provider links survive. The old owner's endpoint mapping is disabled until review.
8. [ ] Remove a real robot only with the concrete removal confirmation. Its retained
   parts remain visible in the unified unassigned list, and its device can be claimed
   by a new robot. No error names a deleted robot. Independent retained controllers
   keep their own mappings, including mappings to other retained parts.
9. [ ] A deleted part returns 404 for a config update. A malformed live CONFIG node or
   `configures` relation fails closed with 409; it cannot supply runtime values or
   trigger navigation repair. Test corruption only in the isolated fixture database.

## Private sources and sessions

10. [ ] In Electron, open Hardware → From a file → Local calibration sources. Choose
    a supported local file. The list shows a portable reference/name, no native path.
    Verify checks the actual bytes; listing alone makes no integrity claim.
11. [ ] Open a migrated CONFIG's source controls and explicitly relink its opaque
    reference to the correct file. The requested reference remains unchanged, while
    MAIN stores only the local path/digest in the current account's private state.
    Two parts citing the same migrated reference resolve it together.
12. [ ] If another historical reference already points to that file, explicit relink
    preserves both references. A new normal pick reuses an existing same-file ref.
    Changing known bytes requires review; it cannot replace shared calibration values.
13. [ ] Modify the selected file after verification. A new session must return
    `source_changed` and open no device. Relink/review through the picker, then retry.
    Missing/wrong-account authorization yields `relink_required`, never a guessed path.
14. [ ] Switch project/account while a picker or request is pending, including A→B→A.
    The old result must not update the new scope or restore an old draft. Cancelled
    picks preserve the existing source and config.
15. [ ] Try absent, corrupt, newer-version, symlinked and oversized state/source files
    in fixtures. No automatic overwrite, path disclosure, secondary file read or
    unbounded read is permitted. A cloud/absent runner performs no local file I/O.
16. [ ] Start a saved robot session. Verify a connection-owner part session through
    fixture check C below; that provider has no renderer caller yet. Both paths
    resolve current independent configs. Serial-only identity with no private hint
    remains valid. A hint is not confirmed-port permission and never selects a CAN
    channel. Private hints must not appear in session responses or driver-error logs.
17. [ ] Disconnect the device or induce a driver/setup failure on fixtures. The saved
    node remains usable; retry uses its existing ID. An open session is not proof of
    receiving packets. Confirm actual telemetry before marking streaming verified.
18. [ ] Submit an arbitrary `repo_root` path to compatibility propose/confirm. Expect
    422 without any filesystem inspection. This field is not picker authorization.

## Cross-feature and final checks

- [ ] Unauthenticated requests fail 401; viewers cannot write; foreign-project
  entity/config/source IDs disclose no other team's data.
- [ ] Migration fixtures preserve nested/deleted history, source tokens and existing
  IDs; conflicting copies abort atomically. Both constraints reject invalid writes.
- [ ] API, Live Bench, companion, desktop, lint/types and hardware ratchets pass.
  Record native/live, fixture-only, skipped and unavailable checks separately.
- [ ] Confirm no synthetic nodes/edges/configs remain in the real graph. Before any
  real hardware creation, its baseline was six `.solus` nodes, five edges, zero CONFIGs.

## API-only fixture checks

Run these against a disposable project/database or the mandatory rollback harness;
use an authenticated project MEMBER and JSON content type. Preserve the response
IDs and versions. Do not leave synthetic records in the real project.

A. POST `/api/v1/projects/{project_id}/hardware/entities` with a fresh UUID
`Idempotency-Key` header and body `{"kind":"part","name":"Fixture standalone part"}`.
Expect `data.entity.id`, with no placeholder parent robot.

B. PUT `/api/v1/projects/{project_id}/hardware/entities/{entity_id}/config` with
`If-Match: 0` and body
`{"config":{"schema_version":2,"entity_id":"<entity UUID>","provenance":{}}}`.
Expect `data.version: 1`. Subsequent writes send that current version; stale writes
return 409, missing/malformed headers 422. V2 GET permits project viewers; the
legacy robot GET specifically requires MEMBER.

C. POST `/api/v1/projects/{project_id}/bench/sessions` with body
`{"mode":"real","config":{"provider":"hardware","entity_id":"<entity UUID>"}}`.
Use a fixture runner and saved identity/protocol. The empty config from B must
return 422. A successful real request can open hardware, so do not use a real
runner for synthetic identifiers. Assert current per-entity config is resolved.
