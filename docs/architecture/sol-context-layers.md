# SOL Context Layers — the eleven layers SOL reasons over

> **Status: IMPLEMENTED (SOLUSDEV-252 S5; prefix-stable ordering SOLUSDEV-321 P0-T4; the scope
> planner SOLUSDEV-321 P1-T1) — see §6.**
> This document is descriptive: it records what the code does today. Re-verify against the cited
> files if it reads stale.
>
> Governing docs: DECISIONS.md ADR-036 (the shipped engineering corpus), ADR-034 (the `.solus`
> layers), ADR-016 (SOL modes), ADR-019 (context budgets), `docs/contracts/sol-interface.md`,
> `docs/architecture/engineering-corpus.md`, `docs/architecture/solus-folder.md`,
> `docs/architecture/sol-window.md` (screen capture), CLAUDE.md §7.
>
> Code: `packages/api/src/solus_api/agent/layers.py` (the shapes and the order),
> `agent/context.py` (assembly, packing, the model-facing surface and its prefix/suffix split),
> `agent/turn_scope.py` (the scope planner: the anchors, the turn's one graph pull, the budget and
> the hints), `agent/reason.py` (the anchor vocabulary), `agent/prompt.py`
> (fencing, the conversation nonce, the synthesis turn), `agent/screen.py`, `agent/runtime.py`
> (the runner), `orchestration/providers.py` (cache breakpoints, cached-token usage). Tests:
> `packages/api/tests/test_context_layers.py`, `packages/api/tests/test_prefix_stability.py`.

---

## 1. The eleven layers, in prompt order

`LAYER_ORDER` in `agent/layers.py` is the whole design in one tuple. Every layer before
`conversation` comes from the project, the person and the turn's anchors: together they are the
**stable prefix** of the prompt, byte-stable across turns that keep the same anchors — the graph
layer changes when a message brings new `@`-mentions, pasted UUIDs or names the scope planner
resolves. Everything that varies with the message follows the history.

