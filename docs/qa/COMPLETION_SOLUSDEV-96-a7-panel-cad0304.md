# Completion report — SOLUSDEV-96: Fusion visibility, A7 panel pairing, CAD-03/04 assessment

Branch: `SOLUSDEV-60/ons-ui01-confirmation-surface` · Commits `f462603`, `b66609c`, `87b8c35`,
`c716707`

Governing docs consulted: `DECISIONS.md` (ADR-018, ADR-024, ADR-025, ADR-026, ADR-032, ADR-033),
`docs/contracts/*`, `integrations/mcp/CLAUDE.md`, `integrations/mcp/README.md`,
`integrations/mcp/LICENCE_VERIFICATION.md`, root `CLAUDE.md` §7.
`docs/architecture/` and `docs/wireflows/` remain **empty** — flagged again, as in previous reports.

---

## 1. Why Fusion 360 wasn't visible (answered, and fixed)

Not one bug — **four independent gaps**, each of which alone kept it invisible:

1. `SOLUS_COMPANION_URL` was set **nowhere in the repo**, so the companion died at
   `config_from_env` and `companion.ts` silently crash-looped it forever with `stdio` discarding
   stderr.
2. `integrations/mcp/` contained **only markdown** — no `fusion/allowlist.yaml`. Both the
   companion's `discover_servers` and the cloud's `load_allowlist` glob that path, so it was a
   **double gate**.
3. Tool names must come from a live `tools/list`; the server is closed-source with dynamic tooling.
4. Discoverability — the only UI that would ever say "fusion" is the bridge pill, and
   `routers/bridge.py` filters status against the (empty) allowlist before rendering.

Also worth stating plainly, because it is a recurring question: **Fusion will never appear on the
Integrations tile list, and that is correct.** That list is the _connector_ registry — cloud OAuth
integrations. Fusion has no cloud endpoint; it is a loopback MCP server on the user's own machine,
and reaching it through the companion is a **licensing requirement**, not an optimisation (Autodesk
prohibits hosting or multiplexing a licensed seat).

Fixed in `f462603`: `companionEnv.ts` derives the URL from the configured API base and **throws**
rather than emitting a `ws://` the companion would reject; `companion.ts` now pipes and logs the
child's stderr; `integrations/mcp/fusion/allowlist.yaml` exists with `tools: []`;
`scripts/capture-fusion-tools.py` captures the live list, refuses non-loopback URLs, and emits every
entry `requires_confirmation: true`.

**Tools stay empty until a human runs the capture.** Inventing names would be the fabricated-fixture
failure the vendoring rules exist to prevent — and here it is worse than a missing tool, because the
allowlist _is_ the security gate: a wrong name exposes nothing while looking configured.

---

## 2. A7 — the panel (Decisions 1 and 2)

**Decision 1 honoured as scoped.** The panel displays Solus content and pushes into Onshape; it does
not read click-selections back. The stated scope note is respected: **SOL's REST path is untouched**
and keeps full read/write at face and feature granularity. Nothing in this diff narrows the API-path
tool surface.

**Decision 2 built.** Device-code pairing (`PanelPairing` → `PanelBinding`, migration
`2d49fdc410e4`). `OAuthState` could not be reused after all: its `source_id` is a `NOT NULL` FK and
it has neither an attempt counter nor an approval column.

### The security hole in the stated shape, and what was done instead

The instruction was to key the panel on `{$userId}`. Exploration found that
`Source.account_external_id` already **is** the Onshape user id — OAuth-proven and
panel-uncreatable, which is genuinely attractive. But it is **not a secret**: Onshape user ids are
visible to anyone sharing a document, so a `{$userId}` match would let a collaborator read the
owner's Solus graph. Raised in-session; resolved to **the panel holds a secret, `{$userId}` only
selects** — its sole role is choosing which stored token to send.

### The structural guarantee, three layers

The requirement was to make provisioning _structurally_ unreachable and prove it with tests, not
assertions. `packages/api/tests/test_panel.py`:

1. **A dependant-tree walk** over every `/panel` route asserting it never reaches
   `get_current_user` / `get_current_claims` / `_provision_user`.
2. **A source-grep ratchet** on `routers/panel.py`, for the one thing a tree walk cannot see — a
   direct call inside a handler body. (The module's own docstrings are written without those names
   for this reason; the ratchet is the point, not the prose.)
3. **A route-enumerating behavioural test** firing hostile bearers at every panel route — including
   a **valid Supabase JWT for an unknown `sub`**, the exact credential that _would_ provision on any
   normal route — and asserting the `users` count is unchanged. It enumerates routes, so it covers
   panel routes that do not exist yet.

The approve/list/revoke trio deliberately lives in `routers/users.py`, not `panel.py`. That is what
keeps "no route under `/api/v1/panel` can reach provisioning" a statement a machine can check.

### Other decisions taken under delegated judgment

- **Brute-force safety does not rest on the rate limiter.** `core/ratelimit.py` keys on the
  Authorization header or `request.client.host`, and no proxy-header trust is configured — behind
  the ALB every unauthenticated caller shares one bucket. So: 256-bit device codes, a **durable
  `poll_count` cap on the row**, the device code sent as a Bearer (moving the poll loop into a
  per-credential bucket), a dedicated `path_limits` entry for `pair/start`, and approvals bounded
  per _authenticated_ user by a `ConnectRateLimiter`.
- **Token minted at redemption, never at approval** — the plaintext never exists server-side, not
  even for the ten-minute window, and is stored only as a sha256 digest (sha256 not a KDF: 256 bits
  of entropy leave nothing to slow down, and a KDF would force a table scan instead of an indexed
  equality).
