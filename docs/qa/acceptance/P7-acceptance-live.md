# P7 acceptance, live proof (SOLUSDEV-321 plan §3 "P7 acceptance"; dispatch legs 1–5 with "P7 as landed + fix round 1" and "After fix round 2"): in process, copy of the dev DB, scripted model text, no provider

One harness process, `acceptance/p7_accept_live.py`, in process (httpx.ASGITransport: no listening
socket) against `solus_sol` and the branch Redis on 6390. Every SOL turn went through the
production route `POST /api/v1/projects/{p}/sol/conversations/{c}/messages` (SSE) with
`app.state.agent_runner = LlmRunner(adapters=<P7AScriptedModel>)`: the real runner, reasoning
parser, gate, park, gateway, metering and ledger. Only the provider's text was scripted, so every
`<reasoning>` block below is this harness's fixture. The raw SSE body of each of the 20 turns is kept
as `acceptance/p7_sse_<turn>.txt`, and every grep below ran on those files with GNU
`/usr/bin/grep` (the shell's `grep` here is a parallel ugrep wrapper whose output order varies).
The desktop half was proven by its vitest files, run by hand: there is no Electron here. One run,
no void attempt.

## Verdicts

- **1. A Build proposal shows the reasoning block above its card and no raw JSON in the chat: PASS.**
  - 1a (the block in one chunk): exactly one `reasoning` frame, equal to the fixture, then the
    proposal. Frame order:
    `context_used, token, reasoning, token, tool_call, tool_result, tool_confirmation, token, message, done`.
  - 1b (the same block cut across two chunks, at character 119 of its 238-character JSON, inside
    `"deleting the note`): the same frame (`1b_same_frame_as_1a: true`), the same token text
    (`1b_same_tokens_as_1a: true`) and the same frame order.
  - No `token` or `message` frame of any turn carries `<reasoning>` or a block key. The key grep
    matches exactly the 9 `event: reasoning` data lines; the escaped-key grep (a key inside a token
    or message string) exits 1; the tag grep matches only 2e, the prose that quotes the tag (leg 2).
  - Once per card: 1c, two proposals in one turn, one per model round → two frames, each directly
    before its own card (`edit_solus_entry` card ← "Say which tie spacing applies…",
    `delete_solus_entry` card ← "Remove the outdated wiring note.").
  - A decided card takes its block with it: `SolChat.reasoning.test.tsx` "puts each card’s
    reasoning directly above that card, and takes it away with the card" ✓ (vitest, by hand).
  - Stored assistant turns hold only the closing prose (no `<reasoning>`, no key) for every leg-1
    turn.
  - M4 (1e): a closing reply that was only a block, with a card waiting → `message.content`
    `"See the proposal below."`.
  - Observation 1: two proposals in ONE model round, with a block before each (1d), give one frame:
    the second block is dropped (`reasoning block dropped: a second block`), so the second card
    carries no block. This is API.md §2.9's documented rule ("a second block in the same round's
    text"); the dispatch's "two proposals in one round → two frames" holds when each proposal has
    its own model round (1c). For a ruling.
- **2. A malformed block is dropped and the proposal still shows: PASS.**
  - 2a `<reasoning>{not json</reasoning>`: 0 `reasoning` frames, dropped `malformed`; the tokens
    are `"Reviewing the note.\n"` and `"\nProposing an edit."`; `{not json` appears nowhere in the
    stream; the `edit_solus_entry` card is there.
  - 2b, a block that never closes (40,047 characters in 2,001 chunks): **`REASONING_BLOCK_CAP` =
    4,096** (+ 11 characters a closing tag needs). The parser's held body peaked at **4,096**
    characters (probed after every chunk), went oversize, held 3,111 at the end, and was dropped
    `never closed`. Tokens: `"Reviewing the note.\n"` only; the card is there; the turn closed
    normally (`message`, `done`, no `error` frame).
  - Fix round 2: an unterminated fenced ` ```json ` body (2c), an unterminated `[{…` (2d) and a
    brace-free `["raise the lid", "move the port"]` (2f) each leave **no** raw JSON in the stream
    (grep for the fence, `json\n`, `"what"`, the block's words: exit 1), each dropped
    `never closed`, each with its card.
  - An unterminated plain sentence quoting `<reasoning>` (2e) streams back as text: tokens and
    `message.content` are the sentence exactly as written, and it is stored so.
- **3. Pills: PASS** (server side live; desktop by vitest).
  - The message's verified citations, as the stream carries them: `[finding:01a18cb9-c0e9-7452-a52a-1eff9a1998cb]`,
    `[solus:constraints:01a18cb9-c0fe-711a-8cf5-53b918153738]`,
    `[entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]` (servo 3, the pulled anchor).
  - Stripped, plain text in the prose only: `[entity:<unknown>]`
    (`bcd7ce0e-dea3-449c-9698-c988df6700d4`, cited only), and the two UUIDs pasted into the
    question: another project's part (`968af080-…`, G's servo 3) and a nonexistent one
    (`f7d2f47c-…`). Both are `ref_match` anchors in `context_used`, neither is a scoped anchor, and
    neither is a citation.
  - The context's format line, as the model was sent it: "Cite an entity this turn is anchored on
    by its token, exactly as given: [entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]." (3a and 3b);
    no line on any turn whose pull returned no anchor; 1d's name-matched `.solus` note got its own.
  - P0 prefix pin unchanged: `tests/test_prefix_stability.py` and
    `test_context_layers.py::test_the_graph_layer_offers_the_tokens_of_the_anchors_the_pull_returned`
    passed in the proxy slice.
  - Desktop (vitest by hand): `SolScreen.test.tsx` "finding and solus pills open their surfaces" ✓
    (the brief's `SolChat.test.tsx::…` name lives in `SolScreen.test.tsx`, P7 report deviation 2),
    `BenchScreen.test.tsx` "opens the Findings pane on the finding a SOL citation pill requested,
    then clears it" ✓, `shellStore.test.ts` benchFinding ×2 ✓, `ReasoningBlock.test.tsx` 5/5 ✓.
- **4. Guide answer with the tool version: PASS.**
  - D's own machine reports `kicad-cli` `9.0.2` (stored through `PUT …/members/me/machines/{id}`,
    the companion's own `tool_versions`). The Guide answer: **"For placing a net label in your
    KiCad: No vendor documentation covers KiCad 9.0.2: not sure where that is in KiCad 9.0.2."**
    The sentence is the `kicad.add_net_label` tool's fenced `tool_knowledge` note that
    `placed_tools` built from the owner-gated machine block (`project_card.machine_block` →
    `[["git", …], ["kicad-cli", "9.0.2"], ["python3", …]]`).
  - The read is release-specific: `kicad.set_symbol_property` kept its vendor note, because the
    dev copy has a `>=8.0 <10.0` note for that control; the four drawing tools have `>=10.0 <11.0`
    notes only and got the sentence.
  - Knowledge queries in that one Guide turn: 14 version-less (the route's read, one per mapped
    control: `TOOL_CONTROLS` has 14 rows) and **5 release reads, all `kicad`** (the family alone,
    not 14).
  - Without a version (4b, D's machine reports no `kicad-cli`): no release read, and every KiCad
    tool keeps its version-less vendor note ("Place Net Labels: Place Net Labels Default shortcut:
    L."). The generic wording needs a tool with no note at all (4c, the KiCad reads scripted
    empty): **"No vendor documentation covers KiCad: not sure where that is in KiCad."**
  - Release read scripted to fail (4d): **"Vendor notes unavailable for KiCad 9.0.2: not sure
    where that is in KiCad 9.0.2."**
  - Owner gate (4e): teammate E's companion claiming D's machine id gets no machine block, no
    release read and the version-less note.
- **5. Untouched invariants: PASS.**
  - 5a: one Build owned routine auto-ran. The policy decided `true` for `machine.write_file`, the
    companion got 3 dry runs then 1 write, `tool_result` ok
    `{"bytes_written":66,"changed":true,"path":"notes/p7-build.txt","verified":true}`, no card, the
    file sha256 `97aa18ee…6e67` = the checklist's.
  - 5b: one forced card still appeared. With `force_confirmation: true` the policy decided `false`
    and the gate parked a `pending` `machine.write_file` card with its full preview rows; 1 dry
    run, 0 writes, the file absent.
  - Both turns carried a `reasoning` frame before the call: the block changed no decision.
- **Desktop behaviour beyond vitest (Electron): NOT VERIFIED here** (no display; the vitest files
  the dispatch names stand in: 11 files, 142 passed).

**Model calls: 33 scripted, 0 real, 0 refused, 0 unscripted.** Each was one `gateway.stream`
(purpose `answer`, this turn's id) answered by a `P7AScriptedModel`: 33 `model call start` lines
and 33 `credit_ledger` `usage` rows. 0 refusing-adapter reaches, 0 real adapter-registry builds, 0
rounds left in the script. 0 processes started.

Ready to paste into the SDD ledger:

> P7 acceptance (live, in process, DB copy `solus_sol` at a32000000006, Redis `solus-redis-321`,
> the production SOL route with `LlmRunner(adapters=<scripted>)`: 33 scripted model calls, 0 real,
> 0 refused, 33 `model call start` lines, 33 usage rows; egress loopback-only; 0 processes). Leg 1:
> one `reasoning` frame with the fixture's shape before `tool_call`/`tool_confirmation`; the same
> frame and tokens with the block cut across two chunks; two proposals in two rounds → two frames,
> each before its own card; no token/message frame holds `<reasoning>` or a key (9 key hits, all
> `event: reasoning` data lines); a block-only close with a card → "See the proposal below.".
> Observation: two blocks in ONE round → one frame (second dropped, documented). Leg 2:
> `{not json` dropped `malformed`, card shown; a never-closed 40,047-character block held at most 4,096
> of `REASONING_BLOCK_CAP` 4,096 (+11), dropped `never closed`, the turn closed normally; fenced
> json, `[{…` and a brace-free array left no raw JSON; prose quoting the tag streamed back as
> written. Leg 3: citations `[finding:01a18cb9-c0e9-…]`, `[solus:constraints:01a18cb9-c0fe-…]`,
> `[entity:d34a1e11-…]`; another project's pasted UUID, a nonexistent one and an unknown cited one
> stayed plain text; the format line lists exactly the pulled anchor. Leg 4: "No vendor
> documentation covers KiCad 9.0.2: not sure where that is in KiCad 9.0.2." from the owner's
> machine block; 5 release reads, all KiCad; no version → notes stand, no note → "…covers KiCad:
> not sure where that is in KiCad."; failed read → "Vendor notes unavailable for KiCad 9.0.2: …";
> a teammate claiming the machine gets no release. Leg 5: owned `machine.write_file` auto-ran
> (policy `true`, 1 write, sha matches); `force_confirmation` → policy `false`, pending card, 0
> writes. Desktop vitest by hand: 11 files, 142 passed. Proxies: 650 passed (27 API files, one process). Report:
> `docs/qa/acceptance/P7-acceptance-live.md.

## Run identity

| Item     | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Run time | **Harness:** command 12:12:23.284Z → 12:12:30.347Z, exit 0 (internal 12:12:24.601Z → 12:12:29.608Z). **Vitest:** 12:18:36.182Z → 12:18:39.938Z, exit 0. **Proxy pytest:** 12:19:48.454Z → 12:23:11.908Z, exit 0.                                                                                                                                                                                                                                                                                                 |
| Branch   | `SOLUSDEV-321-sol-checker-algorithm`                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| HEAD     | `f21d0224` (`f21d022455b9372e829bd4d2c0e811e24376cc77`) before and after. `git status --short` empty before the run, after the run, after vitest and after the proxies. `.coverage` md5 `7571ebfd2af623167baf221f5af68076` before the run and the same after the proxies (not moved, no checkout needed).                                                                                                                                                                                                        |
| Database | `solus_sol`, asserted from the server by the harness (`select current_database()`); `alembic_version` `a32000000006`. Nothing applied, created or dropped.                                                                                                                                                                                                                                                                                                                                                       |
| Redis    | `redis://127.0.0.1:6390/0`, the branch's `solus-redis-321`, dbsize 0 before. `solus-redis-1` was not touched.                                                                                                                                                                                                                                                                                                                                                                                                    |
| Harness  | `/home/beeboss/Solus/.superpowers/sdd/pasted-content-id-24a5-sol-precious-pillow/acceptance/p7_accept_live.py`. Evidence beside it: `p7_accept_live_result.json` (every frame, every scripted round with the conversation it was sent, every probe), `.stdout`, `.stderr`, `.time`; the 20 SSE bodies `p7_sse_<turn>.txt`; the greps `p7_grep_frames_and_tags.txt`, `p7_grep_json_keys.txt`, `p7_grep_leg2.txt`, `p7_grep_leg3.txt`, `p7_grep_leg4_5.txt`; `p7_vitest.{log,time}`; `p7_proxy_pytest.{log,time}`. |
| Commands | Harness: `cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_DATABASE_URL='postgresql+asyncpg://solus:solus@localhost:5432/solus_sol' SOLUS_REDIS_URL='redis://127.0.0.1:6390/0' timeout 900 uv run --frozen --no-sync python <harness>`. Vitest and proxies: below.                                                                                                                                                                                                                                             |

## Environment recipe as executed

1. **Database.** `solus_sol` held P6's leave-behind: 38 users, 42 projects, 77 memberships, 49
   `credit_ledger` rows (15 `usage`), 273 findings, 1 machine, 1,781 entities, 2,117 edges, 166
   `.solus` entries, 7 conversations, 29 turns, 20 tool confirmations, 126 tool-knowledge rows
   (107 `kicad`), 0 data events.
2. **Environment.** The harness refuses to start unless exactly `SOLUS_DATABASE_URL` and
   `SOLUS_REDIS_URL` hold the prescribed values, and re-checks the `SOLUS_*` set after its
   imports. `SOLUS_TEST_DATABASE_URL` was set only on the proxy pytest's command line.
3. **Settings, in code** (as P6): `Settings(_env_file=None, supabase_jwt_secret=<token_urlsafe(32) per run>, supabase_jwt_audience="authenticated", rate limits 100_000, sync_inline=True, fingerprint_embedding_enabled=False, artifact_local_root=<TemporaryDirectory>)`. The database
   and Redis URLs were asserted equal to the exports; `bridge_allowlist_root`
   `/home/beeboss/Solus/integrations/mcp`, so the real allowlists load.
4. **App.** `create_app(settings, create_async_engine(solus_sol))`, then
   `hardware_connections.owner = RuntimeOwner(<tmp>, <tmp>)`,
   `agent_runner = LlmRunner(adapters={anthropic, google, openai: P7AScriptedModel})` and the Narrator's
   `_complete = partial(gateway.complete, adapters=<refusing>)`. The lifespan was not run.
5. **The scripted model.** `P7AScriptedModel.stream` pops the next scripted round for a call whose
   gateway `purpose` is `answer` (anything else raises, recorded) and records what the round was
   sent: the system prompt's sha and action-mode line, whether it holds `prompt.REASONING_NOTE`,
   the offered tools (each KiCad tool's decoded `tool_knowledge` note), the turns, and every line
   holding "Cite an entity this turn is anchored on". A round yields its text chunks as written
   and its tool uses under the provider-safe name (`machine.write_file` → `machine_write_file`;
   all 14 resolved to an offered spec), then `Usage(len(query)//4, len(text)//4)`. Leg 4's replies
   quote the knowledge note the round's own tool spec carried (`p7a_quote`).
6. **Companions** (`P7ACompanion`): in-process `BridgeSession`s whose hello inventory the real
   allowlist gates (`validate_inventory`). `machine.*` calls are answered by the companion's
   builtin `MachineServer`, encoded by `solus_companion.dispatch.map_result`, parsed by the cloud's
   `parse_frame` and handed to `ingest_result` (7 frames, 7 `InboundFrame`s, 0 violations).
   - D (P4) and E: `MachineServer(None, which=…, capture=…)`. Its own `_tool_versions` asked
     `--version` of the fixed binaries through the two scripted seams: `kicad-cli` → `9.0.2`,
     `python3` → `Python 3.12.3`, `git` → `git version 2.43.0` (K1), and the same without
     `kicad-cli` (K0). No binary ran.
   - The KiCad tools are hand-written advertisements (deviation 2): `set_symbol_property`,
     `add_symbol`, `add_wire`, `add_net_label`, `mark_no_connect`, admitted
     `requires_confirmation: true` by the real allowlist. They were offered, never called.
   - F (P5): `MachineServer(<scratch workspace>)`, advertising `write_file` only (admitted
     `requires_confirmation: true`).
7. **Probes, recording only** (each wraps the original by module or class attribute and never
   raises): `ReasoningParser.feed`/`flush` (per parser: chunks, characters, the held body's peak
   after each chunk, oversize, frames, what `flush` gave back), `reasoning_frame._dropped` (the
   `why`), `knowledge.query_entries` (every read; legs 4c and 4d script it, recorded beside each
   call), `runtime.placed_tools` (the KiCad notes before and after, the card's machine),
   `project_card.machine_block`, `BuildExecutionPolicy.prepare`, `citations.reply_parts` (the
   anchors, the scoped anchors, every served citation), the gateway's `stream`/`complete`, a root
   log handler at INFO and one at DEBUG on `solus.agent.reasoning_frame`. 0 probe errors.
8. **Order of steps.** Seed → leg 1 (1a–1e, A) → leg 2 (2a–2d, 2f, 2e, B) → leg 3 (3a, 3b, C) →
   leg 4 (bind K1, PUT, 4a; bind K0, PUT, 4b, 4c; bind K1, 4d; E binds K1, 4e) → leg 5 (5a, 5b, F)
   → ledger read → teardown. Each turn in a fresh conversation except 3b (3a's). Seven people kept
   every person under the 20-calls-a-minute frequency cap (at most 17 a person). Then the greps,
   the vitest run, the pytest guard in its own call, and the proxies.

## Why no real provider was reachable

1. **The runner's adapters are the script.** `LlmRunner(adapters=…)` hands the gateway one
   `P7AScriptedModel` per catalog provider (`anthropic`, `google`, `openai`); the routes picked
   `openai` every time. 33 reaches, all `purpose answer`, each answered by the round scripted for
   it; 0 unscripted; 0 rounds left.
2. **Every other gateway call gets the refusing adapter** (a call whose caller named none): 0.
   The Narrator's `_complete` carries the refusing adapters too: 0.
3. **The real adapter registry raises.** `gateway.build_adapter_registry` records and raises: 0
   reaches.
4. **No credentials.** `InMemorySecretStore`; `secrets_key` unset, `aws_region` None,
   `supabase_url` None; the JWT secret is per run.
5. **No `.env` read.** `DotEnvSettingsSource._read_env_files` refuses and records: 1 refusal
   (`/home/beeboss/Solus/.env` at import). The stderr line is toolkb's ephemeral vote-salt notice.
6. **Egress and spawn guards.** Only loopback 5432/6390 may connect and only loopback names
   resolve: 8 attempts — `bind ::1:0` denied (urllib3's import-time IPv6 probe, as P3–P6), resolve
   `localhost:5432` ×3, connect `127.0.0.1:5432` ×3, connect `127.0.0.1:6390` ×1. Every way to
   start a process (`subprocess.Popen`, `subprocess.run`, `os.fork`/`forkpty`/`posix_spawn`/
   `posix_spawnp`/`system`) records and raises: 0 attempts.
7. **Web research failed closed** on every turn:
   `solus.deps web research unavailable: ToolException code=unauthorized` (the Brave fork's
   discovery refuses without a key, before any process; P1).

| Count                       | 1 (a/b/c/d/e) | 2 (a/b/c/d/f/e) | 3 (a/b) | 4 (a/b/c/d/e)    | 5 (a/b) |
| --------------------------- | ------------- | --------------- | ------- | ---------------- | ------- |
| Scripted model calls        | 2/2/3/2/2     | 2/2/2/2/2/1     | 1/1     | 1/1/1/1/1        | 2/2     |
| `reasoning` frames          | 1/1/2/1/2     | 0/0/0/0/0/0     | 0/0     | 0/0/0/0/0        | 1/1     |
| Cards (`tool_confirmation`) | 1/1/2/2/1     | 1/1/1/1/1/0     | 0/0     | 0/0/0/0/0        | 0/1     |
| Refusing / real reaches     | 0             | 0               | 0       | 0                | 0       |
| Companion frames            | –             | –               | –       | 2 (the two PUTs) | 4 / 1   |

`credit_ledger` gained 40 rows: 7 `trial_grant` (A–G) and 33 `usage` (A 11, B 11, C 2, D 4, E 1,
F 4), one per model call. Routes: `openai_standard` (`gpt-5.6-sol`) ×23, `openai_trivial`
(`gpt-5.6-luna`) ×8, `general_hard` (`gpt-6-astra`) ×2 — leg 3's two rounds, which a warning
finding in scope makes HARD (P0-T7). The costliest was 2b's never-closed round, −41 credits for
the scripted 10,011 output tokens. A `model call start` line as logged:

```
model call start call_id=33be8206-af03-4473-93a1-0c4bd072e319 provider=openai model=gpt-5.6-sol role=openai_standard complexity=standard type=general purpose=answer turn_id=b58ada27-69f7-4757-9e20-9b20b157adf4
```

## Seed (ids for the record)

People were minted as `tests/conftest.py::make_token` does and provisioned by `/users/me`; each
team and project came from `POST /api/v1/teams` and `POST /api/v1/teams/{id}/projects`; E joined
D's team through `POST /teams/{t}/invites` 201 → `POST /invites/{token}/accept` 200.

| Who / what                                                                                  | Id                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A / **P1** (Build proposals)                                                                | `01a18cb9-bbfb-7d76-99c7-98198f7a2535` / **`01a18cb9-bc8d-7cc0-b349-53bf3643c7d8`**                                                                                                         |
| B / **P2** (dropped blocks)                                                                 | `01a18cb9-bc1f-730d-8a80-2b507d66d37b` / **`01a18cb9-bcd6-7e3a-a61c-e47b5405a11b`**                                                                                                         |
| C / **P3** (pills)                                                                          | `01a18cb9-bc33-7371-b738-419d6f305d06` / **`01a18cb9-bd04-7d06-8a47-5ac527ec93ef`**                                                                                                         |
| G / **PG** (another team)                                                                   | `01a18cb9-bc78-73c8-846c-6fe26a0cf99f` / **`01a18cb9-bd31-7ef3-b62e-276ea7f3cac4`**                                                                                                         |
| D (owner), E (member) / **P4** (KiCad release)                                              | `01a18cb9-bc43-70cc-99df-473024422140`, `01a18cb9-bc51-7b9a-81bc-f2d89b59f155` / **`01a18cb9-bd5e-73cd-ac61-00e2e506d107`**                                                                 |
| F / **P5** (Build invariants)                                                               | `01a18cb9-bc64-7e3c-9125-7f670507fa75` / **`01a18cb9-bd8b-7a76-8bc7-8f282e414d44`**                                                                                                         |
| P1 documentation notes (`POST …/solus/documentation/entries`)                               | `01a18cb9-bde0-…cd27` (cable routing), `-bdf5-…c880` (old wiring), `-be02-…f18b` (tie spacing), `-be12-…4bfc` (spare harness), `-be28-…c63e` (power-up order), `-be38-…c851` (label sheets) |
| P2 documentation notes                                                                      | `01a18cb9-be45-…d22b`, `-be52-…30ce`, `-be5d-…55ff`, `-be6c-…1fc8`, `-be78-…3bef4`, `-be84-…3263` (the same six texts)                                                                      |
| P3 fake arm (`seed_fake_arm`, production writers)                                           | robot `a68bf680-4430-47a6-bb16-4344d011327b`, bus `710d605f-…`, brain `0e692e9d-…`, **servo 3 `d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b`**                                                      |
| P3 finding (`raise_finding`, `tracking_error_stall`, warning, subjects servo 3, bus, brain) | **`01a18cb9-c0e9-7452-a52a-1eff9a1998cb`**                                                                                                                                                  |
| P3 constraint (`POST …/solus/constraints/entries`, author user)                             | **`01a18cb9-c0fe-711a-8cf5-53b918153738`**: "Servo current: no servo on the arm may draw more than 2 A for longer than 1 s."                                                                |
| PG fake arm                                                                                 | robot `5dda4bf9-…`, **servo 3 `968af080-b7d8-4564-870e-38238c581a14`** (the "another project" UUID)                                                                                         |
| Machines (companion ids)                                                                    | K1 `cfd796345f034235a320e241033c77a4` (D: `kicad-cli 9.0.2`), K0 `6242355d18ec41489725dd1be0b7cd99` (D: no `kicad-cli`), F `c9fbb27f49be432ca7721a3e6f51fdeb`                               |

## Leg 1: a Build proposal (A in P1, `action_mode: do`)

**1a, the block in one chunk.** Round 1 was ONE text chunk, then the proposal:

```
"Checking the cable-routing note.\n<reasoning>{\"considered\": [\"shorten the cable-routing note\", \"split it into two notes\"], \"ruled_out\": [{\"what\": \"deleting the note\", \"why\": \"the team still routes cables by it\"}], \"proposing\": \"Replace the note with a clearer two-sentence version.\"}</reasoning>\nProposing a clearer version."
ToolUse(edit_solus_entry {entry_id: 01a18cb9-bde0-…cd27, text: "Cable routing: run the servo leads along the left rail. Tie them every 5 cm."})
```

Round 2: `"The edit waits on its card for your approval."`. The stream as received
(`p7_sse_1a-one-chunk.txt`, the `context_used` data line left out: no anchors, no citation):

```
event: token
data: {"text":"Checking the cable-routing note.\n"}

event: reasoning
data: {"considered":["shorten the cable-routing note","split it into two notes"],"proposing":"Replace the note with a clearer two-sentence version.","ruled_out":[{"what":"deleting the note","why":"the team still routes cables by it"}]}

event: token
data: {"text":"\nProposing a clearer version."}

event: tool_call
data: {"args":{"entry_id":"01a18cb9-bde0-7950-a80e-d5fba000cd27","text":"Cable routing: run the servo leads along the left rail. Tie them every 5 cm."},"call_id":"p7_1a","tool":"edit_solus_entry"}

event: tool_result
data: {"call_id":"p7_1a","error":{"code":"unauthorized","message":"edit_solus_entry is now waiting for the person to approve it — they have been shown exactly what it would do. This is not a failure and it does not need retrying: do not propose it again in this turn. Carry on with anything else the task needs. Edit a note in this project's .solus (edit_solus_entry) with entry_id='01a18cb9-bde0-7950-a80e-d5fba000cd27', text='Cable routing: run the servo leads along the left rail. Tie them every 5 cm.'","retryable":false},"ok":false,"value":null}

event: tool_confirmation
data: {"args":{"entry_id":"01a18cb9-bde0-7950-a80e-d5fba000cd27","text":"Cable routing: run the servo leads along the left rail. Tie them every 5 cm."},"confirmation_id":"01a18cb9-c245-71ef-b982-2f5fc3caf1e7","preview":[{"after":"Cable routing: run the servo leads along the left rail. Tie them every 5 cm.","before":"Cable routing: run the servo leads along the left rail and tie them every 5 cm.","label":"Entry"}],"summary":"Edit a note in this project's .solus (edit_solus_entry) with entry_id='01a18cb9-bde0-7950-a80e-d5fba000cd27', text='Cable routing: run the servo leads along the left rail. Tie them every 5 cm.'","tool":"edit_solus_entry"}

event: token
data: {"text":"The edit waits on its card for your approval."}

event: message
data: {"citations":[],"content":"The edit waits on its card for your approval.","role":"assistant"}

event: done
data: {"conversation_id":"01a18cb9-c108-7cf1-8e16-0724acd0b145","turn_id":"01a18cb9-c25d-716b-a7a7-916d4313a461"}
```

The frame equals the fixture (`1a_frame_equals_fixture: true`), precedes the `tool_call` and the
card. The parked card `01a18cb9-c245-…` is `pending` in `tool_confirmations`. Stored turns:
`user, tool, assistant`, the assistant's content `"The edit waits on its card for your
approval."`. Every one of the 25 Build rounds' system prompts held `REASONING_NOTE` verbatim;
none of the 8 Guide rounds' did:

> Before you propose a change, write one <reasoning>{"considered": ["..."], "ruled_out": [{"what": "...", "why": "..."}], "proposing": "..."}</reasoning> block holding only that JSON — at most 12 entries in each list, each string at most 200 characters and "proposing" at most 400 — saying what you weighed, what you ruled out and why, and the change you propose; Solus shows it to the person above the proposal and never as your reply.

**1b, the block cut across two chunks.** Chunk 1 ended inside the JSON, chunk 2 held the rest:

```
chunk 1: "Checking the cable-routing note.\n<reasoning>{\"considered\": [\"shorten the cable-routing note\", \"split it into two notes\"], \"ruled_out\": [{\"what\": \"deleting the note"
chunk 2: "\", \"why\": \"the team still routes cables by it\"}], \"proposing\": \"Replace the note with a clearer two-sentence version.\"}</reasoning>\nProposing a clearer version."
```

The shown frames of `p7_sse_1b-two-chunks.txt` (`grep -A1 '^event: token\|^event: reasoning'`):

```
data: {"text":"Checking the cable-routing note.\n"}
data: {"considered":["shorten the cable-routing note","split it into two notes"],"proposing":"Replace the note with a clearer two-sentence version.","ruled_out":[{"what":"deleting the note","why":"the team still routes cables by it"}]}
data: {"text":"\nProposing a clearer version."}
data: {"text":"The edit waits on its card for your approval."}
```

Same frame order as 1a, `1b_same_frame_as_1a: true`, `1b_same_tokens_as_1a: true`, its own
pending card `01a18cb9-c308-7630-8252-912117384ac1`. The streaming parser of 1b's round 1 (probed)
took 2 chunks (323 characters), held the 119-character half body between them and made 1 frame:
`{"feeds": 2, "chars": 323, "max_body": 119, "oversize": false, "frames": 1, "token_chars": 62}`.

**1c, two proposals in one turn (one per model round).** Round 1: block + `edit_solus_entry`
(tie spacing); round 2: block + `delete_solus_entry` (old wiring); round 3: closing prose.

```
event: context_used
event: reasoning
data: {"considered":["keep the tie-spacing note as it is","say where each spacing applies"],"proposing":"Say which tie spacing applies to the arm and which to the base.","ruled_out":[{"what":"moving it to constraints","why":"it is guidance, not a limit"}]}
event: tool_call
data: {"args":{"entry_id":"01a18cb9-be02-7a3d-886f-df009ed7f18b","text":"Tie spacing: every 5 cm on the arm and every 10 cm on the base."},"call_id":"p7_1c_a","tool":"edit_solus_entry"}
event: tool_result
event: tool_confirmation
data: {…,"confirmation_id":"01a18cb9-c3a1-7b51-ad90-0b14310d8678",…,"tool":"edit_solus_entry"}
event: reasoning
data: {"considered":["keep the old wiring note","remove it"],"proposing":"Remove the outdated wiring note.","ruled_out":[{"what":"editing it","why":"the harness it describes was replaced"}]}
event: tool_call
data: {"args":{"entry_id":"01a18cb9-bdf5-7871-a679-245c7509c880"},"call_id":"p7_1c_b","tool":"delete_solus_entry"}
event: tool_result
event: tool_confirmation
data: {…,"confirmation_id":"01a18cb9-c3ad-79c9-ac4e-73bb56ad0c33","preview":[{"after":null,"before":"Old wiring: the bench harness uses the grey 6-pin connector on the brain board.","label":"Entry"}],…,"tool":"delete_solus_entry"}
event: token
data: {"text":"Two changes wait on their cards."}
event: message
event: done
```

Each card with the newest frame since the previous card (the `hangOnCard` rule the P7 report
states for the desktop, applied by the harness to the live stream):
`[{01a18cb9-c3a1-…, edit_solus_entry, "Say which tie spacing applies to the arm and which to the
base."}, {01a18cb9-c3ad-…, delete_solus_entry, "Remove the outdated wiring note."}]`. On the
desktop the per-card mount and the decided card taking its block are the vitest pins
`SolChat.reasoning.test.tsx` (1/1) and `ReasoningBlock.test.tsx` "draws its own card’s block alone,
and none for reasoning still waiting for its card" (desktop section).

**1d, two proposals in ONE model round (observation 1).** Round 1's text held two blocks, then
`edit_solus_entry` (spare harness) and `delete_solus_entry` (label sheets):

```
event: reasoning
data: {"considered":["reword the spare-harness note"],"proposing":"Name the drawer it lives in.","ruled_out":[]}
event: tool_call            (edit_solus_entry, p7_1d_a)
event: tool_result
event: tool_confirmation    (01a18cb9-c45e-7afd-b491-66448ac60b17)
event: tool_call            (delete_solus_entry, p7_1d_b)
event: tool_result
event: tool_confirmation    (01a18cb9-c465-7018-8ef7-1b59963bfa0d)
```

Log: `solus.agent.reasoning_frame reasoning block dropped: a second block`. Pairs:
`[{01a18cb9-c45e-…, edit_solus_entry, "Name the drawer it lives in."}, {01a18cb9-c465-…,
delete_solus_entry, null}]`. The second block reached neither the stream nor the stored turn.
This turn's question name-matched the `.solus` note "Spare harness: …"
(`01a18cb9-be13-78b2-818d-d615cee4581f`, `name_match`), so its prefix carried one format line for
that anchor.

**1e, M4: a block-only closing reply while a card waits.** Round 1: block + `edit_solus_entry`
(power-up order); round 2: a block and nothing else.

```
event: reasoning      (round 1: "Put the power-up steps in numbered order.")
event: tool_call
event: tool_result
event: tool_confirmation    (01a18cb9-c502-7b51-be7b-c3e90ac03b47)
event: reasoning      (round 2: {"considered":["anything more to add"],"proposing":"Nothing beyond the card.","ruled_out":[]})
event: message
data: {"citations":[],"content":"See the proposal below.","role":"assistant"}
event: done
```

Stored assistant turn: `"See the proposal below."`. Round 2's frame precedes no card: on the
desktop it waits (the deferred M176 misattribution ceiling).

## Leg 2: dropped blocks (B in P2, `action_mode: do`; 2e in Guide)

Each round 1 below was followed by an `edit_solus_entry` proposal (2e: none), each round 2 by
`"The edit waits on its card."`.

| Turn | Round 1 text as scripted                                                                                                  | Drop (`why`)   | `reasoning` frames | Card                                           |
| ---- | ------------------------------------------------------------------------------------------------------------------------- | -------------- | ------------------ | ---------------------------------------------- |
| 2a   | `Reviewing the note.\n<reasoning>{not json</reasoning>\nProposing an edit.`                                               | `malformed`    | 0                  | `01a18cb9-c596-7e8d-a98c-3841ce96b431` pending |
| 2b   | `Reviewing the note.\n<reasoning>{"considered": [` + `"one more thought", ` ×2,000 (never closed)                         | `never closed` | 0                  | `01a18cb9-c630-7348-bab1-259c47db1de4` pending |
| 2c   | `Reviewing the note.\n<reasoning>` + "```json\n" + `{"considered": ["tighten the wording"], "ruled_out": [{"what": "half` | `never closed` | 0                  | `01a18cb9-c69e-7b0c-8601-02724d9ab574` pending |
| 2d   | `Reviewing the note.\n<reasoning>[{"what": "a thinner wall", "why": "under the print min`                                 | `never closed` | 0                  | `01a18cb9-c71d-773b-be73-79deaf9308f2` pending |
| 2f   | `Reviewing the note.\n<reasoning>\n["raise the lid", "move the port"]`                                                    | `never closed` | 0                  | `01a18cb9-c7b0-7af2-8776-b06ed0fa3405` pending |
| 2e   | `Wrap your notes in a <reasoning> tag when you explain a change, then carry on with the conclusion in plain sentences.`   | none (prose)   | 0                  | –                                              |

Every shown frame of leg 2 (`p7_grep_leg2.txt`):

```
## p7_sse_2a-malformed.txt
data: {"text":"Reviewing the note.\n"}
data: {"text":"\nProposing an edit."}
data: {"text":"The edit waits on its card."}
data: {"citations":[],"content":"The edit waits on its card.","role":"assistant"}
## p7_sse_2b-unterminated.txt
data: {"text":"Reviewing the note.\n"}
data: {"text":"The edit waits on its card."}
data: {"citations":[],"content":"The edit waits on its card.","role":"assistant"}
## p7_sse_2c-unterminated-fenced.txt
data: {"text":"Reviewing the note.\n"}
data: {"text":"The edit waits on its card."}
data: {"citations":[],"content":"The edit waits on its card.","role":"assistant"}
## p7_sse_2d-unterminated-array.txt
data: {"text":"Reviewing the note.\n"}
data: {"text":"The edit waits on its card."}
data: {"citations":[],"content":"The edit waits on its card.","role":"assistant"}
## p7_sse_2e-prose-quoting-the-tag.txt
data: {"text":"Wrap your notes in a "}
data: {"text":"<reasoning> tag when you explain a change, then carry on with the conclusion in plain sentences."}
data: {"citations":[],"content":"Wrap your notes in a <reasoning> tag when you explain a change, then carry on with the conclusion in plain sentences.","role":"assistant"}
## p7_sse_2f-unterminated-brace-free-array.txt
data: {"text":"Reviewing the note.\n"}
data: {"text":"The edit waits on its card."}
data: {"citations":[],"content":"The edit waits on its card.","role":"assistant"}
```

The greps over those files:

````
$ /usr/bin/grep -n "not json" p7_sse_2a-malformed.txt
(exit 1)
$ /usr/bin/grep -c "one more thought" p7_sse_2b-unterminated.txt
0
(exit 1)
$ /usr/bin/grep -n "```\|json\\n\|tighten the wording\|\\"what\\"\|thinner wall\|print min\|raise the lid\|move the port\|\\"half" p7_sse_2[a-f]-*.txt
(exit 1)
````

**2b, the buffer cap.** `REASONING_BLOCK_CAP` = **4,096**; past it the parser keeps only the 11
characters a closing tag could start with (`len("</reasoning>")` = 12). The streaming parser of
2b's round 1, probed after every chunk:

```
{"label": "2b-unterminated", "feeds": 2001, "chars": 40047, "max_chunk": 47, "max_body": 4096, "max_held": 0, "oversize": true, "frames": 0, "token_chars": 20, "flush": {"open_body_chars": 3111, "oversize": true, "streamed_back_chars": 0}}
```

The body grew 20 characters a chunk from 16 to 4,096, was cut to 11 at the next chunk, and so on:
it never held more than 4,096 characters, under the 4,107 bound (4,096 + 11). At the end 3,111
were held and nothing was given back. The turn: `context_used, token, tool_call, tool_result,
tool_confirmation, token, message, done`, no `error` frame. Its round 2 was sent the round's full
text as the assistant turn (10,604 tokens in, by the harness's estimate).

**2e, prose quoting the tag.** Both parsers (the round's stream and the closing message's strip)
held the 85-character body to the end, found no `{` and no leading `[`, and gave it back as
written (`streamed_back_chars: 96`, the tag included). The stored assistant turn is the same
sentence. No drop line.

## Leg 3: pills (C in P3, Guide; `mentions: [servo 3]`)

The question, with another project's UUID and a nonexistent one pasted in:

> Why does servo 3 keep stalling, and does that break the current limit we wrote down? I also found 968af080-b7d8-4564-870e-38238c581a14 and f7d2f47c-3507-45f1-83c6-3c099d81c96e in an old bench log; are they related?

The scripted reply cited the finding, the constraint, servo 3, both pasted UUIDs and an unknown
one. The stream (`p7_grep_leg3.txt`):

```
$ /usr/bin/grep -A1 "^event: message" p7_sse_3a-pills.txt
event: message
data: {"citations":["[finding:01a18cb9-c0e9-7452-a52a-1eff9a1998cb]","[solus:constraints:01a18cb9-c0fe-711a-8cf5-53b918153738]","[entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]"],"content":"Servo 3 stalls against its command [finding:01a18cb9-c0e9-7452-a52a-1eff9a1998cb] while it draws past the limit you set [solus:constraints:01a18cb9-c0fe-711a-8cf5-53b918153738]. The part is [entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]. I cannot place [entity:968af080-b7d8-4564-870e-38238c581a14], [entity:f7d2f47c-3507-45f1-83c6-3c099d81c96e] or [entity:bcd7ce0e-dea3-449c-9698-c988df6700d4] in this project.","role":"assistant"}

$ /usr/bin/grep -o "\"anchors\":\[[^]]*\]" p7_sse_3a-pills.txt
"anchors":[{"id":"d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b","reason":"mentioned"},{"id":"968af080-b7d8-4564-870e-38238c581a14","reason":"ref_match"},{"id":"f7d2f47c-3507-45f1-83c6-3c099d81c96e","reason":"ref_match"}]

$ /usr/bin/grep -o "\[entity:[0-9a-f-]*\]" p7_sse_3a-pills.txt | sort | uniq -c   (token text, message content, message citations)
      2 [entity:968af080-b7d8-4564-870e-38238c581a14]
      2 [entity:bcd7ce0e-dea3-449c-9698-c988df6700d4]
      3 [entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]
      2 [entity:f7d2f47c-3507-45f1-83c6-3c099d81c96e]

$ python3 -c "<the message frame's data line, json.loads, its citations>"
[finding:01a18cb9-c0e9-7452-a52a-1eff9a1998cb]
[solus:constraints:01a18cb9-c0fe-711a-8cf5-53b918153738]
[entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b]
```

- `verified_citations` kept the three served tokens; the foreign, nonexistent and unknown entity
  tokens appear twice each (the streamed text and `content`), never in `citations`, so no pill
  and no "verified" token for them.
- `citations.reply_parts` (probed): anchors `[[d34a1e11-…, mentioned], [968af080-…, ref_match],
[f7d2f47c-…, ref_match]]`, **scoped anchors `[d34a1e11-…]`**. The served citations are the
  finding, the constraint and 24 envelope lines, all six of P3's own parts; no id of PG appears in
  the context. `context_used` lists the served sections `[solus, [solus:constraints:01a18cb9-c0fe-…]]`,
  `[finding, [finding:01a18cb9-c0e9-…]]` and the envelopes.
- **The format line**, from the round's recorded prefix (3a and 3b alike):

  ```
  Cite an entity this turn is anchored on by its token, exactly as given: [entity:d34a1e11-4ff5-4c59-8f7a-c65dd04cdc4b].
  ```

  Exactly the one pulled anchor, not the two pasted ones. Every turn whose pull returned no anchor
  (1a–1c, 1e, leg 2, leg 4, leg 5) carried no such line; 1d carried one for its name-matched note.

- **3b**, the same conversation, a follow-up mentioning servo 3 and no pasted ids → citations
  `["[solus:constraints:01a18cb9-c0fe-711a-8cf5-53b918153738]"]`, the same format line. Its prefix
  differs from 3a's (sha `1e56ce9f…` vs `5a7b594f…`): the scope planner pulled the whole arm for
  3a's wording (graph layer 1,015 tokens, 25 finding-layer sections) and servo 3's neighbourhood
  for 3b's (401 tokens, 5 sections). This pair therefore says nothing about byte stability; the P0
  pin is the proof (observation 4).
- Desktop: pills open their surfaces, by vitest (desktop section).

## Leg 4: the Guide answer with the tool version (D, and teammate E, in P4)

**The machine, through the route.** D's companion K1 bound (admitted `machine.tool_versions` and
the five `kicad.*` tools), then `PUT /api/v1/projects/{P4}/members/me/machines/cfd79634…` → 200.
The route asked the companion for `machine.tool_versions` (frame recorded, answered by the
companion's `_tool_versions` through the scripted seams: `--version` of `python3`, `git`,
`kicad-cli`) and stored:

```json
{
  "hostname": "p7-bench",
  "os": "linux",
  "arch": "arm64",
  "owner_user_id": "01a18cb9-bc43-70cc-99df-473024422140",
  "tool_versions": {
    "python3": "Python 3.12.3",
    "git": "git version 2.43.0",
    "kicad-cli": "9.0.2"
  },
  "devices": [],
  "flash_history": [],
  "recent_commands": []
}
```

K0, the same PUT with no `kicad-cli` on the machine: `tool_versions {"python3": "Python 3.12.3",
"git": "git version 2.43.0"}`. The question, every time (Guide, `sol_mode` guide):

> Where do I find the tool that places a net label in KiCad? I want to label the I2C lines on my sheet before I route them.

The scripted reply quotes the note the round's own `kicad_add_net_label` spec carried. Messages
as streamed (`p7_grep_leg4_5.txt`):

```
4a-release-reported:            {"citations":[],"content":"For placing a net label in your KiCad: No vendor documentation covers KiCad 9.0.2: not sure where that is in KiCad 9.0.2.","role":"assistant"}
4b-no-release:                  {"citations":[],"content":"For placing a net label in your KiCad: Place Net Labels: Place Net Labels Default shortcut: L.","role":"assistant"}
4c-no-release-no-note:          {"citations":[],"content":"For placing a net label in your KiCad: No vendor documentation covers KiCad: not sure where that is in KiCad.","role":"assistant"}
4d-release-read-fails:          {"citations":[],"content":"For placing a net label in your KiCad: Vendor notes unavailable for KiCad 9.0.2: not sure where that is in KiCad 9.0.2.","role":"assistant"}
4e-teammate-claims-the-machine: {"citations":[],"content":"For placing a net label in your KiCad: Place Net Labels: Place Net Labels Default shortcut: L.","role":"assistant"}
```

**Where each sentence came from** (`project_card.machine_block` and `runtime.placed_tools`, probed;
the note as the model was sent it, decoded from the tool spec's `tool_knowledge` fence):

| Turn | Asker / live companion                  | Machine block (owner-gated)                                                        | `kicad.add_net_label` note sent                                                                                                            | Release reads                                            |
| ---- | --------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| 4a   | D / K1                                  | `[["git","git version 2.43.0"],["kicad-cli","9.0.2"],["python3","Python 3.12.3"]]` | `[kicad.eeschema.interactive_drawing.place_label] No vendor documentation covers KiCad 9.0.2: not sure where that is in KiCad 9.0.2.`      | 5, all `kicad`, `version 9.0.2`                          |
| 4b   | D / K0                                  | `[["git",…],["python3",…]]` (no `kicad-cli`)                                       | `[kicad.eeschema.interactive_drawing.place_label] Place Net Labels: Place Net Labels Default shortcut: L.` (the route's version-less note) | 0                                                        |
| 4c   | D / K0, KiCad reads scripted empty      | `[["git",…],["python3",…]]`                                                        | `[kicad.eeschema.interactive_drawing.place_label] No vendor documentation covers KiCad: not sure where that is in KiCad.`                  | 0                                                        |
| 4d   | D / K1, release reads scripted to raise | `[["git",…],["kicad-cli","9.0.2"],["python3",…]]`                                  | `[kicad.eeschema.interactive_drawing.place_label] Vendor notes unavailable for KiCad 9.0.2: not sure where that is in KiCad 9.0.2.`        | 5, all `kicad`, each `raised ConnectionError` (scripted) |
| 4e   | E / E's session claiming K1             | **`null`** (`owns_machine` false)                                                  | the version-less note                                                                                                                      | 0                                                        |

**4a, the release reads** (control, version, the published entries found):

```
["kicad.eeschema.edit_symbol_properties", "9.0.2", [[">=8.0 <10.0", 0.8]]]
["kicad.eeschema.interactive_drawing.place_symbol", "9.0.2", []]
["kicad.eeschema.interactive_drawing_line_wire_bus.draw_wires", "9.0.2", []]
["kicad.eeschema.interactive_drawing.place_label", "9.0.2", []]
["kicad.eeschema.interactive_drawing.place_no_connect", "9.0.2", []]
```

So after `placed_tools`, `kicad.set_symbol_property` kept "[kicad.eeschema.edit_symbol_properties]
Symbol Properties: Edits one placed symbol's fields — Reference, Value, Footprint and custom
properties — in the schematic editor; the change is saved with the schematic." and the other four
carried the 9.0.2 sentence. **Knowledge queries per Guide turn** (`knowledge.query_entries`,
probed): 4a `{None: 14, "9.0.2": 5}` (release reads by family: `{kicad: 5}`), 4b `{None: 14}`, 4c
`{None: 14}` (5 of them, the KiCad ones, scripted empty), 4d `{None: 14, "9.0.2": 5}` (the 5
scripted to raise), 4e `{None: 14}`. 4d logged `solus.agent.knowledge tool knowledge lookup failed
for kicad.<tool>` once per KiCad tool (the 5 warnings of the run beyond startup).

## Leg 5: untouched invariants (F in P5, `action_mode: do`)

F's companion advertised `machine.write_file`, answered by `MachineServer(<scratch>)` over a
workspace holding `notes/README.txt` (sha256 `43589761…f367`).

**5a, an owned routine auto-runs.** `"Write our bench checklist into notes/p7-build.txt for the
next run."`; round 1 a block, then `machine_write_file {path: notes/p7-build.txt, content: "bench
checklist: bus powered, brain board up, servo limits loaded\n"}`.

```
$ /usr/bin/grep '^event:' p7_sse_5a-owned-routine.txt
event: context_used
event: reasoning
event: tool_call
event: tool_result
event: token
event: message
event: done
$ /usr/bin/grep -A1 '^event: tool_result\|^event: tool_confirmation' p7_sse_5a-owned-routine.txt | /usr/bin/grep '^data:'
data: {"call_id":"p7_5a","error":null,"ok":true,"value":{"bytes_written":66,"changed":true,"path":"notes/p7-build.txt","verified":true}}
```

- `BuildExecutionPolicy.prepare` (probed): `{"tool": "machine.write_file", "mode": "do",
"force_confirmation": false, "decision": true}`; log `build action authorized
tool=machine.write_file call_id=p7_5a authorization_origin=build_policy`.
- Companion frames: `write_file` `dry_run: true` ×3 (the two policy previews and the tool's own
  check), then one without `dry_run` (the write); all answered ok.
- Workspace after: `notes/p7-build.txt` sha256 `97aa18eec73486d4015ef25e18c0f4bd18cf2ed1f213dc5fd0c18f1953196e67`
  = sha256 of the scripted content. No `tool_confirmations` row.

**5b, a forced card still appears.** The same tool, `force_confirmation: true`, path
`notes/p7-review.txt`.

```
$ /usr/bin/grep '^event:' p7_sse_5b-forced-card.txt
event: context_used
event: reasoning
event: tool_call
event: tool_result
event: tool_confirmation
event: token
event: message
event: done
```

- `prepare`: `{"tool": "machine.write_file", "mode": "do", "force_confirmation": true,
"decision": false}`; log `parked machine.write_file for confirmation`, `tool call gated …
parked=True`.
- The card `01a18cb9-cdf6-718d-9210-5da95fa944db`, `pending`, rows: `File` → `notes/p7-review.txt`,
  `File state fingerprint` → `2e9d7986…:b6105976…:87845ec0…:0055fe94…`, `Content 1` → the review
  text.
- Companion frames: one `dry_run: true` (the card's preview), 0 writes. Workspace after:
  `notes/README.txt` and `notes/p7-build.txt` only, shas unchanged.

The dispatch says "reuse the P4 acceptance's checks": P4's and P5's acceptance reports hold no
`force_confirmation` or owned-routine check (grep, none), so the pair was proved in the shape of
P6's leg 5 (the policy decision, the companion frames, the workspace shas), with the pins
`test_force_confirmation.py`, `test_build_execution_policy.py`, `test_machine_writes.py`,
`test_command_auto_run.py` and `test_command_auto_run_route.py` in the proxy slice.

## Desktop (vitest by hand; no Electron)

```
cd apps/desktop && npx vitest run --reporter=verbose src/renderer/src/features/sol/SolChat.test.tsx src/renderer/src/features/sol/ReasoningBlock.test.tsx src/renderer/src/features/sol/SolScreen.test.tsx src/renderer/src/features/sol/SolChat.reasoning.test.tsx src/renderer/src/features/bench/BenchScreen.test.tsx src/renderer/src/features/workspace/shellStore.test.ts src/renderer/src/features/sol/solStream.test.ts src/renderer/src/features/sol/solChatItems.test.ts src/renderer/src/features/sol/solChatStore.reasoning.test.ts src/renderer/src/features/sol/domainIds.test.ts src/renderer/src/features/sol/domainDot.test.tsx
 Test Files  11 passed (11)
      Tests  142 passed (142)
```

Per file (✓ lines): BenchScreen 16, ReasoningBlock 5, SolChat.reasoning 1, SolChat 36, SolScreen
14, domainDot 1, domainIds 3, solChatItems 16, solChatStore.reasoning 5, solStream 36, shellStore 9. 0 failed, 0 skipped. The named ones, as printed:

```
 ✓ src/renderer/src/features/sol/SolScreen.test.tsx > SolScreen — citation pills (SOLUSDEV-321 P7) > finding and solus pills open their surfaces 48ms
 ✓ src/renderer/src/features/bench/BenchScreen.test.tsx > opens the Findings pane on the finding a SOL citation pill requested, then clears it 28ms
 ✓ src/renderer/src/features/workspace/shellStore.test.ts > benchFinding (SOLUSDEV-321 P7: a finding pill opens the Bench on that finding) > holds the requested finding until the Bench takes it 0ms
 ✓ src/renderer/src/features/workspace/shellStore.test.ts > benchFinding (SOLUSDEV-321 P7: a finding pill opens the Bench on that finding) > is cleared by reset 0ms
 ✓ src/renderer/src/features/sol/SolChat.reasoning.test.tsx > SolChat — a proposal’s reasoning sits on its own card (SOLUSDEV-321 P7) > puts each card’s reasoning directly above that card, and takes it away with the card 134ms
 ✓ src/renderer/src/features/sol/ReasoningBlock.test.tsx > ReasoningBlock > shows what SOL considered, ruled out and why, and proposes — shut in Expert 29ms
 ✓ src/renderer/src/features/sol/ReasoningBlock.test.tsx > ReasoningBlock > opens in Guide, where the reasoning is part of the teaching 4ms
 ✓ src/renderer/src/features/sol/ReasoningBlock.test.tsx > ReasoningBlock > renders model text as text, never as markup or a link 9ms
 ✓ src/renderer/src/features/sol/ReasoningBlock.test.tsx > ReasoningBlock > draws its own card’s block alone, and none for reasoning still waiting for its card 11ms
 ✓ src/renderer/src/features/sol/ReasoningBlock.test.tsx > ReasoningBlock > leaves out a list with nothing in it 2ms
 ✓ src/renderer/src/features/sol/solStream.test.ts > reasoning frame (SOLUSDEV-321 P7) > keeps reasoning frame 0ms
 ✓ src/renderer/src/features/sol/solStream.test.ts > reasoning frame (SOLUSDEV-321 P7) > keeps a frame at its bounds, counting characters rather than UTF-16 units 0ms
 ✓ src/renderer/src/features/sol/solStream.test.ts > reasoning frame (SOLUSDEV-321 P7) > drops a frame it cannot prove, whole 1ms
 ✓ src/renderer/src/features/sol/solChatItems.test.ts > applyReasoningFrame — a proposal’s reasoning > hangs a round’s reasoning on the proposal card that follows it, and on no later card 1ms
 ✓ src/renderer/src/features/sol/solChatStore.reasoning.test.ts > a proposal’s reasoning on its turn (SOLUSDEV-321 P7) > a reloaded turn carries no reasoning: the frame is shown live and never stored 0ms
```

The stderr lines in `p7_vitest.log` are jsdom's missing canvas and WebGL in BenchScreen's scene
(present on every run of that file). `git status` was empty afterwards.

## Proxy tests (after the live run)

The pytest guard (`ps -eo pid,args | grep -E "[u]v run pytest|[p]ython -m pytest|[p]ytest -q"`)
ran in its own call before the run and printed nothing. One process, no `--cov`:

```
cd packages/api && PYTHONDONTWRITEBYTECODE=1 SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_d7fa72c2 timeout 1800 uv run --frozen --no-sync pytest -q -rs -p no:cacheprovider tests/test_reasoning_frame.py tests/test_citations.py tests/test_context_layers.py tests/test_guide_toolkb_version.py tests/test_knowledge.py tests/test_stream.py tests/test_prompt.py tests/test_prefix_stability.py tests/test_runtime.py tests/test_sol_runtime.py tests/test_force_confirmation.py tests/test_command_auto_run.py tests/test_command_auto_run_route.py tests/test_build_execution_policy.py tests/test_execution_policy.py tests/test_machine_writes.py tests/test_firmware_recipe.py tests/test_confirmations.py tests/test_sol_red_team.py tests/test_capability_hygiene.py tests/test_model_call_sites.py tests/test_vendor_hygiene_api.py tests/test_no_hardcoded_models.py tests/test_toolkb_code_isaac.py tests/test_context.py tests/test_project_card.py tests/test_sol_turn_limits.py
650 passed in 199.86s (0:03:19)
```

- **P7's own pins:** `test_reasoning_frame.py` (shape, splits, unterminated, prose quoting the tag
  with the fix-2 cases, the REAL-runner frame-before-call and block-only-close tests),
  `test_citations.py` (I1: a pasted id the pull never returned is never served; M4),
  `test_context_layers.py` (the R142a format line), `test_guide_toolkb_version.py` (release digits,
  owner gate, the family-only read and the unavailable wording), `test_knowledge.py`,
  `test_stream.py`, `test_prompt.py` (the one sentence).
- **The P0 prefix pin** `test_prefix_stability.py`, unchanged by P7, and the P5 drift check
  `test_sol_turn_limits.py`.
- **Leg 5's invariants:** `test_force_confirmation.py`, `test_build_execution_policy.py`,
  `test_execution_policy.py`, `test_machine_writes.py`, `test_command_auto_run.py`,
  `test_command_auto_run_route.py`, `test_firmware_recipe.py` (a routed write keeps its card),
  `test_confirmations.py`.
- **Ratchets and the runner:** `test_capability_hygiene.py`, `test_model_call_sites.py`,
  `test_vendor_hygiene_api.py`, `test_no_hardcoded_models.py`, `test_sol_runtime.py` (the
  `.invoke(` site ratchet), `test_runtime.py`, `test_sol_red_team.py`, `test_context.py`,
  `test_project_card.py`, `test_toolkb_code_isaac.py`.
- 0 failed, 0 skipped (`-rs` printed none). Log `acceptance/p7_proxy_pytest.log`, times and the
  `.coverage` md5 before and after in `p7_proxy_pytest.time`. The tree stayed clean.

## Deviations from the brief and observations

1. **Two proposals in ONE model round give one frame (1d).** API.md §2.9 and the parser drop "a
   second block in the same round's text", so a model that proposes two changes in one round with
   a block before each shows the first block on the first card and none on the second. The
   dispatch's "two proposals in one round → two frames, each bound to its card id" holds only when
   each proposal is its own model round (1c), which is how the desktop pin
   `SolChat.reasoning.test.tsx` feeds it. Not a failure of the landed contract; a gap against
   "once per card" for parallel proposals, for a ruling (fix shape: one frame per block, each
   ahead of the call it precedes, or the deferred M176 round/call binding).
2. **The KiCad tools were hand-written advertisements.** The fork's own server needs `fastmcp`
   (its private venv; `ModuleNotFoundError: No module named 'fastmcp'` in the repo environment),
   so its `list_tools()` could not be read. The five mapped write tools were advertised with a
   small object schema each and admitted by the real allowlist; they were only offered, never
   called, so their schemas played no part.
3. **The machine's versions came through the companion's own code with scripted seams.**
   `MachineServer._tool_versions` ran (its line extraction and redaction) over a scripted `which`
   (a fake absolute path) and `capture` (the version line); no binary ran. The cloud path, `PUT
…/members/me/machines/{id}` → `machine.tool_versions` over the bridge → `upsert_machine`, was
   the production one.
4. **3b is not a prefix-stability test.** Its prefix differs from 3a's because its wording pulled a
   smaller scope; the format line is the same in both. The P0 pin `test_prefix_stability.py`
   (unchanged by P7) is the proof, with the R142a pin in `test_context_layers.py`.
5. **"Without a version → the generic wording" needs a tool with no note.** The dev copy's toolkb
   has published vendor notes for all five mapped KiCad controls, so with no release reported (4b)
   each tool keeps its note, as API.md §2.9 says ("With no release reported, a tool the knowledge
   base has nothing for gets the sentence naming the tool alone"). The generic wording was shown
   with the KiCad reads scripted empty (4c).
6. **The failing release read (4d) was scripted**: `knowledge.query_entries` raised
   `ConnectionError` for the turn's versioned reads, as `test_guide_toolkb_version.py` does; the
   version-less reads ran for real.
7. **14 version-less queries, not 15.** `TOOL_CONTROLS` has 14 rows; the review's "all 15" counted
   one too many. The release read is 5, the KiCad family alone.
8. **The harness's case-folded needle `proposing` matched the fixture's own prose** ("Proposing a
   clearer version.", "Proposing an edit.") in 1a, 1b and 2a. Those are the model's words outside
   the block, which the person should see. The case-sensitive key grep and the escaped-key grep
   (above) show no block key in any shown frame.
9. **A round-2 block with no card still streams (1e).** It waits on the desktop item with no card
   to hang on: the deferred M176/M2 misattribution ceiling. M182 (restored-card fallback) was not
   tested, as the dispatch says.
10. **No data event was stored**: every minted person is `consented=False`, and P7 adds none
    (M178 is deferred, tier-2).
11. **Leg 2's edit cards replace whichever P2 note they target** with a "Cable routing: …
    (review N)" text (2b's card targets the old-wiring note). They are parked and never approved;
    the proof is the card's presence, not its wording.

## Not verified here

- **The desktop live (Electron):** the block above its card, a pill opening the Findings pane or
  a `.solus` entry, a decided card taking its block. Proven by the vitest pins above only.
- **A real model writing a `<reasoning>` block** (or following `REASONING_NOTE`): every block here
  was the fixture.
- **A card's approval** (the cards stay `pending`) and the decided card's server side.
- **The KiCad fork's real inventory** and a real `kicad-cli --version` (deviations 2 and 3).

## Left behind

- **In `solus_sol`.** Counts before → after the run:

  |                    | before | after                                                               |
  | ------------------ | ------ | ------------------------------------------------------------------- |
  | users              | 38     | 45                                                                  |
  | projects           | 42     | 48                                                                  |
  | memberships        | 77     | 91                                                                  |
  | `credit_ledger`    | 49     | 89 (7 `trial_grant`, 33 `usage` from this run)                      |
  | of which `usage`   | 15     | 48                                                                  |
  | findings           | 273    | 274 (P3's stall)                                                    |
  | machines           | 1      | 3 (D's K1 and K0)                                                   |
  | entities           | 1,781  | 1,958                                                               |
  | edges              | 2,117  | 2,336                                                               |
  | `.solus` entries   | 166    | 199 (12 notes, 1 constraint, 14 arm configs, 6 environment entries) |
  | conversations      | 7      | 26                                                                  |
  | conversation turns | 29     | 83                                                                  |
  | tool confirmations | 20     | 33 (13 `pending`: A 7, B 5, F 1)                                    |
  | tool knowledge     | 126    | 126                                                                 |
  | data events        | 0      | 0                                                                   |

  The run's projects are in the Seed table. The artifact root and P5's workspace lived in the
  process's temporary directory, removed at exit.

- **Not touched:** `solus`, `solus_sol_p1`, and every `solus_test_*` except `solus_test_d7fa72c2`
  (the proxy run truncates it, as designed).
- **Redis 6390** after the run: six `solus:freqcap:<user>` keys (A–F) and five
  `solus:project_card:<project>` keys (P1–P5). `solus-redis-1` was never touched.
- **Processes.** None started, stopped or killed; no `pkill`, no `pgrep -f`.
- **Files** (the git-ignored plan workspace): `acceptance/p7_accept_live.py`,
  `p7_accept_live_result.json` with `.stdout`, `.stderr`, `.time`; the 20 `p7_sse_*.txt`; the five
  `p7_grep_*.txt`; `p7_vitest.{log,time}`; `p7_proxy_pytest.{log,time}`; `reports/`: this report.
  No tracked file changed.
