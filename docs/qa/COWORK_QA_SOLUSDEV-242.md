# Workspace W1 fix + W2 + W3 + W4 — Cowork QA

This is the cumulative QA handoff for branch `SOLUSDEV-242-workspace-graph-w2`.
All four phases are implemented: navigation, `.solus` nodes, service documents and
Physical Robot instances. The implementation record links the completed live checks.

## Setup

- Run PostgreSQL with pgvector, Redis, the local Solus API, and the desktop renderer.
  Apply Alembic migrations; final head is `c7f242e9a842`. Phase 4 adds no migration.
- Sign in as a member of a test team. Have a second member and a viewer account for
  permission checks, and another team's account for isolation checks.
- Use disposable projects. Prepare one empty project and a large graph with at least
  243 entities, containment at least three levels deep, and a cross-domain relation
  between leaves in different branches. Suggested structure: Drive document → Drive
  assembly → Left drivetrain → Wheel motor; Firmware repository → src → motor_driver.c;
  motor_driver.c `drives` Wheel motor. Drive assembly has 243 additional sibling parts.
- Keep another project available in the project switcher. Neither testing navigation nor
  selecting nodes requires a sync, provider access, or hardware connection.
- For imports, set a durable local artifact directory through runtime
  configuration, such as `SOLUS_ARTIFACT_LOCAL_ROOT=/home/beeboss/.local/share/solus/artifacts`.
  Do not use a process-temporary artifact directory for persistence QA.

## Phase 1 — navigator

1. [ ] Open Workspace in the empty project. Expect one `.solus` card centered in the
       viewport. No separate `.solus` panel remains.
2. [ ] Open the large project. Expect only top-level cards, with `.solus` at the origin
       and other roots around it. Names remain readable. The inspector starts unselected.
3. [ ] Hover Drive document and scroll upward. Expect its children, a breadcrumb and an
       animated inward transition. Repeat on Drive assembly and Left drivetrain: depth is
       three and Wheel motor is visible. Scroll downward three times to return to overview.
4. [ ] Repeat with double-click, the node's Zoom button, ArrowRight, ArrowLeft/Escape,
       breadcrumbs, and Up. Leaves do not enter empty levels. Project returns to overview.
5. [ ] Select Wheel motor. Expect the inspector's real properties and links. Open Live
       Bench. Its focus is Wheel motor with the same ancestor trail. Return to Workspace:
       selecting a cached node does not initiate a source sync.
6. [ ] Inspect the dashed cross-link between document/repository at overview and the
       external link inside the assembly. Open either real endpoint from the link list.
       Expect the correct containing level/page and selected endpoint. Solid containment
       and dashed cross-links remain distinct.
7. [ ] Enter Drive assembly. Page through all children. Expect at most 24 entity cards
       in the DOM, 11 pages for 244 children, and four cards on the last page. Every child
       is reachable; labels do not shrink to fit the complete graph. Record frame timing
       while zooming and paging; report hardware/browser and dropped-frame observations.
8. [ ] Drag a root using its handle; also move it using the handle's arrow keys.
       Wait for saving to finish, reload, and reopen Workspace. Expect the saved position.
       Switch projects and back: the other project keeps its own layout.
9. [ ] With network response latency enabled, move A, then B while A is saving, and
       immediately open Home. Wait, return, and reload. Both moves must be persisted.
10. [ ] In a second member's session, move another node. Move locally from the older
        layout. Expect a visible conflict and Retry. Retry preserves the teammate's
        position and applies only local moved nodes. Repeat after the teammate adds a new
        node: its saved coordinate must survive even before the local graph refreshes.
11. [ ] Move an imported document, delete it through its `.solus` entry menu, then move
        another node. Expect successful saving; the deleted ID must not poison later saves.
12. [ ] Simulate layout read/write failures. Expect a visible error and Retry; successful
        retry restores operation. Simulate a graph-links read failure: no misleading flat
        forest appears. Restore the API and reload to recover.
13. [ ] Switch accounts during a delayed graph/layout response. Expect no previous
        account's graph, positions or queued new requests under the next account's token.
        A viewer can read but cannot save layout; an unrelated team cannot read or save it.
14. [ ] Enable the operating system's reduced-motion setting. Zoom still changes levels
        and selection, with animation disabled. Keyboard focus remains visible.
15. [ ] Watch network traffic while returning from Home/Live Bench to Workspace with an
        unchanged graph. Project detail may validate the cache; entity and relation page
        walks are retained until graph mutation/version change or the five-minute TTL.

## Phase 2 — `.solus` on the canvas

1. [ ] Create a new project in the test team, then open Workspace. Expect exactly one
       top-level card, `.solus`, centered, and Add at the top left. No fixed `.solus` panel
       or empty-project message covers the canvas. Graph counts include the five contained
       sections, even though they are not overview cards.
