# What SOL can do — integration capability checkpoint

Date: 2026-09-13. Checkout: SOLUSDEV-261-integration-check. This is an evidence
checkpoint, not a declaration of full integration acceptance. The orchestrator
should update the live-result column after each approved action and readback.

**Current scope:** Onshape calls are paused because the user's API credits are
exhausted. The active completion pass covers KiCad, local code/read-only GitHub,
Isaac and tool knowledge. See [the current evidence matrix](FINAL_NON_ONSHAPE_SOLUSDEV-261.md).

**Live product** means the authenticated Solus UI/SOL/companion path was exercised.
**Implemented/tested** means code and automated tests exist. **Native fixture**
means a developer exercised the actual vendor runtime outside the product approval
journey. A queued card, connection badge or successful preview is not a write.
The latest user-approved Build amendment automatically executes validated routine
edits; destructive and unclassified operations retain compact decision cards.

| Tool | What SOL supports in this checkout | Recorded live product proof | Remaining proof / boundary |
| --- | --- | --- | --- |
| Onshape | Account/document browsing, source import, geometry reads; state-bound automatic routine feature edits, circle sketches and cuts; variable operations and assembly placement/mating | Draw Piece imported; Extrude 1 changed 1.5 → 2 mm; automatic circle and 0.5 mm pocket verified. Pocket depth changed 0.5 → 0.6 → 0.5 mm with verified readback; automatic persisted graph volume changed by 12.667686977 mm³ on restoration while bounds stayed unchanged. Variable Studio 2 → 1 → 2 mm verified with full-table readback and automatic graph sync | Donor insertion/mating and full FeatureScript acceptance remain incomplete. Full Hand selection hit the 25-exportable-element limit. |
| Onshape FeatureScript | Separate account-owned hosted authorization and hosted FeatureScript tool access | User reconnected; actual `onshape_fs.list_feature_studios` returned an empty list successfully | Empty inventory is a valid read, not proof of FeatureScript creation/execution or every hosted operation. Cached ready status alone is insufficient. |
| KiCad | Read complete official net topology/geometry; create supported sheets; place installed symbols; wire, label and mark unused pins; edit properties; ERC; project binding and graph refresh | SOL drew the four-symbol Uno/FSR divider, verified saved metadata/property edits, passed ERC and read complete official 30-net topology. UI binding and automatic sync persisted 34 entities/35 relations with exact A0/supply/ground pins | Four ignored ERC rules are disclosed. Unsupported constructs or oversized complete output refuse; no PCB autorouting claim. Rail analysis correctly reports unknown capacity/demand when ratings are absent. |
| Local folder / code | Link workspace, scan code into graph, bounded reads and state-bound writes; Python environment/package/script/pytest tools with incremental output | Four scratch files saved/read back through SOL; automatic A0/I2C/UART/Wire.h observations verified. User-approved intentional failure exited 2 and was filed in Error logging. Pending cards survive reload. Fresh user-approved build exited 0; pytest exited 0 with 3 passed and 3 non-failing inherited-configuration warnings | Native streaming and UI/API tests passed; live incremental UI output was not directly observed during these completed commands. ForgeTS files/conflict preserved; its durable native folder-picker linkage is not newly claimed. |
| GitHub / GitLab with local Git | Cloud repository sources, local identity matching and status/log/diff; separately gated staged commit and non-force push implementations | Authenticated GitHub sync imported 157 entities and remote SOL code read succeeded. Read-only ForgeTS scan matched its origin to the actual connected source | GitHub writes prohibited; GitLab excluded. Matching repository identity does not prove branch/revision equality or a new durable live clone edge. |
| Isaac Sim | Owned headless lifecycle; pinned SO-101 model; graph-bound limits/sensor pose; finite explicit routine and saved physics readbacks | Full calibrated SOL start/load/pose/clearance/approach-close-lift/stop passed. Clearance reached targets; bottle lifted 37.5209 mm with 8.29553 N contact and 120/120 hold steps; final status stopped | Strict grasp and target flags correctly remain false: two joints exceeded 0.01 rad tracking tolerance. No arbitrary USD/script import, GUI automation or Onshape placement provenance claim. |
| Arduino | Pinned CLI/toolchain probe, gated preparation and offline Uno compilation with verified artifacts | Earlier SOL preparation/recovery cards were rendered. Later direct read-only production probe verified CLI 1.5.1 and toolchain ready | User asked to skip Arduino troubleshooting and hardware verification. Native disposable compile evidence exists; no current product compile or firmware upload is claimed. No board, XIAO driver or physical behavior acceptance. |
| ROS / Live Bench | Existing feature areas outside this acceptance scope | No live proof claimed here | Explicitly excluded by user for now. No sim/real time-aligned telemetry, ROS bridge, Foxglove or hardware claim follows from Isaac routine readback. |
| Fusion, AutoCAD, Altium Designer, SOLIDWORKS on this Linux host | Catalog/platform handling reports unsupported OS and prevents incompatible launch | Platform behavior has implementation/test coverage; final catalog visual acceptance belongs to the current UI pass | Display **“Fusion is not available on Linux”**, likewise for each unsupported tool, rather than an integration error. This is not a claim that their integrations work on supported hosts. |