- **Unknown, expired and exhausted device codes are indistinguishable** — no oracle.
- **Zero matching projects is an empty list, never a 403** — a panel must not become an existence
  oracle for another tenant's documents.
- **Served from the API origin** (`/panel`), not `panel.solusforge.com`: same-origin means no extra
  DNS record, no cert SAN, and — the real reason — **no widening of `SOLUS_CORS_ORIGINS`**.
- **CSP per-response, never global.** `frame-ancestors` is a no-op on JSON and a global
  `default-src` would break the CDN-loaded Swagger UI. No `X-Frame-Options` anywhere: it has no
  allowlist form, so it could only ever forbid the framing this feature exists to permit. Both
  directions are asserted.

### One defect I introduced and caught in self-review (`87b8c35`)

The panel page carried an inline `<style>` while its own CSP said `style-src 'self'` — it would have
rendered unstyled, and the obvious "fix" would have been to add `'unsafe-inline'`, weakening the
policy that exists to backstop exactly the XSS this page cannot afford (the token lives in its
localStorage). Split into `/panel/app.css` instead, added `X-Content-Type-Options: nosniff`, and
added `test_nothing_inline_needs_unsafe_inline`, the test that would have caught it.

### Desktop

`Settings → Onshape panel`: enter the pairing code, see live links with their Onshape label and
last-used, revoke one. Without this the flow had no approval surface at all.

---

## 3. CAD-03 / CAD-04 — the ticket premise was false

**CAD-03 assumed "strip the ~8 fabricated tools" from `SolidworksMCP-python`'s 112. The real number
is 48.** That is not a strip; it is a different fork.

Both LICENSEs were re-read in clones at pinned commits (`34a21fe`, `abc2a82`) — never the GitHub
API, per `LICENCE_VERIFICATION.md`. Both MIT. **MIT settles the legal question and nothing else**,
which is precisely what the fabricated-data checklist item exists to catch, and this is the first
time it has been exercised for real.

The disqualifying shape:

```python
if hasattr(adapter, "check_interference"):
    result = await adapter.check_interference(...)          # the real path
    ...
return {"status": "success", "interference_found": False}   # nothing ran
```

For Solus specifically this is worse than a missing tool. A confident false negative on an
interference check is the failure the product exists to prevent, the graph cannot distinguish
"clear" from "never looked", and SOL will summarise it as a real pass — in Guide mode, to a user
trusting it because they do not know the domain.

`U-C4N/Autocad-MCP` audited the same way: **0 of 155**, structurally rather than by luck, and its
`analysis_measure_area` even documents that it measures its arguments and not the drawing.

**Shipped as decision artifacts, not a fork**: a committed audit tool with tests pinning what it must
_not_ flag (a genuine second adapter attempt, VBA text generators, delegating wrappers), mechanically
drafted allowlists with everything `requires_confirmation: true` and the excluded tools left as
commented `EXCLUDED` lines, and two `PROVENANCE.md` files stating the options with a recommendation.

**No `upstream/` import was made.** It cannot ship without two human sign-offs, so importing ~20 MB
now would only enlarge a diff a human must review anyway. Per `integrations/mcp/CLAUDE.md` rule 3,
`SECURITY_REVIEW.md` is a human gate and was **not** self-approved.

CAD-04's actual substance is the graph mapping in `autocad/PROVENANCE.md` §4 — block definitions are
entities, inserts are instance relations, attributes carry the manufacturer part number, xrefs are
the only `depends_on`, and **there is no mass or volume to default**.

---

## 4. Verification

| Check                       | Result                                                     |
| --------------------------- | ---------------------------------------------------------- |
| `pytest packages/api/tests` | **1638 passed, 4 skipped** (baseline 1602 → +36 panel)     |
| `pytest integrations`       | 7 passed (audit-tool tests)                                |
| `ruff check` (repo)         | clean                                                      |
| `mypy` (262 source files)   | clean                                                      |
| desktop `vitest` (settings) | 64 passed, incl. 4 new `PanelLinksSection`                 |
| desktop `tsc --noEmit`      | clean, both projects                                       |
| desktop `eslint`            | no new findings (2 pre-existing errors confirmed by stash) |

---

## 5. Deviations and open concerns

1. **`docs/architecture/` and `docs/wireflows/` are still empty.** CLAUDE.md §3 says a missing
   diagram means the design phase is incomplete. Flagged, not improvised around — the panel followed
   `docs/contracts/*` and ADR-025 instead.
2. **An ADR is owed (tier-2, human).** "Panel tokens are a second, disjoint credential class;
   `{$userId}` is never identity." Proposed text is in `infrastructure/aws/HUMAN-STEPS.md`. Without
   it a reviewer will read a second bearer path as a §7 violation.
3. **Two vendoring decisions are owed** (§3 above, both recorded in HUMAN-STEPS).
4. **Onshape OAuth is still unconfigured on staging** — `SOLUS_ONSHAPE_CLIENT_ID` / `_SECRET` unset,
   so every connect fails `oauth_not_configured` and §2/§3 of the QA file cannot be exercised.
5. **Fusion has zero tools until a human runs the capture.** Deliberate, explained in the QA file so
   a tester does not file it as a bug.
6. **The panel extension must be registered in the Onshape developer portal** before §5 of the QA
   file is testable. Exact action URL is in HUMAN-STEPS.

## 6. Handoff

`docs/qa/COWORK_QA_onshape_fusion.md` — self-sufficient, written so the honest answer to "can I tell
it to edit a part?" is unmissable: **yes via SOL over REST with diff-and-approve; not via the panel;
and Fusion connected ≠ callable.** Its §3.2 stale-approval case, §3.5 prompt-injection case, and
§5.3 `{$userId}` case are marked critical — those are the security properties, not conveniences.

Nothing was pushed. No MR was opened. No `.env*` was edited.
