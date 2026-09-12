# SOL Artifacts — diagrams SOL draws, and errors SOL files

> **Status: IMPLEMENTED (SOLUSDEV-252 S5).** This document describes code that has landed; it is
> descriptive, not a design proposal. Re-verify against the files it cites if it reads stale.
>
> Governing docs: `docs/contracts/agent-tool.md` (the tool interface), `docs/contracts/action-gate.md`
> (what needs confirmation), `docs/api/artifacts.md` (the artifacts routes, TTL, 404 posture),
> `docs/api/solus.md` (the `.solus` sections), `docs/architecture/solus-folder.md` (the project
> `.solus`), DECISIONS.md ADR-031 (fork/allowlist governance), ADR-035, CLAUDE.md §7.
>
> Code: `packages/api/src/solus_api/agent/diagram/{model,build,svg}.py`,
> `agent/tools/make_diagram.py`, `agent/errors_filing.py`, `agent/stream.py`,
> `services/artifacts.py`, `services/solus_config.py`, `routers/solus_config.py`,
> `integrations/mcp/machine/allowlist.yaml`,
> `apps/desktop/src/renderer/src/features/sol/{ArtifactCard.tsx,solChatStore.ts}`,
> `apps/desktop/src/renderer/src/lib/api/solStream.ts`.

---

## 1. What an artifact is

An **artifact** is a byte blob a tool produced, stored outside the graph, addressed by id:

- an `artifacts` row (`project_id`, `scope`, `uri`, `media_type`, `size_bytes`, `created_by`,
  `source_tool`, `tool_call_id`, `retained`, `deleted_at`) plus the bytes in the project's
  `ArtifactStore` (`services/artifacts.py:create_artifact` writes the **bytes first**, then the row —
  a mid-write failure never leaves a row pointing at bytes that do not exist);
- **a TTL buffer by default.** `settings.artifact_ttl_seconds` (3600) bounds it, and
  `sweep_expired_artifacts` soft-deletes the row and removes the bytes past the cutoff. An artifact
  is a hand-off surface between a tool and a person, not storage.
- **retained when filed.** `services/solus_config.py:add_artifact_entry` sets `artifact.retained =
True`, which `_is_expired` honours — the sweep skips it forever — and wraps it in a `document`
  graph entity edged from the project's `.solus` node. From that moment it is a graph node with an
  identity, reachable by `load_neighborhood` and therefore by Impact, not a chat attachment.

So the lifecycle is one sentence: **a tool writes a TTL buffer; the person either files it (it
becomes a retained document node in the graph) or lets the sweep reclaim it.**

Reads are non-destructive and identical in posture to every other artifact read: unknown, foreign,
soft-deleted, expired, or private-and-not-yours all collapse to the same 404 (no existence oracle).
The one consuming path in the codebase is `consume_tool_artifact`, reachable only from the bridge
export acquirer — never from a client route.

---

## 2. The diagram: what the graph knows, and nothing else

`make_diagram` draws a **wiring** diagram (`kind=wiring`, 2 hops: part → net → part) or a **plug-in**
diagram (`kind=plug_in`, 1 hop) around up to `MAX_FOCUS` (8) focus entities.

### Source of truth

`agent/diagram/build.py` is pure — no I/O, no vendor names — and takes exactly two inputs:

1. the bounded `Neighborhood` loaded by `load_neighborhood` (project-scoped; entities outside the
   project simply are not there, so a focus id from another team yields `NOT_FOUND`), and
2. the robot's runtime `HardwareConfig`, assembled read-only from its validated
   per-entity schema-2 entries by `resolve_runtime_config`. Absence stays `None`;
   malformed graph/config authority is refused. The owner never becomes its own
   component. Config assembly, diagram building and rendering failures return a
   portable tool error without exposing private exception text.

Edges become wires only when their `relation_type` is in `WIRING_RELATIONS`
(`connected_to`, `drives`, `reads_from`, `powers`, `bus`, `wired_to`). Containment and mating are not
wiring. Bus lines come from the config's `bus_map`: one `bus` node per protocol, one wire per entry
whose part is in view, labelled `addr <address>`.

### A pin is drawn only when something recorded it

There are exactly three sources for a pin, listed in the `build.py` docstring and nowhere else:

- an edge's `attrs.pins` (what the EDA connectors record on a component → net `connected_to` edge),
- an entity's `attrs.pins` (a connector that recorded the part's own pins),
- a `PartConfig.firmware` key whose name contains `pin` (its value is the pin, the key is the role).

Anything else lands on the `UNKNOWN_PIN` (`"?"`) stub: the pin renders as the italic red text
`unknown pin`, the wire renders dashed, the endpoint is listed in `Diagram.unknown_pins` (as
`<node label>: <wire label>`), and the diagram carries the note

> "Dashed wires end on an unknown pin: the graph does not record which pin they use. Never invent a
> pin the graph does not know — check the schematic or the firmware."

A bus **address** is not a pin, so the part side of every bus wire stays unknown by construction.
The tool's own description repeats the rule to the model, and the tool returns `unknown_pins` so the
model can say what is missing rather than fill it in. **Never invent a pin.**

### Bounds and determinism

`MAX_NODES` 60, `MAX_WIRES` 200, `MAX_LABEL` 60 chars, `_MAX_ENTITIES` 120 on the neighbourhood pull;
truncation adds a note, it does not silently drop. Nodes sort by `(label, id)`, wires by their tuple —
the same graph renders the same bytes.

### SVG safety posture

