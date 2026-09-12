# SOL Context Layers — the five layers SOL reasons over

> **Status: IMPLEMENTED (SOLUSDEV-252 S5), runner wiring complete — see §6.** This document is
> descriptive: it records what the code does today. Re-verify against the cited files if it reads
> stale.
>
> Governing docs: DECISIONS.md ADR-036 (the shipped engineering corpus), ADR-034 (the `.solus`
> layers), ADR-016 (SOL modes), ADR-019 (context budgets), `docs/contracts/sol-interface.md`,
> `docs/architecture/engineering-corpus.md`, `docs/architecture/solus-folder.md`,
> `docs/architecture/sol-window.md` (screen capture), CLAUDE.md §7.
>
> Code: `packages/api/src/solus_api/agent/layers.py` (the shapes and the order),
> `agent/context.py` (assembly, packing, the model-facing surface), `agent/reason.py` (the
> per-query plan that sets the budget), `agent/prompt.py` (fencing), `agent/screen.py`,
> `agent/runtime.py` (the runner). Tests: `packages/api/tests/test_context_layers.py`.

---

## 1. The five layers, weakest first

`LAYER_ORDER` in `agent/layers.py` is the whole design in one tuple:

| #   | Layer           | What is in it                                                                                                                                                                                       | Where its text lives                                                    |
| --- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1   | `corpus`        | The shipped engineering corpus (ADR-036) — general robotics knowledge, retrieved through the same `rag_query` seam as a GLOBAL source type, domain-routed, low-confidence chunks marked not dropped | fenced sections in the context                                          |
| 2   | `preferences`   | The root `~/.solus` engineering preferences (ADR-034 amendment) the person set once, for every project                                                                                              | the system prompt (`prompt.py`); the layer reports only its token count |
| 3   | `project_solus` | The project's own evidence: the graph neighbourhood, telemetry windows, error history, retrieved documents, and the project `.solus` entries                                                        | fenced sections in the context                                          |
| 4   | `screen`        | What is on the person's display right now — the S3 screen read (`agent/screen.py`)                                                                                                                  | one already-fenced section                                              |
| 5   | `conversation`  | The surrounding turns plus the live message                                                                                                                                                         | the runner's `Turn`s; the layer reports only its token count            |

`SECTION_LAYER` maps every `SectionKind` onto its layer: `corpus → corpus`; `graph`, `telemetry`,
`error`, `document`, `solus → project_solus`; `screen → screen`. There is no second copy of the
sections — `Context.layers` derives the layers from `Context.sections` on read.

## 2. Precedence: later overrides earlier

General → specific. The model is told so in Solus-authored prose, rendered **outside every fence**
(`layers.PRECEDENCE_NOTE`):

> "Layers below are ordered from general to specific; where they disagree, the later, more specific
> layer wins."

`Context.fenced(nonce)` emits that note, then each layer in order under a Solus-authored header
(`## Layer 3/5 — project_solus (this project's graph, runtime windows, retrieved evidence, .solus
entries)`), then each section of that layer as its own nonce-fenced data block via
`prompt.data_block`. Those header labels are deliberately worded to avoid the gateway type
estimator's trigger words (`telemetry`, `screenshot`, `logs`, `plot`, …) — Solus prose must not steer
the model choice. The screen read arrives already fenced under the turn's nonce, so it is not fenced
twice.

Consequences that are load-bearing, not cosmetic:

- **The team's own data outranks shipped knowledge.** Corpus is layer 1, the weakest, and inside
  `build_context` corpus sections also pack _after_ every tenant hit.
- **The person's preferences outrank the corpus** but sit below the project's facts.
- **Nothing inside a fence can pose as a Solus instruction** (CLAUDE.md §7). Layer headers, the
  precedence note and the per-layer "none" lines are the only Solus-authored text in this region;
  everything ingested is JSON-encoded inside a per-turn nonce fence.
- The prompt gets a bare `<layer>: none` for an empty layer — the _reason_ stays in the manifest, not
  the prompt, because reason wording would otherwise feed the gateway's route-type estimator.