## Platform catalog scope

Committed `integrations/mcp/*/platform.json` declares Fusion and AutoCAD for macOS
and Windows; Altium Designer and SOLIDWORKS for Windows. All four are unavailable
on this Linux machine. Missing setup for a compatible tool must still be reported
honestly; do not relabel a genuine runtime failure as OS incompatibility. An
unknown browser platform must ask the desktop app to check availability.

## GitHub/GitLab matching audit

The existing local-folder QA explicitly requires a connected, already-synced
GitHub/GitLab source **in the same project**. Matching uses normalized remote host
and repository identity; a foreign repository or provider does not become linked
merely because a local path was selected. Tests in
`packages/api/tests/test_local_links.py` cover provider mismatch, case-folded
GitHub identity, remote changes, delayed repository arrival and cross-project
isolation. These are automated cases, not evidence of real remote authentication.

The earlier I2 completion report records a live `clone_of` edge for the scratch
GitHub clone `solus-test/rover-fw`, but explicitly says its GitHub sibling source
and repository node were **seeded** and GitHub OAuth/sync was not exercised.
Therefore that report proves local graph reconciliation, not arbitrary connected
GitHub/GitLab acceptance. The current Git QA also leaves live commit/push unchecked.
Do not describe either record as complete GitHub/GitLab integration verification.

The current real GitHub read-only sync (157 entities) and remote code read supersede
the earlier seeded-only limitation for authentication and ingestion. They do not
prove local clone reconciliation or writes. The user has restricted GitHub to
read-only and excluded GitLab from current acceptance; do not run the following
remaining write/matching scenarios without a new scope change.

To close the separate matching gap later, a human-controlled disposable repository must be connected via
the normal provider flow, synced in the same project, linked as a real clone, and
observed to acquire the correct graph edge. Repeat with GitLab; verify the edge is
removed when the remote changes. Commit/push and post-write graph refresh need
their own previews, approvals and independent local/remote readback. Agents do
not push in this ticket.

## Guide and tool knowledge

| Knowledge category | Published rows | Live Guide questions verified |
| --- | ---: | --- |
| Onshape | 2 | 3: edit feature, change variable, reorder/check features |
| KiCad | 107 | New 3 passed: wire endpoints/junctions, local/global labels, ERC versus current capacity |
| Code | 10 | New 3 passed: changed/staged/conflicted files, local HEAD/origin versus remote identity, historical file inspection without overwriting |
| Isaac | 7 | New 3 passed: collision approximation, drive/limit tracking, local/world sensor pose and bottle-specific retained-contact evidence |

Counts were read after the reviewed 2026-09-13 scoped seed; an immediate repeat
preserved every live row identity and status. Onshape records were not seeded.
Counts are published knowledge rows, **not full manuals or distinct controls**.
KiCad includes version-specific duplicate controls. Stored Isaac documentation
coverage is 6.0.0; installed runtime is 6.0.1-rc7. Answers must distinguish supplied
official notes, general guidance and installed-version observations. Guide success
does not prove execution. No customer design facts are stored as global knowledge.

## Evidence and next update locations

- `ACCEPTANCE_SOLUSDEV-261.md`: current project, source/model IDs and live checkpoint.
- `COWORK_QA_integration-check-phase1.md`: Onshape operations and remaining gates.
- `COWORK_QA_kicad-development.md`: geometry/import/binding and pending write refresh.
- `COWORK_QA_code-git-development.md`: exact Git consent and remote proof requirements.
- `COMPLETION_SOLUSDEV-249-i2-local-folders.md`: earlier live evidence and seeded-source limitation.
- `COWORK_QA_code-arduino-development.md`: readiness versus native compilation/hardware.
- `COWORK_QA_isaac-development.md`: native outcomes versus product acceptance.
- `COWORK_QA_integration-tool-knowledge.md`: ingestion counts, sources and Guide checks.

