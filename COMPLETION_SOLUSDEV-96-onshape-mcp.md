# SOLUSDEV-96 — Onshape MCP server (Part A) + CAD-00b core

Branch: `SOLUSDEV-60/ons-ui01-confirmation-surface` (off `SOLUSDEV-60-mech-cad-mcp-tools`)
Status: **ready for human review. Not pushed, no MR opened, nothing self-approved.**

---

## What shipped

| #         | Ticket                      | Commit              |
| --------- | --------------------------- | ------------------- |
| A1        | Operations layer + reads    | (earlier on branch) |
| A2        | Connect-time grant, backend | (earlier on branch) |
| A5        | Confirmation round-trip     | (earlier on branch) |
| ONS-UI-01 | SOL chat + confirmation UI  | `f920835`           |
| A2 (UI)   | Connect-time grant picker   | `f3a2b24`           |
| A3        | Write tools                 | `2a0913b`           |
| A4        | Selectors + surgical edits  | `c056784`           |
| B1        | CAD-00b per-fork runtime    | `c7d4955`           |
| —         | **ADR-033** (tier-2)        | `995709a` (no code) |
| A6        | `tool_docs` knowledge store | `ea2da0c`           |
| A2+A5 UI  | Gate audit + hardening      | `ad300ca`,`8c9b812` |
| A7 step 0 | Panel message harness       | `444ae0c`,`c511baa` |
| RUN-01    | **LLM tool-calling runner** | `cceb62b`→`861cd9c`  |
| CAD-02    | Fusion loopback transport   | `08b344a`,`1b0760e` |

Verification: `ruff` clean, `mypy` clean over the changed set (src **and** tests),
**1564 passed / 4 skipped** (baseline 1387), desktop **736 passed / 107 files**, desktop
`typecheck` clean, single alembic head (`59530f556236`). No live Onshape call in CI — every Onshape test is
respx-mocked.

---

## RUN-01 — the reason none of the above actually worked yet

**Every Onshape tool was unreachable.** `plan_tool_calls` regexed a UUID out of the prompt and
emitted at most one `get_entity` call — that was the entire tool-selection logic in the product. So
`set_variable`, `add_feature`, `update_feature`, the selectors and every read tool were registered,
gated, tested and **never invoked by any turn**. Underneath, the gateway was text-only:
`ProviderAdapter.stream()` took one string, every adapter hard-coded a single user message with no
system prompt, and the repo contained no `tool_use` anywhere.

Six commits closed it, and three design decisions in them are worth your review:

**Tool calling is one optional param on the existing `stream()`, not a second entry point.** A
separate `complete_with_tools()` would have duplicated the frequency cap, the spend gate, the retry
policy and the cost hook — and a duplicated gate is where a gate silently goes missing. It follows
the `ImageBlock` precedent exactly. `conversation=None` is byte-identical to before, asserted on the
wire request, so `fingerprint/escalation.py` and `visual.py` were not edited.

**The destructive gate is now structurally unbypassable.** "Every runner MUST consult
`gate_tool_call`" was a comment and a merge-blocker convention — the wrong mechanism when the whole
point is that a mistaken or compromised runner cannot execute a destructive tool. `AgentRunContext`
no longer carries the registry: a runner gets descriptors plus a `dispatch` closure that fuses
gate-then-invoke. It holds no object with an `.invoke()`, so ungated dispatch is unwritable. Three
ratchets keep it that way, including one asserting `registry.invoke` appears in exactly two files.

**The red-team tests were asserting the wrong thing.** They required that *no tool call ever
happens*, which passed only because a regex planner is deaf to prompt content. Against a real model
that is both wrong (a read call is not a violation) and harmful (it would force the runner to be
artificially deaf). Replaced with a seam-level suite that assumes the model is **already
compromised** — a scripted adapter does exactly what each injected payload asks — and asserts the
seam refuses. Those stay meaningful under any future runner because they never test the model's
judgement.