## 3. Token budgets, as set in code

`LayerBudget` (`agent/layers.py`) — the defaults, all of them:

| Layer           | Cap (tokens) | Enforced by                                                                                                    |
| --------------- | ------------ | -------------------------------------------------------------------------------------------------------------- |
| `corpus`        | 4000         | `build_context`'s packing (`_under_cap`)                                                                       |
| `preferences`   | 800          | its producer — the system prompt; `prompt.py` caps each preference FIELD at `PREFERENCE_FIELD_CAP` = 800 chars |
| `project_solus` | 2500         | `build_context` (the `.solus` digest cap) and the packing loop                                                 |
| `screen`        | 600          | its producer — `screen.SCREEN_READ_MAX_TOKENS` = 600                                                           |
| `conversation`  | 6000         | its producer — the runner's turns                                                                              |

`LayeredContextBudget` is a `ContextBudget` that also carries these caps, so every `SolSystems` pull
keeps its existing contract (`agent/interfaces.py` is untouched). `reason.plan_query` builds it per
query with `max_tokens = 4000` (`_CONTEXT_MAX_TOKENS`) and `max_entities = 200`.

Two bounds apply to a fenced layer: **its own cap and the total**, whichever bites first. With
today's numbers `project_solus` (2500) is stricter than the total, while `corpus` (4000) equals it —
so the layer caps are what stop any one layer eating the turn, and the total is what stops the sum
doing it. Layers whose text lives elsewhere (`preferences`, `conversation`) are _reported_ here, not
enforced: their producers hold the cap and the layer states what it was handed.

Packing order inside the context (`build_context`): the scoped graph pull is the **floor** (clipped,
never dropped, if ingested content bloats it), telemetry trims oldest-window-first, then ranked
retrieval hits, then `.solus`, then corpus — each group under its cap with a **strict cutoff**: the
first item that does not fit ends that group, so a less relevant hit never sneaks in on size alone.
Every cut is recorded in `Context.dropped`.

## 4. The honesty rule

**An absent layer is present, with a reason. It is never omitted, and never stubbed with invented
content.** `ContextLayer.empty_reason` is set exactly when the layer has nothing this turn:

| Layer           | `empty_reason` when empty                                                                                                                          |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `corpus`        | `"no corpus hits"`                                                                                                                                 |
| `preferences`   | `"no preferences"`                                                                                                                                 |
| `project_solus` | `".solus not loaded"` (no sessionmaker was passed), `"no .solus entries"` (loaded, empty), or `"no .solus entry fit the budget"` (`_solus_reason`) |
| `screen`        | `"no screenshot on this turn"`                                                                                                                     |
| `conversation`  | `"no conversation reported"`                                                                                                                       |

Note the three distinct `.solus` reasons: "we could not look", "we looked and there is nothing", and
"there was something and it did not fit" are different facts, and SOL must not present them as the
same one. The reasons travel in `Context.manifest()` — the `context_used` SSE payload — which carries
per-section `{kind, citation, tokens, layer}` and per-layer `{layer, tokens, sections, empty_reason}`
plus `truncated` and the `dropped` count. **Labels and counts only; never section text** — prompt
internals do not cross the wire, and the citation is the same verified provenance surface the
`message` event carries.

## 5. What the runner passes in

`LlmRunner.run` (`agent/runtime.py`) per turn:

1. `prompt.system_prompt(mode, custom_instruction, engineering_preferences, with_screenshot=…)` —
   this is where the **preferences** layer's text actually goes.
2. `reason.plan_query(ctx.prompt, mentions=ctx.mentions)` — deterministic, no model call: graph
   anchors (mentions first, capped at `MAX_ANCHORS` = 8), degree 2, a 120 s telemetry window only for
   runtime-shaped queries, `k = 5`, and the `LayeredContextBudget` above.
3. `build_context(systems, prompt, project_id=…, scope=…, window=…, budget=…, k=…, mode=…)` —
   `project_id` is the tenant scope, derived from `ProjectCtx`, never from model output or ingested
   content. `mode` only orders corpus ties (ADR-016): Guide reads fundamentals first, Expert
   reference first. It is never a filter.
