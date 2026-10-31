# SOL depth — architecture (SOLUSDEV-321)

How SOL decides what to look at, keeps a turn inside its budget, reasons over the graph's facts and
looks at renders. Each part lives in its own module, vendor-free, and reads and writes the graph only
through the sanctioned seams (`graph/edges.py:write_edge`, `graph/findings.py:raise_finding`,
`graph/neighborhood.py:to_graph_context` / `is_candidate`).

The tiers, the scope planner, the first tier, the envelopes, the interaction matrix and the
simulation ladder are described in their own documents (`sol-context-layers.md`,
`docs/api/findings.md`, `docs/contracts/checker-interface.md`, `docs/api/simulation.md`). This
document starts with perception (P5) and software depth (P6); the other sections join it as the
cycle's docs pass lands.

## Perception (P5)

Renders are data for semantics (ADR-029). SOL looks at a picture to learn how something looks and
where it sits, never to count, never to trace a connection, and never to read a number the graph
states. One tool does it: `render_view` (`agent/vision/render_view.py`; the tool surface is
`docs/api/solus.md` §6.4).

### One view, chosen by the question

`render_view {entity_id, question ≤ 300, show?}` draws ONE view of the entity, chosen by the
question's words (`choose_view`):

- **A sheet renderer** (a source's companion export): `board` when the question names the board
  (`board`, `pcb`, `layout`, `copper`, `silkscreen`, `footprint`, `traces`), else `sheet` — the
  export's first page.
- **A model renderer** (a scene model or CAD): `face:<side>` for the first side the question names
  (`front`; `back`, `rear`, `behind`; `left`; `right`; `top`, `above`, `overhead`; `bottom`,
  `underside`, `below`, `beneath`), looked at along that face's inward normal; else `bounds`, the
  part's bounds, when it asks about size (`big`, `large`, `long`, `size`, `bounds`, `extent(s)`,
  `dimension(s)`); else `iso`, the isometric view.

The sides are the scene's own frame: front is the +x face, back −x, left +y, right −y, top +z,
bottom −z.

### Who draws it (R104)

`agent/vision/renderers.py` picks by what the entity HAS — never by a product's name (the package is
in the capability-hygiene sweep):