**Five live defects fixed along the way,** all of which existed independently of the runner:
consent-card forgery (the card capped length but passed newlines and bidi overrides, so anyone who
could name a feature could write prose onto the approval surface); unbounded conversation history (a
cost bomb, and one poisoned turn would replay into every prompt forever); raw unredacted tool values
persisted to Postgres and served to the browser; `redact_value` guarding only the bridge path, so an
Onshape variable named `api_key` went straight into model context; and the router never supplying
the identity the runner needs, which would have broken every turn in production while the
scaffold-backed tests stayed green.

## The four things worth your attention

### 1. Writes are reachable, and gated three ways

`confirmation_refusal` was a **hard refusal**, not a prompt: any tool declaring
`requires_confirmation` returned `UNAUTHORIZED` 100% of the time because the flow that would let a
user approve one did not exist. A5 built that flow; ONS-UI-01 built the surface. A write now passes
three independent gates:

1. **The connect-time grant** — enforced server-side in `_prepare`, re-read per call. A read-only
   source, or a source connected before the choice existed, refuses writes. Onshape scopes are
   account-wide, so the token _could_ write; the refusal is ours to make.
2. **The confirmation** — the call parks, the turn streams it, the user decides. Arguments are
   server-side: the decide endpoint takes a decision and nothing else, so what was shown is what
   runs.
3. **The diff** — every write tool describes its own change, so the card shows
   `width: 120 mm → 150 mm`, not the word `onshape.set_variable`.

The card is generic by construction — `{label, before, after}` rows. A firmware flash and a robot
command render through the same component with no Onshape-specific code.

### 2. Nothing invents a payload — this is the load-bearing design decision

I verified against Onshape's published OpenAPI spec (fetched live, 248 paths) that **every BTM
parameter subtype is a `btType`-only stub**: `BTMParameterQuantity-147`, `BTMParameterEnum-145`,
`BTMParameterQueryList-148` and the rest publish no value fields anywhere machine-readable. Writing
`{"expression": ...}` from memory would have been exactly the "plausible fabricated data" you told
me to strip.

So the payload shape is **derived from live data**:

- `add_feature` clones the value field carried by the **live `featurespecs` default** and replaces
  only its value.
- `update_feature` clones the **feature's own parameter objects**.
- A geometry parameter clones the **query object the feature already carries** and swaps its id
  list.
- Anything not derivable that way — an unknown parameter kind, an ambiguous shape, a feature with
  no example to copy — is **refused**, never guessed.

`test_add_feature_follows_whatever_value_field_the_spec_default_uses` proves the code does not
depend on my fixtures having guessed right: change the live default's value key and the operation
follows it.

**What is genuinely spec-derived:** `BTVariableParams` (required `name`+`type`, name pattern
`^[a-zA-Z_][a-zA-Z0-9_]*$`) and the write envelope `BTFeatureDefinitionCall-1406`. Those are
published in full and are used directly.

### 3. A deterministic id is never a tool argument

Onshape face/edge ids are microversion-scoped: the same id can name a different face after the
model changes. A model that saw one in a previous turn will reuse it, and the edit lands somewhere
nobody asked for — silently, because the write succeeds. Community servers hand ids to the model
and inherit that bug.

Instead the model names geometry declaratively (`{"entity": "face", "largest": true}`,
`{"entity": "face", "surface": "plane", "nearest_to": [0,0,0.05]}`) and the selector is resolved
against the live document **at write time**. `resolve_reference` returns a _description_, never an
id, so nothing leaks into a transcript. An ambiguous selector refuses and lists the candidates
rather than picking one — silently choosing among equal candidates is how an edit lands on the
wrong face.

### 3b. The tool-knowledge table is contained by structure, not convention (A6 / ADR-033)

You approved ADR-033 in-session; it landed in its own commit with no code, per ADR-032.

`tool_docs` is the schema's **first global content-bearing table**, so it cannot borrow the
FK+CASCADE containment every other text store relies on. Three properties replace it, each with a
test that fails if it erodes: **no tenant column exists** to hold a reference; the column set is a
**closed list of typed columns** with no `payload`/`extra` bucket a handler could stuff a prompt
into; and **no router imports the writer** (asserted by scanning `routers/` — a table every tenant
reads cannot rely on convention).