`agent/diagram/svg.py` emits a document with **no scripts, no `foreignObject`, no external
references** (no `<image href>`, no web fonts, no CSS `url()`); every label goes through
`xml.sax.saxutils.escape`, the `aria-label` through `quoteattr`. `MAX_SVG_BYTES` (200 000) is a hard
ceiling the build bounds already keep us under. Layout is deterministic: controllers/boards left,
nets and buses centre, parts right, with a legend that names the dashed convention.

The renderer's half matters as much: the SVG text is **never** injected into the DOM. `ArtifactCard`
fetches the bytes as a `Blob`, wraps it in an object URL, and shows it as `<img src={objectUrl}>` —
an `<img>` cannot run scripts inside an SVG. The object URL is revoked on unmount.

### Why `make_diagram` is not confirmation-gated

Per `docs/contracts/action-gate.md`, the gate exists for real-world or destructive effects — flashing,
deploying, mutating an external system, deleting graph data. `make_diagram`'s only write is one TTL
artifact row plus its bytes in the project's own store, exactly like `add_solus_entry`'s write. Its
scope (project, user, store) is bound by Solus code at registry construction; the model chooses only
_which_ entities to focus and a title. Nothing it produces re-enters a prompt as instructions: the
model gets back ids, a title, an unknown-pin list and a count — **never the SVG**.

---

## 3. The `artifact` SSE event, and the "File this to…?" flow

`agent/stream.py` adds `AgentEventType.ARTIFACT`. The event is a **reference**, never bytes:

```
event: artifact
data: {"artifact_id":"…","uri":"/api/v1/projects/…/artifacts/…/content",
       "media_type":"image/svg+xml","title":"…","source_tool":"make_diagram","summary":"…"}
```

`AgentEvent.artifact_from_result(tool, result)` is keyed on **both** a Solus-owned allowlist
(`ARTIFACT_TOOLS = {"make_diagram"}`) **and** the result shape (`artifact_id`, `uri`, `media_type`
all strings). A look-alike value from any other tool — or from model-influenced text — emits nothing,
so the model can never make the UI fetch something of its choosing. The runner yields it right after
the tool's `tool_result` (`runtime.py`).

Client side:

- `lib/api/solStream.ts:toSolArtifact` parses the frame defensively and returns `null` when it cannot
  name its bytes; `features/sol/solStream.ts` maps it to `{type: 'artifact', artifact}`.
- `features/sol/solChatStore.ts` appends it to the assistant item's `artifacts`, de-duplicated by
  `artifactId`, each carrying `filedTo: SolusSection | null`.
- `features/sol/ArtifactCard.tsx` renders it under the turn: the image (or a chip for a non-image
  media type), the summary, and the **"File this to…?"** row — a section picker over the five `.solus`
  sections, a **File** button, and **Keep in chat** (which just dismisses the row; the TTL then
  reclaims it).

Filing goes through the **existing** route, not a new one:

```
POST /api/v1/projects/{project_id}/solus/{section}/entries
{"kind": "artifact", "artifact_id": "…", "name": "<the artifact title>"}
```

`add_artifact_entry` marks the artifact retained, creates the `document` entity with
`attrs = {artifact_id, media_type, size_bytes, filename, section}`, attaches it to the `.solus` node,
and records a `SolusEntry(kind=ARTIFACT, author="user")`.

It is **idempotent by construction**: `filedTo` lives on the store item, not on the card, so a
remount or a second click posts nothing (`fileArtifact` returns early when the artifact is unknown or
already filed). A failure rethrows and `ArtifactCard` shows the API's own message inline, under the
row — nothing is marked filed.

---

## 4. Automatic Error logging

When a tool that Solus has marked `files_errors` comes back `ok=False`, the runner files **one**
`.solus` entry in the `errors` section before the client sees the result, so the Workspace already
has the note by the time the person looks.

**Which tools file.** `files_errors` is a field on `ToolDescriptor`, defaulting to `False`, set
**only** by the Solus-owned allowlist (`bridge/allowlist.py:AllowedTool.files_errors`, copied onto the
descriptor) — never advertised or chosen by a companion. Today the flag is `true` on the machine
server's mutating tools (`integrations/mcp/machine/allowlist.yaml`): `run_command`,
`install_package`, `write_file`, `create_environment`, and the other tools that change the person's
machine. Read-only tools (`read_file`, `list_environments`, `env_packages`) are `false` — a failed
read is not an incident worth a permanent note.

**What the entry contains** (`agent/errors_filing.py:format_error_entry`, bounded to
`MAX_TEXT_CHARS` = 4000, each field to 1500 chars):

```
Tool failure: <tool name>
When: <ISO-8601, seconds>
Entity: <entity_id / focus_entity_ids / robot_id / part_entity_id, or ->
Command: <the call's args, JSON, redacted>
Error [<code>]: <the ToolError message>
Filed automatically by SOL — edit or delete this note if it is wrong.
```

The args pass `redact_value` **and** a name-based gate (`token|secret|passw|key`, case-insensitive) —
a bare key named `key` is credential-shaped too. No traceback, no environment, no secret values.

**Author and ownership.** The entry is written through the same `add_text_entry` the `add_solus_entry`
tool uses, with `author="sol"`. The Workspace shows "filed by SOL" and the person edits or deletes it
like any other note (`SolusNodeContent.tsx` renders `errors` entries in a mono body and the SOL
byline off `entry.author`).

**Never fails the turn.** `file_tool_error` swallows every exception and logs a warning naming only
the exception class, the tool, the call id and the project. A filing failure is a log line, not a
failed turn. The filing also emits `solus.entry_added` with `{entry_id, section, kind, tool, auto:
true}` so the data-collection system can tell automatic notes from human ones.