1. **A scene model.** The entity is a `bench_scene_model`, the robot one names (`attrs.robot_id`), a
   part one binds (`attrs.bindings`), or a part the scene's robot `contains` (a live `contains`
   edge). The scene row and that edge are read in the asker's graph scope, like every SOL graph
   read (`current_scope(...).entity_predicate()` / `edge_predicate()`; P5 fix 1, M6), so a scene
   the asker's view hides draws nothing for them. The scene's own file is read as the person
   (`fetch_artifact_bytes`, within the scene's
   size bound) and drawn by the livebench member's offscreen renderer
   (`livebench/src/livebench/sim/offscreen.py`), reached through the optional runtime import
   (`livebench/sessions.py:load_local`'s pattern). The physics engine's renderer is called there
   and nowhere in `solus_api` (`.render()` appears only in `context.py`, `tests/test_context.py`).
   The labels are the entity, then the parts the robot contains (read through
   `load_neighborhood` / `to_graph_context`), at most 16.
   - The text passes P4-T3's parse-based guard (`checked_mjcf`) before anything compiles it: no
     DTD, no comment, no file, no plugin, nothing that multiplies the model. A scene that loads
     mesh files is therefore refused with that reason; primitive-geom scenes render.
   - The scene may not ask the renderer for more than a render's budget (`render_budget_error`):
     an offscreen framebuffer past 4096 px, more than 4 samples, a shadow map past 4096 px, more
     than 16 textures or 16 Mi texels, or height fields past 4 Mi samples is refused before
     anything compiles, the reason naming what asked. The child bounds the compiled model again
     (`bound_for_render`): the framebuffer is the request's size, samples and shadows are
     clamped, the textures re-checked.
   - The engine runs only in a child of its own: a private directory, a scrubbed environment plus
     `MUJOCO_GL=egl`, P4-T3's CPU, memory and file caps (`limit_child`), a 30 s wall timeout. It
     compiles through an empty virtual file system and checks every count before it allocates.
     What the child leaves is read back as untrusted and validated whole.
   - A second, segmentation pass gives each body's pixel bounds. An entity is labelled at its body:
     through the scene's `bindings` (part → joint → the body that joint moves), else by its name
     under the one name rule, `agent/vision.body_key` (lower case, each other run one `_`), which
     the offscreen child also finds its target by (P5 fix 1, M8).
2. **Else the entity's own source, when its connector declares `Capability.RENDER`**
   (`providers_of`). The connector says how, by what it declares:
   - `render_tools` (KiCad): the companion tools that export the view as PDF,
     `kicad.export_schematic_pdf` (`sheet`) and `kicad.export_board_pdf` (`board`). The call goes
     down the person's own bridge session, with the source's `project_path`, within 60 s. The
     tool must be flagged `returns_image` in the Solus-owned allowlist, and its PDF comes back by
     the existing upload path (`publish_artifact` → `artifact_ref`), consumed one-shot through
     `consume_tool_artifact` (R124). The first page is rasterised by
     `agent/documents/pdf.py:render_pages`: no SVG and no other rasteriser. The export is never
     run when the artifact store accepts less than 2 MiB (R124), when no companion is connected,
     or when the companion does not offer the flagged tool; a degraded export (no native
     `kicad-cli`, the Flatpak adapter, no board) is refused with the companion's own reason.
   - `render_view(...)` (Onshape, `connectors/onshape_render.py`): one shaded view of the element
     the entity was synced from, at the synced microversion on the immutable `m/` route, under the
     connector's own scoped, metered connection (`purpose: "agent"`, `label: "agent_read"`), the
     source and its account connection re-read for the picture. It refuses above
     `integration_degrade_ratio` (the quota meter's own rule), without a cached element listing
     for that revision (it never probes), without a meter or a cache, for a document the source
     does not track, and with an expired token (it never refreshes one). One call per
     (microversion, element, view, size), kept in the integration cache.
3. **Else nothing draws it**: `render_view` says so. Empty beats invented.

A connectivity question with wires in scope, or a counting question, gets no render at all: the
scope planner decided it before any prompt (`TurnScope.exclude_renders`, `.counting`), and the
runner binds the decision with the turn (`agent/turn_context.py:PerceptionTurn.renders_refused`).

### The image boundary (R102)

Every image is untrusted bytes until it passes one gate, `bridge/service.py:checked_image`: a PNG or
JPEG by its magic bytes (`agent/screen.py:_SCREENSHOT_MAGIC`), its dimensions read from its header
(`_image_dims`) and at most 4096 px a side, at most 2 MiB. The header read takes the FIRST IHDR or
SOF and a decoder keeps the LAST, so the gate also opens the bytes lazily as that type alone
(headers, no pixels) and refuses unless that size is the header's; the one decode
(`render_annotate.py`) opens only as the gated type and refuses any other size before a pixel is
allocated (P5 fix 1, I1). Nothing decodes an image before the gate, and every renderer's picture
passes it before it leaves `renderers.py`. A companion tool's output
(`consume_tool_image`) is read only for a `returns_image` tool, only as the one artifact that call
uploaded, and only when the bytes are what the companion claimed: a mismatch is dropped with a log
line naming the types, never the bytes. A PDF is accepted by its `%PDF-` header and rasterised at
most 4096 px tall (`render_pages` scales a page to fit both its width and that height; P5 fix 1,
M7); its page passes the same gate. The pull-based `bridge/service.py:fetch_artifact` stays a dormant seam
(no caller); the upload path is the exercised one.

A tool flagged `returns_image` is never offered to the model: `_register_bridge_tools` skips it, so
the model reaches it only through `render_view`.

### Labels, one read, the graph's numbers

- **Annotation** (`render_annotate.py`). Before anything reads the picture, Pillow burns in each
  labelled part's name at its pixel bounds, and a caption band: the subject when it was not placed
  (a net as the net the sheet is about), the view, and each labelled part's extents as the graph
  states them (`attrs.geometry.dimensions`, the CAD import's bounding box). Every label is graph
  text, reduced to printable ASCII and capped, so it can only ever be pixels. Face ids would be
  burned in where a renderer exposes them; none does yet.
- **One read** (`vision_extract.py`). One `gateway.complete` per render: `type: VISUAL_LOG`,
  `purpose: "vision"`, the requester's `user_id`, `session` and `redis`, the turn's `turn_id`. The
  prompt is Solus-authored and question-independent, and it frames the image as data. The call
  counts against the turn's `max_model_calls` through `PerceptionTurn.take_model_call`, which never
  spends the closing round's call; outside a SOL turn nothing is called. Its text is the tool
  result. It never re-routes the turn: the route type is pinned at round 1, and the image never
  rides the turn's own messages.
- **The graph wins** (`vision_postcheck.py`). The read's `number unit` lengths (mm and m, through
  P2-T6's own number tokens and rounding comparison, never a substring search) are compared with
  the graph's extents of the one labelled entity a sentence names. A disagreeing number is replaced
  by the graph's value, with the render's value in brackets, and files ONE
  `vision_fact_disagreement` info finding per (entity, `length`) per render through `raise_finding`
  (`source: "sol"`, `bucket: "length"`; evidence: parsed numbers only).

### Cache and showing (D6, R127)

The subject and its renderer are read in the requesting person's own graph scope
(`bind_scope(resolve_scope(...))`, the read every other tool makes) BEFORE the cache is consulted,
so a cached look is reachable only by someone who may read the subject at that moment; another
project's entity is not found. The cache is in process, keyed by `(project_id, asker, entity_id,
change_signal, view_id)`. The asker is set only for a companion-drawn view: a companion exports
its own person's working copy, which can hold edits not yet synced, so that look is theirs alone
(P5 fix 1, M5); scene and connector views are shared. The change signal digests the renderer's revision (the scene model's id
and version, or the source's cursor) and every labelled entity's id, name and attributes, so a
changed graph is a new picture. It holds values only: the annotated PNG, the checked read and the
lengths the graph won — never an artifact, a finding or anything else a later reader might not be
allowed to see. A hit costs no render, no model call and no finding (its `findings` is empty). Only
a look a model read is kept. Ponytail: 32 looks, per process; Redis-backed when the API runs as
several instances.

The render reaches the person only when asked (`show: true`), and the model is told so where it
chooses: the tool's description and `show`'s own say true only when the person asked to see the
picture, otherwise the read is reported in text (P5 fix 1, M4). Every `show`, a cached look's
included, stores a FRESH TTL artifact for the requesting person, and the result carries its
reference (`artifact_id`, `uri`, `media_type`, `title`, `summary`). The chat shows it as a card
(`agent/stream.py:ARTIFACT_TOOLS`). Pixels never enter model context.

### Deferred

- **M162.** "The sheet containing a net" rasterises the export's first page with the net in a
  caption. Finding the net's sheet, or its place on it, needs the PDF's text layer.
- A scene with mesh files renders once the shared guard can admit assets through the virtual file
  system.

## Software depth (P6)

What a robot's software states becomes graph facts the checkers and SOL read, by structure and
never by running it. Each reader is pure and model-free (`software/`, swept by the vendor,
capability and model-call ratchets).

### ROS workspaces

- **The wire.** The local companion ships a folder's ROS packages as bounded texts
  (`FolderScan.ros`, `integrations/mcp/local/solus/ros.py`): `package.xml`, launch files,
  `setup.py`/`setup.cfg` and the modules of each package's own module directory, never a hidden,
  test or credential-shaped path component (R135), within per-file, per-package and total caps.
  A code host's packages are read through `CodeContentReader` at the synced commit, at most 64
  reads a sync (`connectors/code_content.py:read_software`).
- **The reader.** `software/ros_reader.py:parse_ros_workspace` reads launch files with
  `ast.parse` only, XML through the DTD-refusing `_xml_root`, YAML capped and alias-free, and
  takes each node's direction from its executable's own Python module (R133). Names must match the
  ROS grammar whole, a node's package the package-name rule and its executable an identifier (one
  `.py` or `.sh` suffix allowed); a compiled node lands without topics (M166).
- **The graph.** `ros_node` and `ros_topic` entities under the clone or repo node (`contains`),
  and `graph/inference/ros_edges.py` writes `publishes` / `subscribes` at 0.9 through `write_edge`
  (evidence `config` at the launch line), retiring what a re-sync no longer declares.
- **Live confirmation.** `code.ros2_nodes` / `code.ros2_topics` run one fixed argv each through
  the code fork's planner, sandbox and executor, ungated only when the fork's own judge finds the
  profile system scope (every search-path and load-configuration variable, and any variable
  naming a path in the folder: R136, R137). They run from an empty private directory while every
  judgement stays on the linked folder. In the cloud, `agent/tools/ros_live.py` only RAISES
  standing inferred edges a listing names to 1.0 (`annotate_edge(confirmed_by=bus_enumeration)`);
  a listed name no edge carries creates nothing, since any DDS participant can announce one.

### Module contracts

`software/policy_reader.py` reads a policy's action and observation widths (`Box` spaces,
`action_dim`/`obs_dim`, space shapes, one-feature input/output shapes) and a controller's inputs
(`joints`, `input_dim`, `command_dim` beneath a key that names a controller) from code-host
files; a checkpoint path is recorded and never opened, and a non-literal width is named as
ambiguous. The facts ride on each file's entity (`attrs.module_interfaces`), and
`module_contract_mismatch` compares them within one source whose controllers take one width;
controllers of more than one width leave the pairing `unknown_input`
(`docs/contracts/checker-interface.md`).

### Firmware from the topology

`agent/firmware_recipe.py` writes a board's firmware from what the graph says drives it: the
parts its buses reach, the confirmed `commands`/`reads` edges, the board's pin capabilities and
each part's telemetry channels, with the person's code style. The path is decided before anything
is read (R138), the current file comes through the owned write's dry run, the one model call is
metered as the person, and the turn is routed so `machine.write_file` keeps its card even in Build
mode (R134; `docs/api/solus.md` §6.5).

### Expertise and the register

`agent/expertise.py` sets a member's level per domain (control, electronics, mechanical,
software: novice, working or expert) from their own code sources and the kinds of questions they
ask; `expert` needs both, so repos alone reach `working` at most. Only the four levels are
stored, on the member node, since a teammate can read it, and only when that node already exists
(registering a machine creates it; a sync lands only what the connector produced, R168); a
person's `expertise` preference wins per domain, and the system prompt carries one Solus-authored
register line after the mode note. The two model narrations that take the mode carry it too:
`agent/finding_narration.py` for the owner's stored levels, and `livebench/runs/narration.py`
for the asker's, which the runs route reads as the SOL route does (`turn_expertise`). The
person's own stated `expertise` preference reaches only the SOL chat turn: both narrations read
stored levels alone (the runs route states no override, so `turn_expertise(..., None)`). Levels
are recomputed after a code source's sync and once a
day by the hourly sweep, after its change detection: at most 100 members a run, each cut off at
1 s, inside the job's 300 s timeout.

### Deferred

- **M166.** A compiled ROS node lands with no topics: its direction needs a C++ reader.
- **M167.** A live listing confirms per call (a node's edges from a node listing, a topic's from a
  topic listing); confirming only when both ends were seen needs state across calls.
- **M170.** The first tier's templated text (`agent/deterministic.py`) does not take the register
  yet.
- A local folder states no module interfaces yet: the companion ships ROS texts, not arbitrary
  files.
- A live raise does not publish a graph change hint, so an open canvas shows it on its next
  refresh.

## Outcomes and usage (P8)

Every decision on a proposal is data, and so is every model call.

- **Outcomes.** `services/outcomes.py:record_outcome` writes one `proposal_outcomes` row per
  decision, called by the router that saw it: `routers/sol_confirmations.py` for a card
  (`accepted`, `rejected`, and the gate's own `expired` and `stale`; the card's status is read
  before the decision under the row lock the decision takes, so a repeat click records nothing) and
  `routers/sol.py:_record_build_outcome` for an owned routine Build ran by itself
  (`accepted_auto`). A row holds identifiers and digests only: the tool, a digest of what was
  proposed, the one entity the arguments named when it is the project's own, the decider, the
  decider's own machine, the decision's tool turn, and the design signals. Members list the
  project's outcomes; the machine, the turn and the digest reach only the decider (R146, M6).
  Recording runs in a savepoint and never fails the decision. The table:
  `docs/schemas/proposal-outcomes.md`.
- **The digest.** A code command's card (`command_gate.PLAN_PREVIEW_TOOLS`) is the server's own
  `code.plan`, so its plan fingerprint is the digest; a `plan fingerprint` row on any other card
  could come from model-proposed text and is ignored (I2). Every other digest is sha256 of the
  arguments after error filing's redaction (`_redact_args`, then `redact_value` with no display
  path exempted), in canonical JSON. That is stricter than the stored turn's redaction, so the
  digest cannot be re-derived from the transcript, and proposals that differ only in a `key`-named
  or an entropic argument share one. An auto-run has no card: its digest is always the redacted
  arguments'.
- **Design signals.** `services/change_signals.py:snapshot_signals` maps each source of the
  project to the change token its connector keeps on the sync cursor (commit `sha`, `content_sha`,
  folder `digest`, else sha1 of the cursor), so an outcome can be read beside the design it was
  made against. Revision snapshots are left out; a value is always a hex digest. A card's signals
  are read at the click, before an approved tool runs (a sync that lands while it runs does not
  change them); an auto-run's when it is recorded, right after the routine returns.
- **Usage.** The gateway's ledger attrs carry `purpose`, the routed `tier`, and the call's
  `turn_id` and `project_id` when it has them; a zero-credit call still writes its row. Inside a
  turn every call names both: the runner passes its own; `turn_context.with_turn` binds the turn's
  project beside its id, which a render read and a page read name (`current_project_id()`, R148);
  the firmware recipe and `label_motifs` pass their own, the same project.
  `GET /projects/{id}/usage/turns` lists the caller's own rows for one project, never a balance
  (`docs/api/API.md` §2.9).

### Deferred

- `edited` is in the decision set, but no surface edits a proposal before deciding it yet.
- `proposal_digest` is unkeyed sha256 (a code command's plan fingerprint included): an argument the
  redaction keeps, such as a path, stays confirmable by re-hashing until a dedicated digest key
  makes it HMAC-SHA256 (R147).