One thing worth flagging that the ADR text implies but does not spell out: **a customer's own
`featurespecs` includes custom features they imported — that is customer data.** It stays live-read
through `onshape.get_feature_specs` and is never written here. Ingestion runs over vendor
documentation only.

Search escapes LIKE metacharacters (an unescaped `%` would turn a narrow lookup into a full read of
a shared table) and is hard-bounded at 50. `embedding` exists so vectors are a later backfill rather
than a migration, and stays NULL because `embed()` does not exist.

**No SOL tool exposes it yet, deliberately.** For Onshape, `onshape.get_feature_specs` answers the
same question live, per-document, and includes custom features — strictly better. The table earns
its keep when Fusion/SolidWorks/AutoCAD land, none of which have live introspection. Offering a
model a lookup tool over an empty table would be the same "tools that always fail" antipattern the
secret-store fail-closed rule avoids.

### 3c. The gate was audited adversarially, and it was not holding (`ad300ca`, `8c9b812`)

38 agents over four lenses raised 34 defects; **12 survived adversarial verification**, 22 were
refuted. Two of the confirmed ones were in code I had already reported as done, which is the
argument for running the audit at all.

**`update_feature` could edit geometry the user never saw.** It resolves its selector against the
live model at park time to build the card, and again at execute time to choose what to repoint —
and nothing compared the two. Reachable inside a single turn: the runner parks up to 8 calls, so
approving edit #1 moves the model and edit #2's card is then stale. `rejectMicroversionSkew` cannot
catch it; that guards read→POST, not park→approve.

Fixed **at the gate, not in the tool**: before dispatch, re-run the preview and refuse if it no
longer matches what was displayed (new `ConfirmationStatus.STALE`). One guard, every tool kind —
which is what makes it a gate guarantee rather than an Onshape one. Freezing the resolved id into
the stored args would have been the obvious fix and would have reintroduced the exact stale-id bug
A4 exists to prevent.

**An approval that failed read as success.** The decide endpoint answers 200 for every outcome and
carries the result in the envelope; the renderer treated any 2xx as success and removed the card.
Expired, already-decided, tool-gone and ordinary Onshape failures all told the user a destructive
edit had applied when nothing ran. The subtlety that makes a blanket fix wrong: a *rejection* is
also `ok:false` — not running is its success — so only approvals branch on it.

**Diff values were force-uppercased.** `Mono` uppercases by default and the card never overrode it,
so `#width * 2` painted as `#WIDTH * 2`. Onshape variable names and FeatureScript unit tokens are
case-sensitive: the expression read was not the expression approved.

**Untrusted vendor text led the consent sentence.** `_summarize`'s docstring asserted the
description was always Solus-authored. False for bridge tools, where it is advertised by the
upstream fork — which could describe a destructive tool as "read-only". `ToolDescriptor` gained
`consent_summary`, fed from the allowlist `reason` that was already mandatory on destructive
entries and had never been read by anything. Latent today (no fork is vendored) and live the moment
one is, i.e. exactly at the MCP-03 milestone.

**A tool with no preview now shows its arguments.** Bridge, MCP and shell tools have no
before/after, and previously rendered "could not preview its change" — consent to a bare action
name, for precisely the tool kinds you named. They now render the arguments they will run with,
read from the same stored dict that executes.

**Approval was neither atomic nor durable.** Check-then-act with no row lock, and the status
transition held un-flushed until after the tool ran: two concurrent approvals both executed, and
any failure after the external write rolled `APPROVED` back to `PENDING`. Now `SELECT FOR UPDATE`,
committed before dispatch.

Plus: the card no longer says "SOL wants to change your design" over a shell command, and
`SolConversation` is keyed on the project so a switch cannot carry another project's parked action.

### 4. `set_variable` reads before it writes

`POST .../variables` **replaces the whole studio table**. Writing one variable naively would
silently delete every other one. The operation reads the table, merges the one entry, and posts the
whole thing back. This was the highest-damage bug available in the cheapest tool.

---

## Doc changes (all tier-1, editable directly)