2. [ ] Enter `.solus`. Expect Hardware configs, Project details, Error logging,
       Documentation and Code environment. Each is a selectable real graph node; selecting
       one updates the inspector and shared focus. Empty sections show EMPTY.
3. [ ] Right-click each section. Expect exactly Import files…, Ask SOL to find…, Type it.
       Right-click Project details → Import files…, select a valid PDF below 8 MiB.
       Expect an import success message. Enter Project details: the PDF has its own
       document card, media type and size. Select it and inspect its real graph links.
4. [ ] Return to the sections and use Project details → Type it. Enter a specification
       such as “48 V supply, 10 A maximum”; submit. Enter the section: the note is a real
       selectable child. Reload and return to this level: text and graph identity persist.
       For an existing W1 project, old imported documents keep their IDs and content.
5. [ ] Add a note in Error logging, enter the section, select it, then Edit note.
       Change the text and Save. Expect editing inside that card, an updated title and
       updated inspector/shared-focus label. Reload: the change persists with the same ID.
6. [ ] Attempt to save an edit while the API returns an error. Expect a visible failure
       and the unsaved draft to remain open. Restore the API and retry; the update succeeds.
7. [ ] Delete a note from its context menu. Expect confirmation naming the note and
       explaining its graph node/links will be removed. Cancel preserves it. Confirm removes
       the note and clears its selected focus. Other nodes remain. Repeat with an imported
       PDF: confirmation additionally explains stored-byte removal; confirm removes its card.
8. [ ] Use Ask SOL to find… with a bounded query. The existing SOL flow runs; a filed result
       appears under the requested section. A reply that files nothing says so honestly.
       During an active SOL turn the menu action is disabled. Existing confirmation/refusal
       protections remain in effect; do not approve external changes merely to test the menu.
9. [ ] Choose a file above 8 MiB: expect a warning before upload. Try a rejected type or
       failed upload: no invented entry/card appears. Try blank text and >4000 characters:
       blank cannot submit; the composer enforces the existing length boundary.
10. [ ] Open a note editor, context menu, or file chooser and switch project/account.
        Expect no old draft/menu in the new workspace and no upload/entry request under the
        new account for the old operation. A delayed old sections response cannot replace
        the new project's data. A viewer cannot mutate; another team cannot access entries.
11. [ ] Inspect the project graph using the authorized graph API: root → sections and
        section → entries have `contains` edges; imported documents retain root `references`
        edges for Impact. Zoom/select/reload issue no provider sync calls.

## Phase 3 — service documents

Setup: connect an Onshape account in Home with two accessible small documents, including an
assembly with child parts. Keep a second project and a second user/team for isolation. Have the
API, PostgreSQL and Redis running; use the normal ARQ worker for queued imports/change detection,
or the existing local inline sync setting for controlled development checks. OAuth connection
alone does not register a provider webhook. For a live change gate, record whether the hint came
from a configured webhook, the scheduled detector, or a deliberately invoked scoped detector.
Record provider request/export counters before testing; avoid repeated listing refreshes.

1. [ ] Create/open a disposable project. Add → From a service lists the Home account.
       Expand it. A cache hit shows choices; a miss says no cached documents and offers Load
       documents. Opening never populates the provider cache. Click Load once when needed.
2. [ ] Select document A once. Expect progress, then a real named document node around `.solus`.
       Select B once. Expect a second document node and the same account-bound project source.
       Capture actual entity/source IDs and successful job records.
3. [ ] Close Add, reopen it, collapse/expand its account three times while watching requests.
       Expect zero additional account/document/source-list requests and no sync requests. Other
       preexisting app background requests should be recorded separately from picker actions.
4. [ ] Select A's existing root once to warm shared focus; select B, then A again through Add.
       Expect the correct root/containing level, its entire card visible in a small window, and zero
       listing, sync, job or cached-focus reads.
       Zoom into A → assembly → part; select the part and open Live Bench. Its focus/path matches.
5. [ ] Reload: source/document identities and positions persist. Open the same document in a
       second project. Its graph/source identities differ; unchanged version payloads reuse the
       account cache. Do not claim zero exports for payloads exceeding the documented cache cap.
6. [ ] Change one test document in Onshape after recording the baseline microversion. Deliver
       a real/controlled change hint through the existing detector. Expect one ingestion for
       the changed version and live canvas refresh. Repeated hints must produce no further
       export/ingestion; unrelated document and part identities remain stable. Record both the
       delivery mechanism and actual counters, not only mocked-test evidence.
7. [ ] With a connected Git account, select repository A and B. Expect distinct code_repo roots
       and directory/file hierarchy; reselect A with zero sync. A second account containing the
       same repository name cannot silently rebind A's existing account/source.
8. [ ] Simulate cache outage/malformed cached listing. Expect a visible cache miss/error with
       no credential/provider fetch. Explicit refresh failure stays visible. Reopening does not
       repeat the failed call; a later explicit refresh can recover.
