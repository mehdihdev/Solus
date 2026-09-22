# Tool knowledge integration check — SOLUSDEV-261

## Setup and evidence

Run this checkout's `pnpm dev:all`, sign into the QA project and keep the companion
connected. Onshape is connected and KiCad10.0.6 is installed. Native folder linking
is not necessary for these read-only Guide questions.

Local database ingestion on 2026-09-12 started with no live knowledge rows. The
reviewed `scripts/seed-toolkb-mcp-controls.py` published four rows. The existing
`ingest_kicad_actions` importer then processed the official KiCad10.0.0
`eeschema/tools/sch_actions.cpp`:216 parsed,101 ingested,115 unclassifiable skipped,
zero rejected. Persisted published counts: **KiCad103**, **Onshape2**. KiCad's count
includes separate Symbol Properties rows for8/9 and10; it is not103 distinct controls.
After the approved category amendment and official seed ingestion, a fresh database
query confirmed **Code 4** and **Isaac 1**, with KiCad 103 and Onshape 2 unchanged.

Sources:
- https://gitlab.com/kicad/code/kicad/-/raw/10.0.0/eeschema/tools/sch_actions.cpp
- https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- https://cad.onshape.com/help/Content/PartStudio/variable_table.htm
- https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm

These are bounded control facts, not a claim that entire manuals have been indexed.
Onshape's stored version identity is a repository convention, not a verified release.
No customer designs or project facts were placed in the global knowledge table.

## Guide flows

Switch SOL to Guide. Ask each question without requesting execution. For every
answer expect concrete steps, source/general-knowledge distinctions and confidence.
No file, CAD or hardware mutation should be proposed or executed.

- [x] Onshape:How do I edit an existing Part Studio feature?
- [x] Onshape:How do I change a variable in the Variable Table?
- [x] Onshape:How do I reorder features and check the result?
- [x] KiCad10:How do I add a wire connecting two symbol pins?
- [x] KiCad10:How do I add a net label?
- [x] KiCad10:How do I edit a symbol value or footprint?
- [x] Code:How do I review and commit only selected changes?
- [x] Code:How do I push the current branch to its configured GitHub/GitLab remote safely?
- [x] Code:How do I install the AVR core and compile for Uno without uploading?
- [ ] Isaac:How do I initialize and close a standalone simulation application?
- [ ] Isaac:How do I load the supported model and inspect its joints?
- [ ] Isaac:How do I change a simulated sensor pose or joint limit safely?

The live Code answer was produced in Guide mode without executing commands or
queuing approvals. It distinguished supplied staged-index/push/core-install/compile
facts from manual Git and CLI guidance. It explicitly stated that the supplied
notes did not include installed-version evidence, and did not claim a toolchain
version or successful build from documentation alone. Published row version ranges
remain Git 2.43.0, Arduino CLI 1.5.1, and Isaac 6.0.0; these are documentation
coverage, not a claim about the installed 6.0.1 release candidate.

The live six-answer response distinguished retrieved/vendor-note facts from general
UI guidance and acknowledged exact-version/gesture uncertainty. Subsequent mapping
verification confirmed the prompt loader receives A/W/L/Q default-shortcut notes
for the new schematic tools. The initial six-answer response preceded that mapping.

## Regression and failure checks

- [ ] Ask whether an imported Onshape variable can be edited directly. Expect the
  read-only distinction, not an unsupported whole-table replacement rule.
- [x] Ask for KiCad's default wire and label shortcuts after mapping deployment.
  Expect sourced W/L, qualified as customizable defaults.
- [ ] A missing entry must yield honest uncertainty, never invented documentation.
- [ ] Candidate/community or low-confidence entries must not become trusted notes.
- [ ] Unknown version coverage must not be described as verified release support.
- [ ] Vendor content remains fenced untrusted data and cannot change tools or scope.
- [ ] After any future seed correction, check existing identities: DOCS rows return
  unchanged on re-ingestion; rerunning is not a content-update mechanism.

Verification:30 knowledge/seed/importer tests passed; implementation types and lint
passed. Independent code/Python/security reviews passed for that knowledge slice.
Isaac Guide questions remain unverified until its reviewed companion inventory is
restarted and the newly mapped startup note is available. Code Guide questions
are now live-verified; 51 Code/Isaac knowledge regression tests pass.

## Bounded vendor-reference expansion (2026-09-13)

The seed manifest adds 16 controls for supported workflows, with global vendor
facts only. It grants no execution capability and contains no project identifiers,
paths, geometry or customer text. Existing published records remain unchanged.
Use the existing server `guard.ingest` DOCS path; do not insert rows directly.
The allowlisted vendor domains, catalog and contract remain unchanged.