- `docs/integrations/onshape-setup.md` §2 — **rewritten**, not silently reversed. It previously
  forbade `OAuth2Write` outright; it now records your rationale (editing CAD is the product; the
  mitigation is token protection plus the per-edit gate), states that Onshape grants are
  **account-wide** with no per-project scope (verified), and records that `OAuth2Delete` is
  deliberately never requested — feature and instance deletion are both `OAuth2Write`, so `Delete`
  buys nothing and would let a confused agent destroy a customer's document.
- `integrations/mcp/README.md` — the `allowlist.yaml` example **did not load**
  (`upstream_tool_count` is not a field on the `extra="forbid"` model, so the whole file raised and
  the fork would register with zero tools, silently). Removed. Added the CAD-00b launcher contract:
  `SOLUS_MCP_PYTHON`, `.venv/`, `solus/env.allow`, cwd.
- `integrations/mcp/LICENCE_VERIFICATION.md` — **new**. Verdicts from reading LICENSE files, plus
  the pre-vendoring checklist.
- `apps/desktop/CLAUDE.md` — records the H9/vitest-3 `--silent` harness gap.

---

## Licence verification (read from the LICENSE file, never the GitHub API)

| Target                                | Verdict               | Forkable  |
| ------------------------------------- | --------------------- | --------- |
| `andrewbartels1/SolidworksMCP-python` | MIT                   | Yes       |
| `U-C4N/Autocad-MCP`                   | MIT                   | Yes       |
| `AuraFriday/Fusion-360-MCP-Server`    | **SPDX: Proprietary** | **NEVER** |

The AuraFriday repo is the most-starred Fusion result and **the GitHub API reports `NOASSERTION`**
for it while the file says `Proprietary`. Recorded permanently in `LICENCE_VERIFICATION.md`.

---

## What is NOT done, and why — stated plainly

**A7 — step 0 shipped (`444ae0c`); the panel itself is blocked, and one premise is broken.**

Research settled the outbound contract and produced two corrections worth having early: an
**element right panel receives NO document/workspace/element ids** unless its action URL asks via
`{$documentId}` (only `server`, `companyId`, `userId`, `locale`, `clientId` come free — the tab
extension is the opposite, which is what every blog post describing this is actually describing);
and the token is `{$workspaceOrVersionId}`, with `{$workspaceId}` deprecated and `{$name}` syntax,
not `${name}`.

The inbound contract could not be settled and **must not be guessed**. Every published
`SELECTION` field list traces back to somebody reading Onshape's minified bundle. So A7 step 0 is
a dependency-free capture harness that asserts nothing and logs everything, plus a checklist; a
human runs it once against a real session and commits what actually arrived. Contract tests guard
its origin validation and pinned target origin.

**The broken premise — this needs a decision before anyone builds the inbound direction.** Graph
entities are keyed at *occurrence* granularity (`{scope}:{occurrence_path}`,
`connectors/mechanical.py`); nothing ingests face or edge deterministic ids. So even a perfectly
captured `SELECTION` payload has **no row to join to** — "user clicks a face, Solus tells them
something" does not currently have a join at that granularity. Three ways out: ingest at face
granularity (expensive, multiplies the graph), resolve face→part server-side at query time, or
accept that the panel points *into* Onshape rather than reading *out* of it. That is a design call,
not an implementation detail.

**Why the panel itself is not built.** It is blocked on three human gates (developer access, a
public HTTPS origin, OAuth app registration) and on one unbuilt mechanism: the iframe cannot render
team-scoped data without knowing which *Solus* user it is serving, and `{$userId}` is an Onshape id
in a query string, not authentication. Standing up a second auth path is architectural and belongs
in front of you, not inside a feature commit.

**Interference detection — does not exist.** Zero hits for `interfer|collision|clash` across every
path and schema. It is UI-only. Community servers advertising it are doing bounding-box overlap.
**Solus does not claim it.** The honest offer is pairwise `evDistance` via `/featurescript`, clearly
labelled an approximation — not built yet, and it needs your nod that a labelled approximation is
acceptable.

**Sketch-on-existing-face — deliberately not shipped.** The mechanism is sound (`newSketch` imprints
the face, so the offset becomes a constraint against an imprinted edge — what a human does, and it
survives the model changing). But `BTMSketchConstraint-2` is a **bare stub** in the OpenAPI spec.
Shipping a guessed constraint payload is exactly what you told me not to do. It needs one live task:
author a constraint in the Onshape UI and read it back. I cannot do that offline.

