# Live verification — LANE C (SOLUSDEV-68), branch `SOLUSDEV-68-SOL-Reasoning`

**Date:** 2026-08-10 · **Verifier:** orchestrator session · **Base commit verified:** `ad04c08`

All six lane tickets shipped with green suites, but every acceptance claim rested on **doubles**: a scripted provider instead of Anthropic, `FakeSolSystems` instead of real feeds, structural fakes instead of a real `BrowserWindow`. This pass ran the branch against a real Postgres, a real Redis, a real Anthropic key, and a real Electron launch.

**Headline: three defects that every test missed, two of them show-stoppers.** All three are fixed and re-verified live.

## Isolation (nothing shared was touched)

Port 8000 and the `solus_cadmcp` dev DB belong to a _different_ checkout (`/home/beeboss/cad-mcp`) whose API was live throughout. This verification used a throwaway DB `solus_lanec_verify` (migrated to this branch's head `a7c41b9d2e05`) and port **8011**. The other checkout's server, DB, alembic revision, and `.env` end exactly as they started. Secrets were never printed; the Anthropic key was seeded into the verify DB's encrypted `SecretStore` (which is where the app actually reads it from — _not_ `ANTHROPIC_API_KEY`).

---

## Defects found live

### D1 — CRITICAL: every SOL turn failed. Dotted tool names are rejected by the provider.

Anthropic requires tool names to match `^[a-zA-Z0-9_-]{1,128}$`. Solus names tools with **dots** by contract: `solus.connect_integration` (SOLX-04) and `{server}.{tool}` for every bridge/MCP tool. The first live turn returned:

```
anthropic.BadRequestError: 400 tools.1.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'
```

Because SOLX-04 registers its three tools on **every** SOL route, this broke **100% of turns** — the user saw only a generic `internal` error frame; the real cause was server-log-only. Bridge/MCP tools would have broken it identically the moment a companion connected.

**Fix** (`agent/prompt.py`, `agent/runtime.py`): translate at the model boundary — `provider_tool_names()` offers provider-safe names, `resolve_tool_name()` maps the model's answer back before dispatch. The registry, the gate, and the contracts keep their dotted identity. Unknown names pass through untouched so a hallucinated tool still yields `NOT_FOUND`. Collisions (`a.b` vs `a-b`) are broken deterministically.
**Regression tests:** `test_prompt.py::test_offered_tool_names_satisfy_the_provider_charset` (asserted over the **production** descriptors), `…_maps_back_to_the_real_tool`, `…_collide_after_translation_stay_distinct`. One pre-existing test had literally pinned the broken behaviour (`spec.name == "onshape.get_variables"`) — updated with a comment explaining why.

### D2 — CRITICAL: the desktop app could not start at all (since `0d2ff57`).

`electron-vite` externalizes dependencies, so the built main/preload bundles emitted `require("@solus/shared-types")` — but that package ships **raw TypeScript** (`main: "src/index.ts"`). Node cannot execute TS:

```
Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../packages/shared-types/src/focus'
```

Main and preload began importing that package in **SOL-IPC-01** (the CTR-06 contract), so the app has been unlaunchable since that commit. vitest and `tsc` both transpile TS, so 745 tests and a clean typecheck sailed past it.

**Fix** (`apps/desktop/electron.vite.config.ts`): `externalizeDepsPlugin({ exclude: ['@solus/shared-types'] })` on main and preload — the contract is bundled. Verified: `require("@solus/shared-types")` no longer appears in either bundle, and the app launches and renders (screenshot captured).

### D3 — HIGH: turn-admission rate limiting was inert while `/readyz` claimed Redis was configured.

`check_frequency_cap` was always passed `redis=None` because **nothing in the codebase ever assigned `app.state.redis`** — 17 `frequency cap SKIPPED — no redis configured, fail-open by policy` warnings in one session, while `/readyz` reported `redis: configured`. My own 429 path (SOL-02 SEC-H3, SOLX-04) was dead code. This is the pre-GA flag from the handoff report, now root-caused: not "Redis isn't deployed" — Redis _is_ up; it was never wired.

**Fix** (`main.py`): assign `app.state.redis` from `redis.asyncio.from_url(...)` when `redis_url` is set. `from_url` is lazy (no connect at startup) and `redis.asyncio` satisfies the gate's `RedisLike` protocol; the gate already fails open uniformly on Redis errors, so this adds enforcement **without** adding a failure mode.
**Live proof:** 24 rapid decide calls → `200 ×20` then `429 ×4`, zero fail-open warnings, sliding-window key `solus:freqcap:<user>` present in Redis.
**Regression test:** `test_solx01_hardening.py::test_the_app_wires_a_redis_client_for_the_frequency_cap`.

---

## Per-ticket verdicts

| Ticket               | Verdict                        | Live evidence                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **SOL-02 (130)**     | **PASS** (after D1)            | A real Opus turn streamed 29 `token` frames, made a real tool call, and returned an explanation **plus a concrete suggested fix** ("add a 470 µF bulk capacitor on the 3V3 rail") with **3 verified citations**. The model followed `_CITE_NOTE` verbatim and, when a tool returned `NOT_FOUND`, said so instead of inventing — the behaviour the system prompt demands.                                                                                 |
| **SOL-01 (129)**     | **PASS, with the seam stated** | The pull chain ran end to end: plan → `build_context` → nonce-fenced blocks → model. Citations included `[telemetry:2026-07-05T12:01:00_00:00]`, proving the telemetry-citation charset fix round-trips live. **Feeds are still `FakeSolSystems` in production** (`main.py` wires the fake) — so SOL grounds answers in canned data until SYS-04 lands. That is the designed seam, not a defect, but it means real retrieval quality remains unverified. |
| **SOLX-01 (200)**    | **PASS**                       | Guide mode asked to connect KiCad → refused with the honest guide-mode message; DB showed **0 confirmations, 0 sources**. Do mode → parked. `agent.tool_invoked` events carry identifiers only (`{ok, tool, call_id, action_mode}`) — no argument values — closing the SYS-02 handoff obligation, and only after consent (ADR-011 opt-in verified both ways).                                                                                            |
| **SOLX-04 (203)**    | **PASS**                       | Full round-trip: `tool_confirmation` frame with Solus-authored consent + preview → approve → `sources` row `kicad\|connected`, and the previously-untested `config_fields` next-step appeared ("set export for kicad…"). Replay → `already approved`, still 1 source. Negatives all held live: other tenant **404**, unverified email **403**, arg-smuggling **422**, `amend` **422** — action still parked, nothing executed.                           |
| **SOL-IPC-01 (223)** | **PARTIAL**                    | The bundling fix (D2) is what makes the preload load at all. The wire's own behaviour remains proven by unit tests + the shared-types parser: `attachOrbOverlayWire`'s return value still has no production consumer, so no push crosses in the running app. Console-level checks need DevTools access.                                                                                                                                                  |
| **SOLX-02 (201)**    | **PARTIAL**                    | The app now **launches and renders** (previously an instant crash — D2). The orb itself lives inside the authenticated workspace, and the desktop authenticates via Supabase; no account credentials were available, so orb/panel/detach were not exercised in-app. They remain covered by 745 unit tests against structural fakes.                                                                                                                      |

## Repeatable gates (final, quiet tree)

Backend **1764 passed / 3 skipped** (was 1760 — the four new regression tests), mypy clean (132 files), ruff clean. Desktop **745 passed**, `typecheck:node` + `typecheck:web` clean. The 3 skips are the pre-existing `test_live_smoke.py` provider tests, which key off `SOLUS_LIVE_*` variables (not `ANTHROPIC_API_KEY`) and are unrelated to this lane.

**Hermeticity confirmed:** the suite behaves identically with the real `.env` present — `conftest` passes `_env_file=None` deliberately.

## What is still NOT verified (honest list)

1. **Real retrieval quality** — `FakeSolSystems` is production; `rag/retrieval.py` (real pgvector) is never called from the SOL path. Blocked on SYS-04.
2. **The orb in-app** — needs Supabase credentials. Ask a human to sign in and run `COWORK_QA_SOLX-02-orb.md`.
3. **The confirmation card in the desktop UI** — `solStream.ts` has no `tool_confirmation` case, so the frame is dropped by the renderer. The backend parks correctly and the frame _is_ on the wire (verified above), but a Do-mode user in the app would see only prose with no approve control. **Recommend a follow-up ticket**; `COWORK_QA_solx04` Flow 3.2 currently describes a card that does not exist.
4. **Multi-round tool loops** under real latency (the live turns used 1–2 rounds).

## Merged `origin/main` `a79aea8` (2026-08-10)

Main had moved three commits ahead — **SOLUSDEV-102** (project-folder open split, Stripe checkout window, BYO-license capture), **SOLUSDEV-114** (Sources crash fix), and **SOLUSDEV-136/CTR-08** (work already on this branch under a different SHA). Merged into the feature branch per ADR-021 (merge in, never rebase). Nothing in `packages/contracts/`, `packages/shared-types/`, or `DECISIONS.md` conflicted, so no tier-2 sign-off was needed.

**Four conflicts, resolved:**

| File                                                            | Resolution                                                                                                                                                                                                                                                            |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/runtime.py`, `agent/tools/exec.py`, `tests/test_exec.py` | **Ours** — provably lossless: `git diff origin/main:<f> 086f8d6:<f>` is empty for each, i.e. main's copy is byte-identical to this branch's pre-SOLX-01 version. Taking theirs would have undone the unbypassable-gate reshape and the D1 fix.                        |
| `apps/desktop/src/main/index.ts`                                | **Hand-merged** — one conflict region (the import block); resolved as the union, taking main's `isAllowedCheckoutEntryUrl` rename. All of main's SOLUSDEV-102 work and this branch's sol-window wiring are present; no stale `isAllowedBillingUrl` reference remains. |

**Alembic had two heads** after the merge — this branch's SOL confirmation chain (`a7c41b9d2e05`) and main's billing chain (`a91b3c7e2d48`), both branching from `e3a1c8f27b54`. Joined with a no-op merge revision `9add931f4716`. Verified by upgrading the throwaway DB through the whole merged chain: it reaches `9add931f4716`, main's `subscriptions.cancel_at` exists, and this branch's `tool_confirmations` survives.

**SEC-M1 closed while in the file** (the SOLX-02 finding deferred at handoff): `registerSolWindowHandlers` now takes a required `isAllowedSender` predicate and is wired to main's `isMainRendererSender`, so only the app's own renderer can raise or dismiss the always-on-top window; a foreign sender gets current state and no action. The predicate is required rather than defaulted so a forgotten argument cannot silently mean "anyone may". Two tests added, including one proving a foreign sender cannot close a window the real renderer opened.

**Re-verified after the merge:** desktop **823 passed** (this branch's 745 + main's new tests + 2 new) and `typecheck:node`/`typecheck:web` clean; backend **1817 passed / 3 skipped**, mypy clean (132 files), ruff clean. Live smoke re-ran the two things tests cannot see: a real Opus guide-mode turn streamed 43 token frames and dispatched the dotted tool `solus.verify_integration` successfully with 3 structured citations (**D1 holds**), with zero fail-open frequency-cap warnings (**D3 holds**); and the built bundles contain no `require("@solus/shared-types")` while the app launches and renders (**D2 holds**).

**Pre-existing, not mine:** `src/solus_api/contracts/tool_knowledge.py` fails `ruff format --check` on main and is untouched by this branch — flagged, not reformatted.

**Isolation held throughout:** `solus_cadmcp` is still at `a7c5d2e91f04` and the other checkout's API on port 8000 still answers 200.

## Recommended follow-ups (not done here)

- A CI **smoke launch** of the packaged app: D2 proves unit tests + typecheck cannot catch a broken runtime bundle.
- Render `tool_confirmation` in `OrbChat` (item 3 above).
- Consider whether other workspace packages consumed by main/preload need the same bundling treatment as `@solus/shared-types`.
