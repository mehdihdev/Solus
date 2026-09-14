# Integration check — Phase 1 checkpoint (SOLUSDEV-261)

This checkpoint covers document browsing, platform availability, account-owned
hosted setup and the first additional CAD operations. Live FeatureScript consent
and CAD read/operate/write proof are **not yet complete**. Do not use this file as
evidence that all Phase 1 acceptance tests pass.

## Current development evidence — 2026-09-12

- User verified the existing Draw Piece Extrude 1 depth changed from 1.5 to 2 mm.
- Live read-only circle-sketch and extrude-cut previews succeeded against Part
  Studio 1. Their writes and automatic graph refresh remain unverified.
- Face connector and fastened mate operations have fixture coverage, including
  actual vendor geometry shapes and approval staleness. Live mating is pending.
- Public donor candidate: document `0a5ea879a16df03f69824709`, workspace
  `485369bfc785a13efde36b61`, Part Studio `b8545bd5134fa0d89bca71e1` contains one
  solid part `JFD`, named `FSR_402`. Dimensions and insertion still need verification.
- FeatureScript inventory discovery succeeded, but its grant refresh subsequently
  failed. Reconnection is required; cached readiness alone is not live evidence.
- Permanent hosted-grant failures now clear cached readiness and inventory. Test
  recovery by expiring/revoking a test grant, invoking a hosted read, and checking
  that Home offers reconnection without exposing vendor credential text.

Needs you: once development verification is complete, reconnect FeatureScript via
Home → Onshape → Continue FeatureScript setup and approve the concrete CAD write
cards. No pending write is assumed approved by this checkpoint.

## Setup

- Run `pnpm dev:all` from this feature checkout. Use its isolated services; do not
  stop unrelated processes or modify `.env` files.
- Sign in and select an existing test workspace. Connect an Onshape account that
  owns folders and documents and has shared documents. No CAD edits are required
  for the browsing checks below.
- `make mcp-forks` installs the pinned owned forks. On this Linux host, code and
  local fork virtual environments were installed during this session.
- For companion verification use the Electron app: the plain browser cannot
  launch native companion processes or supply Electron platform APIs.
- Governing references: `docs/api/document-tree.md`, `docs/wireflows/document-tree.md`,
  `docs/api/API.md`, `docs/wireflows/local-connections.md`, and existing I1 cache rules.

## Folder browsing

1. [ ] Open Workspace → Add → Integrations → the connected Onshape account.
   Expected: cached navigation appears; a first-use cache miss offers Load documents.
2. [ ] Click Load documents once. Expected: Owned by me and Shared with me appear,
   with provider names; no document is attached by loading or expanding folders.
3. [ ] Expand Owned by me. Expected: actual account folders and root documents.
4. [ ] Expand a folder containing more than 20 documents. Expected: first page and
   Load more. Click Load more: second page appends, first page remains, duplicates
   are removed by kind/id. Repeat through the last page; Load more disappears.
5. [ ] Collapse and reopen the folder and the Add panel. Expected: already loaded
   pages reappear without another provider fetch. API cache supplies new component
   sessions; in-session reopening uses the client cache.
6. [ ] Expand Shared with me. Expected: shared documents are selectable.
7. [ ] Click an already attached document. Expected: existing workspace selection,
   with no duplicate Source. For an unattached document use a designated QA project:
   selection imports through the existing job flow and adds its graph nodes.
8. [ ] Refresh a visible listing. Expected: explicit refresh replaces that page;
   provider errors retain existing rows and offer retry.
9. [ ] Sign out, then sign in as another account. Expected: no previous account
   documents flash or remain. A revoked or foreign connection must return 404,
   including for a warm cache.
10. [ ] Check a flat-list provider. Expected: its existing picker still works.

Automated boundary cases cover malformed links, untrusted origins, invalid node
ids, non-advancing cursors, corrupt cache, authorization, account isolation,
revocation invalidation, refresh retry and recursive ancestor cycles.

## OS availability and companion

1. [ ] On Linux open Home connection catalog. Expected: Fusion, Altium, AutoCAD,
   and SOLIDWORKS say `<Tool> is not available on Linux`; Connect is disabled.
2. [ ] Open the bridge status popover. Expected: unavailable applications have no
   Add license or Upgrade required action and do not alone trigger attention.
3. [ ] Inspect companion status/logs. Expected: unsupported applications never
   spawn or enter restart loops; direct calls are refused before execution.
4. [ ] Exercise a compatible integration with missing setup. Expected: its real
   setup/launch failure still appears as attention; do not hide it as OS unavailable.
5. [ ] Verify normal connection affordances on supported macOS/Windows fixtures.
   Expected: platform metadata does not disable supported applications.

## Account-owned hosted setup