9. [ ] Fail an initial import job. Expect its error and Sources recovery guidance. Click the
       same document again: the error remains, no success node is invented, and no sync starts.
       Check/recover in Sources, return to Workspace, then select its actual imported root.
10. [ ] Delay source binding, switch A → B → A, and separately sign out/in as the same user.
        The old operation cannot continue its add/sync stage or publish a stale result. Another
        account sees none of the previous account's document catalog or selected graph.
11. [ ] Add a second document while the first export is slow. Both accepted selections survive;
        the second job waits/deferred-retries safely and is eventually processed. A slow export
        outliving the original lease does not start duplicate provider work. Lost renewal/outage
        cancels bounded work and leaves an honest job result; completed/successor jobs stay intact.
12. [ ] Interrupt the project event stream, change graph data, then restore it. Expect visible
        reconnect status and a fresh graph after reconnect. A change between snapshot and first
        stream readiness also appears. An unchanged readiness check only validates project detail.
        Old in-flight responses cannot overwrite the refreshed graph. Permission denial stops retries.
13. [ ] Press Escape in Add: it closes before canvas navigation. Reopen and click outside:
        it closes. Hardware tab is completed by Phase 4 below.

## Phase 4 — Physical Robot instances and retained parts

Setup: use a disposable project with a MEMBER account and a second viewer/nonmember.
Keep PostgreSQL, API and desktop running; no provider or hardware connection is required.
R1 part creation is deferred. For the nonempty deletion check, have the developer seed
at least two genuine manual part entities under robot A's categories using the ORM,
with a manual `contains` ownership edge for each. Add an unrelated cross-domain link;
give one part an additional service/document containment parent. Give robot B its own
part and optionally shared ownership of another part. Record actual IDs/properties/edges
before deleting. Empty categories alone do not prove part retention.

1. [ ] Open Add → Hardware → Add Physical Robot. Expect one new root using the project
       name, revealed and selected on the canvas. Create another. The two roots and all
       category IDs must differ; repeated creation must not return a singleton.
       An authenticated existing account with a stale onboarding `linked=false` flag
       must still be able to add a robot to its accessible project.
2. [ ] Use Rename on A. Edit inside its card to “Leader”, save, then name B “Follower”.
       Only the selected instance changes. Blank names cannot submit, names are limited
       to 512 characters, and Cancel preserves the original name. Reload: both persist.
3. [ ] Enter each robot. Expect exactly seven selectable categories: Sensors,
       Actuators / motors, Controllers, End effectors, Power, Structure and Wiring.
       Enter a seeded category and select its part. Inspector/Live Bench use that actual
       part identity. Empty categories remain empty; no fabricated hardware appears.
4. [ ] Inspect each root through the authorized entity API. Expect manual provenance,
       no source and null `hardware_config_ref` / `transport_refs`. No guessed device,
       transport or configuration schema is presented in the UI.
5. [ ] Click Delete on Leader. Confirmation names the robot and explicitly explains
       part retention. Cancel: root/categories/parts remain. Confirm: only Leader and
       its owned categories/containment disappear. Follower and its parts remain.
       Recorded part IDs/properties and unrelated edges are unchanged.
       Repeat with a category selected, then return to overview without selecting the
       root before deletion. Expect idle/empty shared focus and no deleted-category 404.
       A retained selected part keeps its focus with ancestry rebuilt from surviving links.
6. [ ] Expect a persistent prompt listing the retained unassigned parts. Reveal a part
       from the prompt: its actual card is fully visible and selected, including the
       part that retains service containment. Reload and return: the prompt persists.
       A part still assigned to Follower is retained but excluded from unassigned results.
7. [ ] With more than 24 unassigned parts, page through the prompt. At most one bounded
       page is shown at once; next/previous preserve real identities. A read failure
       shows an error and retry, rather than silently reporting that no parts remain.
8. [ ] In another session rename A after the first session opens its editor. The stale
       save/delete must return conflict without overwriting the newer change. Keep the
       draft and show recovery guidance. Return to Workspace without changing counts:
       project graph modification time invalidates the old cached name.
9. [ ] Disable the API during creation/rename/deletion. Expect visible errors, no fake
       success and no automatic repeated mutation. Rapid duplicate clicks must not send
       duplicate writes. Restore access and retry deliberately.
10. [ ] Start an operation, switch project A → B → A or sign out/in. Delayed prior
        responses cannot publish to the new session, reveal an old node or issue a new
        request under the replacement identity. Offline/unlinked controls cannot write.
11. [ ] As viewer/share-only user attempt a write: 403. As nonmember or with an entity
        ID from another project: 404. Attempts to rename/delete connector, fingerprint,
        `.solus` or other manual node kinds through robot routes fail without mutation.
12. [ ] Observe the project event stream during a robot mutation. The committed hint
        has null source/sync IDs, updates the canvas and never triggers provider sync.
        Opening Hardware, navigating categories and revealing retained parts does not
        perform provider listing/export/ingestion.
