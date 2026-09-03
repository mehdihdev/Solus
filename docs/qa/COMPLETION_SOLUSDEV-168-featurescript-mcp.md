# Completion report — SOLUSDEV-168, Onshape FeatureScript (hosted MCP)

**Branch:** `SOLUSDEV-168-featurescript-mcp` (renamed from `featurescript-mcp`)
**Spec:** `docs/qa/HANDOFF_featurescript-mcp.md`
**QA plan:** `docs/qa/COWORK_QA_featurescript-mcp.md`

---

## Governing docs consulted

| Doc | Bearing on this work |
| --- | --- |
| `DECISIONS.md` ADR-031 | MCP hosting model. Covers only forked, Solus-owned servers on the customer machine — **not** a vendor-hosted cloud server. Hence the ADR-035 proposal below. |
| `DECISIONS.md` ADR-019 (amended on main by SOLUSDEV-167) | Third-party integration quotas are a SECOND budget, per provider account, in Redis, failing open. This work's metering is built on it and needs **no** new ADR. |
| `DECISIONS.md` ADR-032 | Two-tier governance. Tier-1 docs amended directly; DECISIONS.md left untouched pending approval. |
| `docs/contracts/agent-tool.md` | W0-04 tool interface. Amended (it was stale in five places). |
| `docs/contracts/action-gate.md` | The destructive-action gate the FeatureScript diff plugs into. |
| `docs/wireflows/sources-connect-wizard.md` | Governs the connect screen. Amended. |
| `docs/api/API.md` | Route plan. Amended with four routes. |

---

## What was built

**Backend.** A hosted-server registry that is complete DATA (`remote_mcp.py`): pinned OAuth
endpoints, an exposure allowlist, per-tool consent sentences, the connector it rides on. A
hand-rolled OAuth client (`hosted_oauth.py`) doing DCR once, PKCE, exchange and refresh. An
auth-capable MCP transport, a per-source token resolver, a metered preflight, and the
FeatureScript diff. Four routes nested under the Source. The registry builds hosted tools
from a persisted inventory.

> **Correction (follow-up commit).** That last sentence was true of
> `build_sol_registry` and **false of every caller**: no route passed
> `hosted_inventory`, so the FeatureScript tools were built, tested and never
> handed to the model. This shipped because every test here stops at
> `build_hosted_tools` rather than going through the route. Fixed by moving
> registry construction to a single dependency (`deps.get_sol_registry`), with a
> ratchet and route-level tests. Recorded here rather than quietly amended,
> because a completion report that overstates what shipped is worse than none.

**Desktop.** Connect-time disclosure, an add-on block on the connected source (enable /
open store / re-check), a sender-gated App Store IPC channel, and the confirmation-card fix.

---

## Decisions made under delegated judgment

1. **The affordance's placement.** The approved option was labelled "Settings surface", by
   analogy with `/users/me/panel-links`. While planning I found that placement implies
   PER-USER tokens, which contradicts storing the grant on the Source (where every other
   connector credential lives, where tenancy is structural, and where the existing deletion
   sweeps can reach it). The endorsed substance — non-blocking, durable, reaches teammates,
   not a tile — is fully satisfied by putting it on the **connected source row**, which is
   also where a per-source grant belongs. Flagged here rather than silently swapped.
2. **PKCE storage.** A nullable `oauth_states.code_verifier` column rather than a SecretStore
   ref keyed by state: it is deleted with the row on every consumption path, so abandoned
   flows cannot leak it, and account deletion already cascades `oauth_states`.
3. **`logout` and `set_api_allocation` are not exposed at all**, per the approved answer.
4. **No `preview` on tools other than the overwrite.** Creates and evaluations have no
   before → after; the gate's argument rows already show exactly what will run.

---

## Deviations and open concerns

- **The FeatureScript argument names were never captured.** The spike recorded schema SIZES,
  not field names. Rather than guess, the preview DERIVES the content argument (the property
  the write schema declares and the read schema does not) and reuses the read tool's own
  properties for the identifying arguments. It therefore does not depend on the vendor's
  naming — but the derivation itself is unverified against the live server, and if it fails
  the tool **refuses the call** rather than previewing the wrong thing. **This is the one
  path that most needs a live run** (QA §5).