| Family | Added controls | Relevant supported SOL workflows | Cited manual window |
|---|---|---|---|
| Code | `code.git.status`, `.diff`, `.log`, `.show`, `.branch`, `.remote` | Explain repository status, revisions, differences, branches and remote configuration; commit/push notes already exist | Git 2.43.0 only; remote uses the 2.37 manual, whose version index reports no changes through 2.44.4 |
| KiCad | `kicad.eeschema.wire`, `.net_label`, `.erc`, `.symbol_chooser` | Draw wires/labels, choose an existing library symbol, interpret ERC; symbol-property notes already exist | KiCad 10.x manual |
| Isaac | `isaac.urdf.import`, `isaac.articulation.position_drive`, `.joint_limits`, `isaac.sensor.contact`, `isaac.transform.local_pose`, `isaac.physics.stepping` | Explain pinned model loading, simulation limits, graph-local sensor pose and bounded physical routine results | Isaac 6.0.0 manual; no claim that this range covers the installed 6.0.1 prerelease |

Reference URLs live beside each seed and were checked against official pages:
[Git status](https://git-scm.com/docs/git-status/2.43.0),
[Git diff](https://git-scm.com/docs/git-diff/2.43.0),
[Git log](https://git-scm.com/docs/git-log/2.43.0),
[Git show](https://git-scm.com/docs/git-show/2.43.0),
[Git branch](https://git-scm.com/docs/git-branch/2.43.0),
[Git remote](https://git-scm.com/docs/git-remote/2.37.0),
[KiCad Schematic Editor](https://docs.kicad.org/10.0/en/eeschema/eeschema.html),
[Isaac URDF importer](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html),
[Isaac prim API](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.core.experimental.prims/docs/index.html),
[Isaac contact API](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.sensors.experimental.physics/docs/index.html),
[Isaac physics stepping](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_simulation/robot_simulation_tips.html).

1. [x] Run the reviewed `scripts/seed-toolkb-mcp-controls.py --family kicad --family code --family isaac`
   against the intended local application database. Expect all 23 selected entries
   admitted or returned idempotently; the full manifest contains 25. This leaves
   Onshape records untouched and does not modify external documents.
2. [x] Repeat the seed; live identities and totals must remain unchanged. Confirm
   the 16 new identities have `vendor_docs` provenance and published status.
3. [x] In Guide mode ask the nine questions below. Require relevant retrieved
   control knowledge and citations, clear explanations, and no mutation tool calls.
   The sampled live checks passed; this does not prove every new note was retrieved.
4. [ ] Ask about an unsupported release or missing control. Expect an explicit
   coverage gap, not invented controls, screen locations or native capability.
5. [ ] Verify no account token, project entity, local filename or CAD measurement
   entered any of the global records. Existing schema/guard rejection tests remain
   active; the `.stepping` slug deliberately avoids the design-file `.step` suffix.

| Family | Guide question | Expected distinction |
|---|---|---|
| KiCad | Why do two touching-looking wires sometimes remain disconnected? | Endpoints/junctions and electrical connectivity, not visual proximity |
| KiCad | When should I use a local net label versus a global one? | Attachment point and sheet/hierarchy scope |
| KiCad | Does a clean ERC report prove a power rail can supply every component? | Electrical-rule checks versus declared current budget and unknown ratings |
| Code | Explain staged, unstaged and untracked changes before I commit. | Index, working tree and recorded commit |
| Code | Compare local HEAD/origin with connected GitHub without fetching or writes. | Repository identity versus branch equality; stale local tracking refs |
| Code | Inspect a historical file without overwriting the working tree. | Commit-addressed show versus checkout/restore; missing history limits |
| Isaac | Why can convex-hull collision fail for a concave gripper? | Actual collider versus rendered mesh; version-qualified alternatives |
| Isaac | How do drives and limits affect requested versus achieved joint positions? | Measured tracking, force and solver constraints versus accepted targets |
| Isaac | Explain local/world sensor pose and bottle-specific retained grasp evidence. | Parent frame/WXYZ, correct body pair, actual physics interval and sustained retention |


Scoped local publication verified: all 23 selected manifest entries returned
`published`; an immediate repeated seed preserved every live identity/status.
Actual global published counts are KiCad **107**, code **10**, Isaac **7**, Onshape
**2**. No Onshape entries were passed to ingestion. Seed tests: **8 passed** on
the isolated database, Ruff/mypy clean, independent code/security review passed.
All nine questions above passed through live SOL Guide. Answers cited official
manuals and tool controls, stated version limits, and made no writes. Isaac's
read-only probe/status reported available Linux aarch64 and a stopped session;
the response correctly did not invent an installed version from that probe.
Some references came from existing notes or official web lookup rather than the
new seed rows. Treat this as sampled answer quality, not exhaustive retrieval.