**CAD-00b dependency installation — mechanism designed, not built.** The launcher, interpreter
discovery, env allowlist, cwd and root default are done and tested. The hash-verified lockfile
install into `.venv/` is not, because **there is no vendored fork to install anything for** —
`integrations/mcp/` still contains only the four template/doc files. It becomes a concrete, testable
piece the moment the first fork lands, and it must land before either fork's security review.

**Credential DELIVERY to forks — plumbing ready, wire frame missing.** `ServerLaunch.env` is now
populated and merged with the right precedence, so a delivered credential has somewhere to go. The
frame that carries a value _downward_ over the bridge does not exist and `OUTBOUND_TYPES` has no
member for it. Adding one changes `packages/contracts/` — **tier-2, so I did not touch it.** Until
it exists, BYO-licence tools (CAD-03/04) ship gated-but-non-functional.

**B2/B3/B4 — not started, and correctly blocked.** B2 (Fusion) is a **client** of Autodesk's own
server, blocked on **G5**. B3/B4 are forkable (MIT, verified) but their security reviews are a
**human gate for both developers** and CAD-00b's install mechanism must land first, or a signature
given today is voided by CAD-00b landing tomorrow.

---

## Owed live-confirmation run against your tenant

Everything Onshape is respx-mocked, and each fixture records the endpoint it stands for, so this is
mechanical rather than exploratory:

1. **The write envelope** — confirm `serializationVersion`/`sourceMicroversion`/`libraryVersion`
   echoed with `rejectMicroversionSkew: true` is accepted, and that skew genuinely fails loudly.
2. **`featurespecs` `defaultValue`** — confirm it really is a BTM parameter object. The code refuses
   rather than guesses if it is not, so the failure mode is a clear refusal, not a bad write.
3. **`bodydetails` field names** — confirm `faces[].surface.type` / `.area` / `.origin` and
   `edges[].geometry.type` / `.length`. The matcher reads these tolerantly (a missing field loses a
   comparison rather than raising), so a mismatch degrades rather than breaks.
4. **`set_variable` replace semantics** — confirm the merge is genuinely required by writing one
   variable to a two-variable studio.
5. **`BTMSketchConstraint-2`** — author one in the UI, read it back. This unblocks
   sketch-on-existing-face.

---

## Delegated-judgment decisions

- **`InProcessTool.preview` is duck-typed, not part of the `Tool` protocol.** The confirmation flow
  reads it with `getattr`, exactly like a connector's `list_selectable`. No contract change, and a
  tool that cannot describe its change simply omits it.
- **`operation_by_name` uses a deferred import** so `onshape_refs` builds on `onshape_ops`
  primitives without a circular import at module scope. The dependency stays one-way.
- **New variables default to `type: ANY`.** Onshape requires a type and a model rarely supplies one;
  ANY accepts whatever the expression evaluates to, rather than guessing LENGTH and rejecting `4`.
- **`_prepare` was hoisted to module level** to keep `_build_tool` under the complexity gate; the
  same function now serves both `run` and `preview`, so a preview cannot bypass the grant check.
- **The desktop was NOT changed to set `SOLUS_COMPANION_INTEGRATIONS_ROOT`.** The new default
  resolves the packaged case correctly and is the smaller diff; dev already sets it explicitly.
- **The `.venv/bin/python` test fixture is a shell shim**, since git cannot carry a binary. What it
  exercises is the companion's side of the contract — discovery, root containment, handover — which
  is the part that has to be right.

---

## Harness notes (flagged, not worked around)

- **H9 is incompatible with vitest 3's `--silent` parsing** and reports a spurious failure on every
  renderer test edit. Documented in `apps/desktop/CLAUDE.md`; verify with
  `pnpm --filter @solus/desktop exec vitest run <path>`. I did not touch the hook.
- **H9 requires new test files to be `git add`ed** before it can see them.
- **Concurrent mypy runs corrupt `.mypy_cache`** and surface as `INTERNAL ERROR` in the
  `cryptography` stubs. Transient; a serial re-run is clean.