- **Unsubscribed-account behaviour is unverified.** No unsubscribed Onshape account was
  available. The probe treats any post-authentication failure as "subscription or Labs
  access", names both remedies, and shows the server's own words. It does not claim to
  distinguish them, because one signal cannot.
- **Whether fs-mcp rotates its refresh token is unverified.** Handled both ways: a response
  without a new refresh token keeps the existing one.
- **Onshape Labs admin-gating remains contradictory** in Onshape's own docs. Surfaced in the
  copy rather than resolved.
- **A DCR client from the spike** (`01a5e3e8-…`) exists on Onshape's side. The code
  registers its own and caches it; the spike's is orphaned and can be ignored or removed.
- **`Source.config["access"]` is not updated on a RECONNECT** (`integrations.py:188-205`
  applies config only when creating). Pre-existing, found while reading, out of scope, worth
  a ticket.

---

## Verification

| Check | Result |
| --- | --- |
| `ruff check .` | clean |
| `mypy packages/api/src` | clean, 180 files |
| `mypy` on every changed test | clean |
| API suite | **2745 passed, 4 skipped, 0 failed** (three sequential slices) |
| Desktop `vitest` | **1439 passed, 164 files** |
| Desktop `typecheck` | clean |
| `pnpm lint` | 0 errors (57 pre-existing warnings) |

**On the suite being run in slices:** the API suite takes ~13 min, past the shell's
10-minute cap, so it runs as three sequential slices of the same file list. It must run
**alone** — `conftest` truncates every table per test, so two concurrent pytest processes
destroy each other's fixtures. A first attempt here overlapped with the Stop gate's own run
and produced 35 spurious failures (`InvalidRequestError`, `DBAPIError`, `KeyError: 'data'`,
concentrated in `test_bridge*`); every one of them passes in isolation, and the clean
three-slice run is green.

### New tests

| File | Covers |
| --- | --- |
| `test_hosted_mcp_spec.py` | The registry as security policy: https-only reviewed hosts, scopes never widening past Read+Write, `logout`/`set_api_allocation` unexposed, per-tool consent, a second server needing only data. |
| `test_hosted_oauth.py` | DCR once and cached, scope-escalation refusal, PKCE freshness, rotation handled both ways, a dead grant saying *reconnect* rather than *retry*, bounded response bodies. |
| `test_featurescript_preview.py` | The diff: hunk rows survive the card's renderer, whole-file rows would not, divergence caught past the 500-char cap **through the real `_build_preview` path**, determinism, no silent truncation, argument names derived not guessed. |
| `test_never_raises_groups.py` | The `BaseExceptionGroup` hole, against the language itself; cancellation still propagates; a typed failure survives nesting. |
| `test_hosted_routes.py` | 404-not-403 across teams and projects, unknown-server refusal, strict decision bodies, end-to-end enable, the account-linking CSRF refused, single-use state, disconnect revoking the grant. |
| `test_hosted_tool_build.py` | Replay from the persisted inventory: gating re-read from the live policy not trusted from storage, a de-classified tool going dark without a re-sync, preview only on the overwrite, and the preview failing closed. |
| `HostedAddOnRow.test.tsx` | Three states, server-backed (absent/malformed ⇒ not connected), store link through the gated bridge, single-flight refusal surfaced verbatim. |
| `ConfirmationCard.test.tsx` (+3) | A terminal refusal keeps the card, disables both buttons, and is distinguished from a retryable transport failure. |
| `appStoreUrl.test.ts` | Exact-host allowlist; subdomains and lookalikes refused. |

---

## Human-owed

1. **Ratify or reject ADR-035** (tier-2, text proposed in-chat). Nothing in `DECISIONS.md`
   was edited.
2. **Review, push, open the MR, merge.** No push, no MR, no remote operation was performed.
3. **Run the Cowork QA pass** — especially §4 (unsubscribed account) and §5 (the diff).