1. [ ] In native Solus connect Onshape from Home. Expected: after account OAuth,
   the same flow discloses and starts FeatureScript authorization without a separate
   Enable click. Complete vendor consent yourself; the tester does not self-approve.
2. [ ] For an already connected account, open Home → Onshape → Continue FeatureScript
   setup. Expected: successful consent produces backend-verified readiness.
3. [ ] If a subscription is needed, use Open subscription page and complete it in
   the vendor portal. Expected: focus/periodic checks detect readiness, stop within
   60 seconds, and offer Check for a later retry. No success is inferred from opening
   the subscription page.
4. [ ] Cancel consent, sign out, or leave the connection screen while authorization
   is pending. Expected: no stale browser launch, exchange, success state or account
   data appears after cancellation. Existing successful account connection remains.
5. [ ] Attach that account to two authorized project Sources. Expected: both use
   its hosted grant; source settings direct grant management to Home.
6. [ ] Check an account owned by another user. Expected: status and mutations are
   refused. Revoking the account disables its grant for all attached Sources.
7. [ ] Check a legacy source-scoped grant. Expected: its existing setup still works.

## Remaining Phase 1 proof — unchecked

- [ ] Live single account connection flow and revoke handling (design approved).
- [x] User-authorized document selection; list elements/parts/mass/features through
  SOL on Draw Piece. Bounds also verified live; missing mass assignment reported
  honestly. No vendor CAD writes performed.
- [x] Live geometry pages returned complete planar faces JLG/JJS and line edge JLB
  for body JJD, with totals of 8 faces and 16 edges. The second face request echoed
  the first page's unchanged body fingerprint. Bounds were verified separately.
- [x] After the containment fix, eight independent fingerprint-checked face pages
  completed in one model tool round. IDs: JLG, JJS, JJC, JJW, JJK, JLC, JLK, JKO;
  offset 7 returned next_offset:null. Largest planar face JLC has observed area
  0.007550659919505753 m², origin (0,0,0) m and normal (0,-1,0).
  The earlier sequential attempt hit the existing five-round limit; cross-turn
  history retained success markers rather than raw geometry. Tool guidance now
  explains batching independent offsets once total/fingerprint are known.
- [x] Live Assembly 1 definition returned empty instances, occurrences and features;
  no named instance or transform was invented.
- [ ] Verify named-part placement in a populated assembly through SOL.
- [x] Concrete depth-edit diff approved by the user; depth changed 1.5 mm → 2 mm.
  Independent SOL readback returned 2 mm and corresponding part bounds.
- [ ] Sketch/cut and Variable Studio update through concrete approval cards.
- [ ] Repeat a user-approved write after the graph-sync hook fix; verify a queued
  sync job, new microversion and graph changes without manual refresh. Scheduling
  failure must retain CAD success and direct recovery to source sync only.
- [ ] Cross-document part insertion and mate, with explicit diff approval.
- [ ] Readback and microversion-triggered graph update after every write.

Never self-approve the above CAD diff gates. The `openai_api_key` SecretStore
reference was seeded successfully using the repository script; live SOL model calls
and Onshape reads succeeded. Do not paste secret values into this QA record.

## Additional read-only preparation

- [x] Live SOL `list_elements` rechecked Draw Piece: three Part Studios and one
  Assembly, with no Variable Studio. No variable write was queued or claimed.
- [x] Located and inspected Interlink's official FSR 402 CAD archive. Its STEP
  filename says 44-29103, but embedded identity is 30-81794 (solder-tab variant).
  Preserve that distinction on any proposed import/insertion card. Local inspection
  record: `/tmp/solus261-fsr402/README.md`; STEP:
  `/tmp/solus261-fsr402/44-29103-FSR 402.STEP`. No Onshape import occurred.
- [ ] Implement and verify STEP import and assembly mate; existing single-part
  insertion cannot stand in for importing all components of this sensor model.

## Reconnected account acceptance — 2026-09-12 follow-up

The user completed FeatureScript reconnect, replacing the old account grant.
Home reported FeatureScript ready. The existing-account document picker was fixed
to skip the absent desktop OAuth bridge; fresh OAuth still requires that bridge.
Draw Piece was linked through the real UI and synced to three graph entities.
Selecting Full Hand as well exceeded the current 25-exportable-element sync limit;
tracking was narrowed to Draw Piece. Full Hand Variable Studio is not yet accepted.

A real SOL `onshape_fs.list_feature_studios` call on Draw Piece succeeded and
returned “No Feature Studios found in this workspace.” This is a successful empty
read, not an unavailable tool. Newly implemented sketch/cut/mating writes still
need actual approval/readback and automatic graph-refresh verification.

The final acceptance turn read current Draw Piece body details successfully, then
stopped at exhausted SOL credits (Billing showed -6). No circle-sketch approval
card or new CAD write was created. Await credit replenishment, then request the
normal gated circle sketch, user approval, readback, cut and graph-refresh steps.