| #   | Layer            | What is in it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Where its text lives                                                    |
| --- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| 1   | `preferences`    | The root `~/.solus` engineering preferences (ADR-034 amendment) the person set once, for every project                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | the system prompt (`prompt.py`); the layer reports only its token count |
| 2   | `project_card`   | What the project is — the project card (P0-T5; see below the table)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | one fenced section — stable prefix                                      |
| 3   | `solus_standing` | Project-wide, from the `.solus` rows (`load_sections`): every `goals` and `constraints` entry a person wrote or confirmed (`author != "sol"`), newest first — whole while that costs ≤ 1,000 tokens, else one title line each (first line ≤ 80 chars plus the goal's `GoalMeta.status` or the quantified `ConstraintMeta` bound) — then the `constraints/budgets` document (`find_budgets_entry`), one line per `BudgetLine`. A row SOL filed is a candidate: it never stands here                                                                                                                                                                                                                                                                                                                                                                           | fenced sections — stable prefix                                         |
| 4   | `graph`          | The scope planner's one pull around the turn's anchors (depth 1, 2 on HARD; ≤ 60 entities), kept to what fact edges reach (P1-T1): one curated line per entity — name, kind, domain, `entity_id`, plus `definition_id`, `address` and `path` when present, never an attrs blob — then one triple per edge, `(src) -relation[0.80]-> (dst) — <evidence kind>: <ref>` with its newest three evidence items; a legacy relation reads as its `RELATION_DOCS` line                                                                                                                                                                                                                                                                                                                                                                                                | one fenced section — stable prefix                                      |
| 5   | `solus_scoped`   | The `errors` entries whose `ErrorMeta.entity_id` is an entity of the graph layer, newest first, with status, count and the machine they happened on (`machine_id` → hostname, OS, architecture: one batch read of the live `machine` nodes)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | fenced sections — stable prefix                                         |
| 6   | `findings`       | Open findings observing an entity of the graph layer (`list_findings(…, status="open", subjects=…)`, at most 20), newest-created first: headline, severity, rule, the scoped subjects (≤ 4) and one evidence line of its newest top-level values — no re-raise count or merge history, so a re-raise that changes nothing leaves the prefix byte-identical; every severity renders, and a non-info one (warning or critical, its own one-row read) sets `Context.finding_in_scope`, which P0-T7 routes hard. After them, the part envelopes (P2-T1): one line per quantity — at most four a part, in a fixed order — of each part of the graph layer that has an envelope, with its nominal, warn and limit bounds and where each came from, cited `[envelope:<part>:<quantity>]`, under the same layer cap; a part with none says nothing                   | fenced sections — stable prefix                                         |
| 7   | `conversation`   | The prior turns (the history block) plus the live message                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | the runner's `Turn`s; the layer reports only its token count            |
| 8   | `retrieval`      | Error-history and document hits ranked for this message, plus the `.solus` entries it matches (`search_solus` fetches up to 20; the first k that layers 3 and 5 do not already carry whole — a standing entry degraded to its title stays reachable by its body; `errors` entries render as `error`, the rest as `document`) — those bound to an entity in scope, such as a part's datasheet, first, then the turn's web research when it ran one (P1-T5: ONE `research` section — per finding `claim — "quote" — url (title)`, then the sources no finding cites; every field redacted, the whole clipped to this layer's cap) ahead of the other hits — and, only when the message uses a `scope.domain_keywords.environment` word, the `environment/divergences` table (one line per machine counting each cause, then up to 3 named items, ≤ 200 tokens) | fenced sections — live turn                                             |
| 9   | `corpus`         | The shipped engineering corpus (ADR-036), retrieved through the same `rag_query` seam as a GLOBAL source type, domain-routed, low-confidence chunks marked not dropped                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | fenced sections — live turn                                             |
| 10  | `telemetry`      | Runtime windows — only when the scope planner weights the runtime domain: the message uses a `scope.domain_keywords.runtime` word, or a runtime entity is anchored                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | fenced sections — live turn                                             |
| 11  | `screen`         | What is on the person's display right now — the S3 screen read (`agent/screen.py`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | one already-fenced section — live turn                                  |

`SECTION_LAYER` maps every `SectionKind` onto its layer: `project_card → project_card`;
`solus_standing` and `solus → solus_standing`; `graph → graph`; `solus_scoped → solus_scoped`;
`finding` and `envelope → findings`; `error`, `document` and `research → retrieval`; `corpus → corpus`;
`telemetry → telemetry`; `screen → screen`. There is no second copy of the sections —
`Context.layers` derives the layers from `Context.sections` on read.

**The project card** (layer 2, `agent/project_card.py`) is one `project_card` section, fenced as
data like every other. Its project-wide facts are a `ProjectCard`: the project's name; its
physical robots (entity id, name, `external_ref`, `attrs.host_machine_id`); its sources — type,
name and the capabilities the connector catalog declares (`ConnectorRegistry.catalog()`); and how
many live `.solus` entries each section and subsection holds. The card is cached per project for
600 s under `solus:project_card:<project>` (`ProjectCardCache`, over the app's integration store)
and dropped on every `graph.changed` by the fan-out (§6); a cached fact whose change publishes no
`graph.changed` ages out within that TTL (adding, editing or deleting a `.solus` entry publishes
none — only a typed-metadata change does). What changes without a `graph.changed` is read by the
route per request, with its own session, and never cached (`card_inputs`): open-finding counts per
severity (`graph/findings.count_findings_by_severity` — a raise publishes `finding.*`); the
budgets line (`find_budgets_entry`, worst status first, at most 120 characters, `no budgets` when
there is none — the debounced recompute rewrites it without a `graph.changed`); which robots have
an active bench session (the device ids of `SessionManager.list(status="active")` against each
robot's `external_ref`); and the caller's own machine — the one their live bridge session runs on,
in this project, and only when they own its row: hostname, OS, architecture, up to 8 tool versions
and the last 5 `recent_commands`, each `command_redacted`, `cwd` and `output_tail` redacted and
capped at 200 characters. A teammate's machine, and its commands, never renders; no id the client
sends selects it. A failed read means no card this turn, never a failed message. `render_card`
holds the card to 300 tokens by `estimate_tokens`, dropping `.solus` subsection detail, then source
capabilities, then every robot and every source but the first (`+N more`; a list read at its
50-row limit counts as `50+`; a robot with an active session sorts first), and clipping what still
overflows (the oldest command goes first); every rendered string is redacted and capped (names at
80 characters). The per-request lines sit in the prefix too, so a new finding, a budgets
recompute, a bench session or a new command changes it.

## 2. Precedence, the prefix/suffix split, and caching

The model is told the order in Solus-authored prose, rendered **outside every fence**
(`layers.PRECEDENCE_NOTE`):

> "Blocks up to the conversation run from general to specific; where they disagree, the later,
> more specific block wins. The conversation is what was said. Retrieved evidence and shipped
> references are supporting material, telemetry is what is happening now, and the live message is
> the question."

The runner sends the context in three places (`LlmRunner._opening_turns`, `agent/runtime.py`):

1. **The prefix turn** — `Context.fenced_prefix(nonce)`: the precedence note, then layers 1–6,
   each under a Solus-authored header (`## Layer 4/11 — graph (…)`) and each section as its own
   nonce-fenced data block via `prompt.data_block`. The turn is flagged `cache_breakpoint`.
2. **The history** — one fenced `history` block plus the assistant's acknowledgement, when the
   conversation has prior turns.
3. **The live turn** — `Context.fenced_suffix(nonce)`: the conversation layer's counted header,
   then layers 8–11, then the live message as a fenced `user_message` (or `extension_request`)
   block, with a screenshot's pixels riding the same turn as `images`. Header numbering continues
   across the split. The screen read arrives already fenced under the turn's nonce, so it is not
   fenced twice.

`Context.fenced(nonce)` is the two halves in one string; the runner sends them apart.

Consequences that are load-bearing, not cosmetic:

- **The prefix is byte-identical across the turns of one conversation** that keep the same
  anchors: same `tools`, same `system`, same prefix turn (`tests/test_prefix_stability.py`).
  Retrieval, corpus, telemetry, the screen and the message itself follow the history, so a provider
  prompt cache can hit on every such turn after the first. Three qualifications: the graph scope's
  anchors include the message's own `@`-mentions, pasted UUIDs (`ref_match`) and the names the
  scope planner resolves in it (`name_match`/`ref_match`, `agent/turn_scope.py`), so the graph
  layer — and the scoped layers that follow the anchors once P0-T6 fills them —
  change when a message brings new anchors, and the prefix is byte-stable across turns that keep
  the same anchors; the routing tier sets the layer caps, so the prefix is stable among turns at
  one tier — another tier is another model, with its own cache anyway; and a turn that attaches a
  screenshot appends `prompt.SCREENSHOT_NOTE` to `system`, so it starts a new cache entry. The
  prefix also changes, legitimately, when the project's `.solus` entries or graph change between
  turns.
- **The team's own data outranks shipped knowledge.** The project's blocks are the specific end of
  the prefix, the corpus is supporting material after the conversation, and inside `build_context`
  corpus sections also pack _after_ every tenant hit.
- **Nothing inside a fence can pose as a Solus instruction** (CLAUDE.md §7). Around the fences, the
  text is Solus-authored: layer headers, the precedence note, the per-layer count and "none" lines,
  the history acknowledgement, the extension framing and the synthesis turn. Everything ingested is
  JSON-encoded inside a nonce fence.
- The prompt gets a bare `<layer>: none` for an empty layer — the _reason_ stays in the manifest,
  not the prompt. Header labels avoid the gateway type estimator's trigger words (`screenshot`,
  `logs`, `plot`, …); the layer names themselves are fixed and one of them is `telemetry`, which
  cannot steer a SOL turn's model: the turn passes its interaction context, and the route type is
  derived from that context ahead of any text estimate (`orchestration/resolution.py`).

**One fence nonce per conversation.** `prompt.conversation_nonce(conversation_id)` is
`sha256(b"solus-fence:" + conversation_id.bytes)`, first 16 hex characters. Every fenced surface of
a turn uses it: context sections, history, live message, screen read, vendor tool descriptions
(`prompt.tool_specs(…, nonce=)`) and both preference blocks (`prompt.system_prompt(…, nonce=)`). It
is derived, not secret — no salt and no setting (§7 keeps prompt material out of config and
credential stores) — and containment never rested on it: every body is JSON-encoded with `<`
re-escaped, so the literal characters of a fence token cannot appear inside one. A turn with no
conversation id (tests, other runners) mints a fresh `prompt.new_nonce()`.

**Cache breakpoints (Anthropic).** `cache_control: {type: ephemeral}` goes on the system block, on
the last content block of the prefix turn, and on the last content block of each round's final user
turn — the live message in round 1, the latest tool results after — so later rounds of a turn read
the earlier ones from the cache. That is three breakpoints, under Anthropic's four. OpenAI caches
prefixes of 1,024 tokens and more automatically and ignores the flag; Gemini refuses
conversations.

**The synthesis round** (the last round of a turn) keeps `system` and `tools` byte-identical,
appends `prompt.synthesis_turn()` — the closing instruction as a Solus-authored user turn — and sets
`tool_choice: "none"` (Anthropic `{"type": "none"}`, OpenAI `"none"`). Dropping the tools, as it
used to, changed the request from its first byte, because tools precede the system prompt in the
cache key. `_terminal_reply` still refuses a tool call that arrives anyway.

**Usage.** Anthropic's `input_tokens` excludes cache reads and cache writes, so the adapter reports
`tokens_in = input_tokens + cache_read_input_tokens + cache_creation_input_tokens` and
`tokens_cached_in = cache_read_input_tokens`. `cost.compute_call_credits` bills the cached subset
at the catalog entry's `price_cached_in`; the cache-write premium is not modelled.

## 3. Token budgets, as set in code

The **total** follows the routing tier (SOLUSDEV-321). `models.yaml` `context_budget:` sets it —
trivial 8,000 / standard 24,000 / hard 60,000 tokens — and `layer_scale` sets each layer's cap as a
fraction of it. `LayeredContextBudget.for_tier(tier, config)` (`agent/layers.py`) turns the two into
`LayerBudget` caps. Each share is that layer's `LayerBudget` default over the old flat 4,000-token
total (the defaults still apply when a pull carries a plain `ContextBudget`):

| Layer            | `LayerBudget` default | Share of total | Cap at trivial / standard / hard | Enforced by                                                                                                    |
| ---------------- | --------------------- | -------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `preferences`    | 800                   | 0.2            | 1,600 / 4,800 / 12,000           | its producer — the system prompt; `prompt.py` caps each preference FIELD at `PREFERENCE_FIELD_CAP` = 800 chars |
| `project_card`   | 400                   | 0.1            | 800 / 2,400 / 6,000              | its producer — `render_card`'s own ceiling (P0-T5)                                                             |
| `solus_standing` | 600                   | 0.15           | 1,200 / 3,600 / 9,000            | `build_context` — the `.solus` digest cap                                                                      |
| `graph`          | 1200                  | 0.3            | 2,400 / 7,200 / 18,000           | not binding — the graph floor packs under the total                                                            |
| `solus_scoped`   | 400                   | 0.1            | 800 / 2,400 / 6,000              | `build_context` — the scoped `errors` entries' cap                                                             |
| `findings`       | 600                   | 0.15           | 1,200 / 3,600 / 9,000            | `build_context` — the open findings' cap                                                                       |
| `conversation`   | 6000                  | 1.5            | 12,000 / 36,000 / 90,000         | its producer — the runner's turns                                                                              |
| `retrieval`      | 1200                  | 0.3            | 2,400 / 7,200 / 18,000           | not binding for the ranked hits, which pack under the total; the one `research` section is clipped to it       |
| `corpus`         | 4000                  | 1.0            | 8,000 / 24,000 / 60,000          | `build_context`'s packing (`_under_cap`)                                                                       |
| `telemetry`      | 600                   | 0.15           | 1,200 / 3,600 / 9,000            | not binding — windows pack under the total                                                                     |
| `screen`         | 600                   | 0.15           | 1,200 / 3,600 / 9,000            | its producer — `screen.SCREEN_READ_MAX_TOKENS` = 600                                                           |

`LayeredContextBudget` is a `ContextBudget` that also carries these caps, so every `SolSystems` pull
keeps its existing contract (`agent/interfaces.py` is untouched). `turn_scope.plan_scope` builds it
per turn from the turn's tier and sets `max_entities = 60` — the bound of the turn's one graph pull
— whatever the tier (SEC-H3: a hostile query bounds DB work).

Two bounds apply to a binding layer: **its own cap and the total**, whichever bites first. Layers
whose text lives elsewhere (`preferences`, `conversation`) are _reported_ here, not enforced: their
producers hold the cap and the layer states what it was handed. Every layer's producer has landed
(SOLUSDEV-321), so each binding layer's cap applies to what it packs.

Token counts everywhere come from one estimator, `orchestration/type_estimator.estimate_tokens`
(`len // chars_per_token`, floored at 1; the divisor is `models.yaml` `type_estimator.chars_per_token`).
`tests/test_token_estimator_ratchet.py` keeps any other char/token arithmetic out of `agent/` and
`orchestration/`.

Packing order inside the context (`build_context`, `_pack`): the scoped graph pull is the **floor**
(clipped, never dropped, if ingested content bloats it); the prefix groups pack next — the standing
digest, the scoped `errors` entries, then the findings, each under its cap and what the total has
left; the stable prefix packs before anything that varies with the message, so what it carries
never depends on how much room the message's own hits took; then telemetry, trimmed oldest-window-first; then
ranked retrieval hits; then corpus. Each group packs under its cap and the total with a **strict
cutoff**: the first item that does not fit ends that group, so a less relevant hit never sneaks in
on size alone. Every cut is recorded in `Context.dropped`.

## 4. The honesty rule

**An absent layer is present, with a reason. It is never omitted, and never stubbed with invented
content.** `ContextLayer.empty_reason` is set exactly when the layer has nothing this turn:

| Layer            | `empty_reason` when empty                                                                                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preferences`    | `"no preferences"`                                                                                                                                                                                  |
| `project_card`   | `"no project card"`                                                                                                                                                                                 |
| `solus_standing` | `".solus not loaded"` (no sessionmaker was passed, or the read failed — logged), `"no standing .solus entries"` (loaded, nothing standing), or `"no .solus entry fit the budget"` (`_solus_reason`) |
| `graph`          | `"no graph context"`                                                                                                                                                                                |
| `solus_scoped`   | `"no scoped .solus entries"`, or `".solus not loaded"` when the `.solus` reads did not happen                                                                                                       |
| `findings`       | `"no findings in scope"`, or `".solus not loaded"` when the `.solus` reads did not happen                                                                                                           |
| `conversation`   | `"no conversation reported"`                                                                                                                                                                        |
| `retrieval`      | `"no retrieval hits"`                                                                                                                                                                               |
| `corpus`         | `"no corpus hits"`                                                                                                                                                                                  |
| `telemetry`      | `"no telemetry window on this turn"`                                                                                                                                                                |
| `screen`         | `"no screenshot on this turn"`                                                                                                                                                                      |

Note the three distinct `.solus` reasons: "we could not look", "we looked and there is nothing", and
"there was something and it did not fit" are different facts, and SOL must not present them as the
same one. The reasons travel in `Context.manifest()`, which carries per-section
`{kind, citation, tokens, layer}` and per-layer `{layer, tokens, sections, empty_reason}` plus
`truncated`, the `dropped` count, the turn's `anchors` (`{id, reason}`) and `anchors_dropped`
(`{id, reason, cause}`). **Labels and counts only; never section text** — prompt internals do not
cross the wire, and the citation is the same verified provenance surface the `message` event
carries.

## 5. What the runner passes in

`LlmRunner.run` (`agent/runtime.py`) per turn:

1. The fence nonce: `prompt.conversation_nonce(ctx.conversation_id)` — the router passes the
   conversation id from the route (`routers/sol.py`, `post_message`) — or a fresh
   `prompt.new_nonce()` when the turn has none.
2. `prompt.system_prompt(mode, custom_instruction, engineering_preferences, with_screenshot=…, action_mode=…, nonce=…)`
   — this is where the **preferences** layer's text actually goes — and
   `prompt.tool_specs(ctx.tools, nonce=…)`.
3. `turn_scope.plan_scope(ScopeInputs(message=…, tier=…, mentions=…, pins=…, focus=…, robot_id=…, finding_subjects=…, history_entity_ids=…, not_visible=…), search=…, load=…, disambiguate=…, config=…)`
   (SOLUSDEV-321 P1-T1) — no model call of its own. Anchors, each with the reason it is one, in
   blame order: what the turn names — the focused entity (`focused`), `mentioned`, `pinned`,
   `finding_subject`, `bench_robot`, then any id found in the prose as `ref_match` — then the
   names the message carries, in message order, then the focus trail, nearest the focused entity
   first (`focused` again): navigation history the page sends on its own ranks below what the
   person asks about, so a long trail cannot crowd out a mention or a name. The names are
   word+number pairs such as `servo 3`, part numbers, quoted strings, paths and capitalised words
   — at most 8, one search each of the project's own index through `search`
   (`turn_scope.index_search`: a short read-only session per search). A `name_match`/`ref_match`
   hit is accepted when it scores at least 0.45 or its name holds the name as whole words
   (`turn_scope.term_in_name`); every hit whose name holds it (or that is its exact external ref)
   is tied with the others — only when none does, the top score decides — and a tie holding an
   entity the turn points at (a mention, a pin, the focused entity, a finding's subject, the
   bench robot; never the focus trail or an id pasted in the prose) is settled by that claim,
   with no planner call. At most 5 entities anchor by name (`name_match` or `ref_match`). One
   anchor per entity, capped at `MAX_ANCHORS` = 8, the rest (and any the caller cannot see) kept
   as `dropped`, each with its reason and its cause (`over_cap` or `not_visible`). With no
   anchor at all, the index's top 10 hits for the message are the anchors. Then ONE graph pull
   through `load` (`systems.get_graph_context`, depth 1 — 2 on a HARD turn — at most 60
   entities), kept to the anchors and what fact edges reach from them; each neighbour records the
   relation that reached it (`TurnScope.neighbours`). On a HARD turn whose names tie,
   `disambiguate` — the runner's closure over `gateway.complete` (TRIVIAL, GENERAL,
   `purpose="planner"`, the turn's `turn_id`) under the requester's identity — may settle the
   first tie, once per turn: the message and the candidates are fenced as data, and the reply
   counts only when it names exactly one offered id; otherwise every tied hit stays. The planner
   also returns the tier's `LayeredContextBudget` above and the domain weights
   (`TurnScope.domains`: code, electrical, mechanical, runtime, environment, from the message's
   words and the anchors' own domains) — a runtime weight asks for the 120 s telemetry window, a
   code weight lists the `read_code_file` targets one `commands`/`reads` edge from an anchor
   (`code_targets`) — plus the `type_hint`, `practice_question`, the names nothing resolved
   (`missing`, with their shape), `exclude_renders` and `counting`. History entity ids stay
   hints, never anchors or roots. `tier` is the tier the gateway will route the turn at — HARD
   for a turn that names a finding, else "think harder"'s explicit one, else the complexity
   estimator's on the live message (see _Routing by scope_ below) — so the budget matches the
   model that reads it.
4. `build_context(systems, prompt, project_id=…, scope=…, graph=…, window=…, budget=…, mode=…, sessionmaker=…, preferences_tokens=…, practice_question=…)`
   — packs the planner's graph and makes no graph pull of its own. `project_id` is the tenant
   scope, derived from `ProjectCtx`, never from model output or ingested content. `mode` only
   orders corpus ties (ADR-016): Guide reads fundamentals first, Expert reference first. It is
   never a filter.
5. The builders for what the runner owns: `with_screen(section_text, tokens)` slots the
   already-fenced screen read into the screen layer, `with_conversation(tokens=…)` reports what the
   history plus the live message occupy, and `with_anchors(scope.anchors, scope.dropped)` records
   where the scope was anchored and why.
6. The `context_used` event, then the three opening turns of §2 — the prefix turn, the history, the
   live turn.

**The practice gate** (SOLUSDEV-321 P0-T6). The scope planner reads the `practice_regexes` of
`OrchestrationConfig` — models.yaml `practice_patterns` ("best practice", "how should", "design
review", "is it ok to", "rule of thumb", "what is the right way"), case-insensitive — and
`TurnScope.practice_question` is set when any of them matches the live message; the runner
passes it on as `build_context(…, practice_question=…)`. Only such a turn
consults the shipped corpus: any other turn makes no corpus `rag_query` at all, so it spends
neither that retrieval nor an embedding on it, and its corpus layer reports `"no corpus hits"`.
SOL embeds only with `SOLUS_FINGERPRINT_EMBEDDING_ENABLED` set — `main.py` builds `DbSolSystems`
with an embed fn only then — so by default every SOL retrieval runs full-text and a turn makes no
embedding call.

**Routing by scope** (SOLUSDEV-321 P0-T7). The runner settles round 1's tier and type itself,
deterministically and with no model call (`type_estimator.round_one_complexity` and
`round_one_route_type`); from round 2 on both axes stay pinned to round 1's choice. _Tier_: a
turn about a finding runs HARD, passed explicitly, above "think harder" too. A turn that names
one — `finding_id`, whose live subjects become `finding_subject` anchors — is bumped before
the scope is planned, whatever the finding's severity, so one `tier` sets both the budget and
round 1. An open non-info finding (warning or critical) on a part in scope that only the findings
read inside `build_context` turns up (`Context.finding_in_scope`) bumps round 1 alone: the context
keeps the budget it was packed at, with no second `build_context` — the scope planner (P1-T1)
leaves that read where it is. An info finding is an advisory note: it renders in the findings
layer and leaves the tier alone. _Type_: `type_estimator.round_one_route_type` passes `type=CODE`
when the scope planner's `type_hint` says the turn is about code — a `code_file`, `code_module`
or `arduino_sketch` among its anchors (the anchored entities' kinds, never their neighbourhood's),
or a live message the type estimator reads as code (`route_type_for_kinds`) — and the measured
input,
`estimate_tokens(prompt.flatten(turns))` exactly as the gateway measures it, fills at most 80 % of
the window of the CODE role at round 1's tier. Otherwise it passes `type=None` and the context
derives GENERAL, as before. The margin is there because an explicit type refuses on window
overflow (`resolution.resolve_routing`) where a system-routed one escalates. VISUAL_LOG and
LONG_CONTEXT are never made explicit here; a screenshot still gets its own VISUAL_LOG extractor
pass.

## 6. Wiring status

All eleven layers are present on every turn, and all eleven are fed on a live turn (P0-T6 filled
`solus_scoped` and `findings`). `LlmRunner.run` (`agent/runtime.py`):

- passes the request's **`sessionmaker`** to `build_context`, so the project's live `.solus`
  entries and open findings load into the standing, scoped, findings and retrieval layers
  (`agent/solus_layer.py`). Without it the standing, scoped and findings layers each report
  `".solus not loaded"`.
- passes **`preferences_tokens`**, counted off the same `engineering_preferences` mapping
  `prompt.system_prompt` JSON-encodes into the system prompt (`_preferences_tokens`), so the
  preferences layer does not say `"no preferences"` while the prompt carries them. The
  answer-styling `custom_instruction` (SOLUSDEV-233) is deliberately not counted here — it is a
  different layer's business.
- calls **`with_screen`** with the already-fenced S3 read, so the screen section renders inside
  layer 11 in order and appears in the manifest.
- calls **`with_conversation`** with the tokens of the history plus the live message
  (`_conversation_tokens`), so the conversation layer reports what the surrounding turns occupy.
- calls **`with_anchors`** with the scope's anchors and dropped anchors.
- calls **`with_card`** with `project_card_section(sessionmaker, project_id, ctx.project_card)` —
  the cached card, built on a miss, rendered with the inputs the route read for this request
  (`routers/sol.py`, `post_message`, `card_inputs`) — which puts the card first in `sections`; it
  renders in layer 2. Without inputs (tests, other runners), or when the card cannot be built
  (logged, never raised into the turn), the layer stays `"no project card"`.
- fences everything with the conversation's nonce (§2), sends the prefix and the live turn as
  separate turns around the history, and marks the cache breakpoints (`Turn.cache_breakpoint`;
  `_round_conversation` flags each round's final user turn).

**The graph-changed fan-out** (`graph/graph_changed_fanout.py`) is what drops a cached card.
`LiveHub.on_graph_changed` holds one callback, and both processes install the same one:
`GraphChangedFanout(graph_changed_callbacks(sessionmaker=…, enqueue=…, store=…))` in `main.py`'s
lifespan and in `connectors/worker.py:_on_startup`. The list holds the debounced budgets recompute
(SOLUSDEV-320 resolution 18) and `ProjectCardCache(store).invalidator()`. Each callback is awaited
in order under a 2 s bound, the hub's own publish bound: a failure or a timeout is logged and the
rest still run, so a stalled store cannot hang a graph-writing request. The synchronous `close()`
— the API's exit stack and the worker's `_on_shutdown` call it — closes every callback that has
one, each isolated the same way. A later
consumer appends itself to `graph_changed_callbacks` and touches neither host. The hub fires it in
the publishing process only: with Redis both processes share the store, so a worker sync drops the
API's cached card; without Redis the worker's store is its own, so the API's card is dropped by the
API's own publishes (inline syncs run there) and otherwise ages out after 600 s.

The `context_used` frame carries **labels and counts**: per section `{kind, citation, tokens}` (a
section's layer is derived from its `kind` through `SECTION_LAYER` — the wire carries no second
copy), `truncated`, the `dropped` count, the per-layer `layers` rows
`{layer, tokens, sections, empty_reason}`, the `anchors` (`{id, reason}`) and the `anchors_dropped`
(`{id, reason, cause}`). The desktop reads `sections`, `truncated` and `dropped` today and ignores
the rest until P1-T6 renders it.

Tests: `tests/test_context_layers.py` (the machinery), `tests/test_sol_reasoner.py` (the live-turn
wiring — the manifest names the `.solus` and screen layers, the preference and conversation notes
reach the prompt, and the screen read is sent exactly once), `tests/test_prefix_stability.py` (the
byte-stable prefix, the history before everything message-dependent, the synthesis round, the
conversation nonce, containment under a known nonce), `tests/test_providers.py` (the breakpoints
and cached-token usage on the Anthropic wire).

## SOL page labels (2026-10-24)

The SOL page's right column labels the per-user `custom_instruction` "CUSTOM INSTRUCTIONS —
applies to every chat on this account": it is a system-prompt input, not a layer, and there is no
per-chat variant. Its FILES & IMAGES section lists the project's `.solus` artifact entries, which
reach the model by name only — `file <name> (<media_type>)` in layer 3 when filed under goals or
constraints, else as a retrieval hit when the message matches the name (P0-T6) — hence "SOL sees
them by name". Its NODES IN CONTEXT pins travel as `MessageCreate.pins` (at most 8, anchor reason
`pinned`) and typed `@`-mentions as `mentions`; both enter the graph layer as anchors.

## SOLUSDEV-260 repository content follow-up

`read_code_file` is a read-only, project-bound in-process tool. It resolves an
entity UUID through the authorized graph, derives its connected code source and
relative file path, and returns bounded, line-numbered text with provenance. A
graph-context entity line carries its explicit `entity_id` — and, since SOLUSDEV-321
P1-T1, only the curated `definition_id`/`address`/`path` attrs, never the attrs blob —
so SOL can call the reader without confusing source IDs with entity IDs. The scope
planner lists the code one `commands`/`reads` edge from a code question's anchors as
`TurnScope.code_targets`. A
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