Isaac's latest developer verification is 88 native tests, 80.75% native module
coverage, plus real MCP inventory → bridge allowlist → cloud-wrapper coverage.
Its `$ref` advertisement defect is fixed without weakening the bridge filter;
all eight tools survive that boundary. Companion re-advertisement and the bounded live lifecycle/model/routine round trip
have since passed. No observed grasp was reported.

Development-only unlimited credits are enabled for the explicitly allowlisted
account and were smoke-tested through SOL. Real usage accounting and approvals
remain in force. This removes a credit blocker; it does not complete any pending
integration operation above.

## Latest persisted evidence — 2026-09-13

Current owned stack session: `45051`. KiCad property edit fingerprint:
`f9971d6e407364d5:775e258e95e826d8:b759fd0db2fcde87:7f378a7e18ae3eae`.
Webhook sync `01a09ac4-58e8-7499-942b-8cac864df741` succeeded at 12:35:54Z
with four updates and zero errors. Onshape update job
`01a09ac5-40b5-7a6e-8de0-1616614d8ad9` followed verified feature
`FRrBskvCj5sNzwW_1` depth 0.5 → 0.6 mm. Persisted microversion
`eee8cce89814e294a5aafc9e` has volume `13568.091301492 mm³` and dimensions
`[146.05, 2.0000001, 57.15] mm`. That became the baseline for a subsequent
verified restoration from 0.6 to 0.5 mm, job
`01a09ac6-b10a-7199-9d24-e68203c62760`. Automatic graph readback changed volume
`13568.091301492 → 13580.758988469 mm³` (increase `12.667686977 mm³`, matching
π × 6.35² × 0.1), surface area `15863.060938058 → 15859.071115388 mm²`, and
microversion to `004f36210573b501e3a29d29`. Bounds/dimensions were unchanged;
the other Part Studio stayed at `51959.096169737 mm³`. Pocket depth is restored
to 0.5 mm. This proves a numerical persisted geometry delta after automatic edit.
Older unchanged source cursor upgrades are implemented and independently reviewed:
147 connector/call-budget/session-cost/empty-element tests passed. The exact
`cad-geometry-v1` marker triggers reingestion after successful ordinary probes and
is persisted only after successful ingestion; this is implementation/test evidence.

These results supersede older pending claims for KiCad property editing, Onshape
cut/depth editing and Isaac's bounded round trip. They do not complete all phases:
Assembly insertion/mates, full FeatureScript, rail analysis,
streamed code execution and sketch topology remain open.

Latest assembly insertion returned `mutation_unverified` after vendor HTTP 503
Service Temporarily Unavailable. Subsequent read-only SOL `get_assembly` returned
empty instances, occurrences and features: no inserted instance remained observable.
No retry was attempted. This is vendor-transient blocked acceptance, not a proved
implementation defect or a passed insertion. Variable Studio `b08e606a014ca1b1a9716c08` is now found. Its single
`sol_acceptance_length` LENGTH variable was changed from 1 to 2 mm; vendor POST
returned empty HTTP 204, which incorrectly prevented the mandatory post-write GET
and produced `mutation_unverified`. Independent read-only SOL recovery confirmed
expression `2 mm` with empty description. No retry occurred. Endpoint-specific
204 handling passed 122 tests and independent review; live automatic 2 → 1 mm
edit then passed with mandatory internal full-table readback and queued sync job
`01a09ace-366c-7f02-a57c-feee5e51b703`. Final restoration to 2 mm subsequently passed.
The transient false no-connected-source report is fixed: CONNECTED and SYNCING
source states preserve existing authorized access, with 47 tests and independent
review passing. Account grants and project/document scope checks remain enforced;
no reconnect was required.

Post-sync live full-table read independently confirmed `1 mm`. Persisted sync
`01a09ace-37e9-7106-aee6-62af4c3a117c` succeeded at 2026-09-13T12:46:54Z
with three entity updates and zero errors. This was followed by successful restoration to `2 mm`; no reconnect was needed.

Final Variable Studio acceptance passed: fresh 1 mm read, automatic 1 → 2 mm
write, mandatory full-table readback and another successful `get_variables`.
The only variable remains `sol_acceptance_length`, type LENGTH, expression
`2 mm`, description empty. Job `01a09ad0-e42f-76d0-9f98-4394474f6586` led to
persisted sync `01a09ad0-e548-7706-a919-59f77a45a7fe`, successful at 12:49:53Z
with three updates and zero errors. Final target is restored to 2 mm.