4. The `context_used` event (the manifest), then the turns: history as a fenced `history` block, then
   `context.fenced(nonce)`, then the screen section when there is a screenshot, then the live message
   as a fenced `user_message` (or `extension_request`) block, with the screenshot's pixels riding the
   same turn as `images`.

`Context` exposes two builders for the layers whose text the runner owns:
`with_screen(section_text, tokens)` slots an already-fenced screen read into the screen layer, and
`with_conversation(tokens=…)` reports what the history plus the live message occupy.

## 6. Wiring status

All five layers are fed on a live turn. `LlmRunner.run` (`agent/runtime.py`):

- passes the request's **`sessionmaker`** to `build_context`, so the project's live `.solus`
  entries load into the `project_solus` layer. Without it the layer reported `".solus not loaded"`
  on every real turn — honest, per §4, but never anything else.
- passes **`preferences_tokens`**, counted off the same `engineering_preferences` mapping
  `prompt.system_prompt` JSON-encodes into the system prompt (`_preferences_tokens`), so the
  preferences layer no longer says `"no preferences"` while the prompt carries them. The
  answer-styling `custom_instruction` (SOLUSDEV-233) is deliberately not counted here — it is a
  different layer's business.
- calls **`with_screen`** with the already-fenced S3 read, so the screen section renders inside
  layer 4 in precedence order and appears in the manifest. It used to be appended after
  `context.fenced(nonce)`: it reached the model, but out of order and invisible to the manifest.
- calls **`with_conversation`** with the tokens of the history plus the live message
  (`_conversation_tokens`), so the conversation layer reports what the surrounding turns occupy.

The `context_used` payload stays **labels and counts**: per section `{kind, citation, tokens}`,
plus `truncated` and the `dropped` count. A section's layer is derived from its `kind` through
`SECTION_LAYER` — the wire carries no second copy. `Context.manifest()` additionally exposes the
per-layer `{layer, tokens, sections, empty_reason}` rows for any surface that wants them; the SSE
event does not carry them today.

Tests: `tests/test_context_layers.py` (the machinery), `tests/test_sol_reasoner.py` (the live-turn
wiring — the manifest names the `.solus` and screen layers, the preference/conversation notes reach
the prompt, and the screen read is sent exactly once).

## SOLUSDEV-260 repository content follow-up

`read_code_file` is a read-only, project-bound in-process tool. It resolves an
entity UUID through the authorized graph, derives its connected code source and
relative file path, and returns bounded, line-numbered text with provenance. A
graph-context entity line carries its explicit `entity_id` before attributes so
SOL can call the reader without confusing source IDs with entity IDs. A
remote read uses the last successfully synced immutable commit, never an implicit
branch HEAD. The existing source credential resolver and configured provider client
own authentication; callers cannot supply hosts, credentials or arbitrary repos.

For an authenticated caller with a matching machine-local clone, the current saved
working-copy text is preferred, including uncommitted edits, and labeled as local.
The match must prove normalized repository identity from a fresh companion scan,
match the requested branch, and bind to that user's live project/machine session.
Existing local.scan_folder and the approved narrow machine.read_code_file capability are used. A missing
or changed local match does not imply a successful remote read: fallback is explicitly
labeled with its immutable remote revision. Binary, oversized, traversal and
credential-file inputs are refused. Ingested file text goes through the existing
structured, redacted untrusted native tool-result boundary and never changes tool scope.

The descriptor directs SOL to read a mentioned file before explaining its contents,
and continue bounded reads for related code when needed. A metadata-only entity is
not sufficient evidence for a code explanation. Personal branch selection is
wired through a revision-consistent graph view; shared Source.config is not changed
by a personal selection.

The native `machine.read_code_file` primitive is internal to the graph reader,
not registered as a model-facing tool. Fixed instructions direct repository
explanations through `read_code_file`; the separate general file reader retains
its confirmation gate.
