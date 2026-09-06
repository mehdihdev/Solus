# Completion report — SOLUSDEV-244 · HOME H4: Health and quota per connected account

Branch: `SOLUSDEV-244-home-h3-root-preferences` (shared with H3, CORPUS C2 and STORE ST3/ST4
sessions; local commits only, no push, no MR). Cowork QA:
`docs/qa/COWORK_QA_home-h4-account-health.md`. H3's report: `COMPLETION_SOLUSDEV-244-home-h3.md`.

## What already existed (SOLUSDEV-167 / I1) and was reused, not rebuilt

The provider-quota meter (`connectors/quota.py`): a Redis ledger per provider ACCOUNT per calendar
year, a degrade band at 70% of the allowance that pauses `scheduled` and `agent` traffic while a
user's own click still spends, and a 24-hour latch on an observed 402 that refuses everything. It
was surfaced only on the project Sources list (`serialize_source(quota=…)`); the Home account card
showed nothing. The card's Re-authorize flow (H2) already existed for a failed handshake.

## What H4 built

- **Derived health per grant** (`services/connection_health.py`): `token_expired` (the grant is in
  error, or a bound source's last sync was refused with `invalid_credentials`) › `degraded` (the
  meter's degraded band or the latch) › `healthy`. Never probed — a probe would spend the allowance
  the card protects, and the change-signal spine forbids turning a throttle into traffic.
- **Estimated quota position on `GET /users/me/connections` and `/{id}`**: the meter's block
  (`status ok|degraded|exhausted, used, allowance, estimated: true`), the same shape a source
  carries; absent for unmetered providers (GitHub, GitLab) and when the ledger is unreachable —
  no block beats a fictional one. `connection_projects` now also carries each bound source's last
  error code so health can see a rejected token.
- **Quota data events**: `integration.quota_degraded` / `integration.quota_exhausted`, recorded
  once per account per transition INTO that state (a Redis `…:seen` marker), payload
  `{provider, connection_id, used, allowance, estimated}` — the §7 abuse-detection signal that was
  missing.
- **Sweep amplifier fixed**: `quota_degraded` joins `NO_SIGNAL_CODES`. The Onshape connector's
  comment claimed it was there; it was not, so a degraded refusal during the hourly sweep read as
  "changed" and scheduled the full sync it had just refused.
- **The card** (`ConnectedAccountsCard`, `connectedAccounts.ts`): a health badge on every linked
  row (HEALTHY quiet, TOKEN EXPIRED / DEGRADED in the warn colour); for metered accounts "At least
  N of A <Provider> calls this year (estimate)" over a thin bar; a warn note that says what already
  degrades when approaching the limit (automatic syncs and SOL's calls pause; your own Sync now
  still reaches the provider; at the limit cache-only reads and no new syncs) and, at the wall,
  explains cache-only mode and that it is not an error; Re-authorize inline for an expired token
  even when the grant row itself still reads connected. Copy never says "remaining" or "left".
- Docs: `docs/api/API.md` connections row; `docs/wireflows/home.md` "Health and quota per account".

## Governing docs

DECISIONS.md ADR-019 (amended 2026-08-30: provider quota is a second budget; the surfaced position
is an estimate), ADR-024 (accounting never fails a request — the marker read is best-effort),
ADR-025; `docs/architecture/change-signal-spine.md` (fail-safe without the amplifier; cache-only,
visibly); `docs/wireflows/home.md` §Connected accounts; `docs/api/API.md` §2.1; CLAUDE.md §7
(rate-limit and budget events to data collection; tenant isolation). `docs/design/SPEC.md` and
`docs/design/screens/` do not exist in this repo.

## Verification

- API: `tests/test_connection_health.py` (9 tests: derivation, no-ledger, 80% flagged + one event,
  the wall reads exhausted not errored + its own event, rejected token on a bound source, failed
  handshake, unmetered provider, owner-only, bytes-answering Redis) and
  `test_connector_quota.py::test_a_degraded_refusal_is_no_signal_never_a_change`. Connection,
  adoption, quota and Onshape suites green (160). Desktop: 2 851 tests green across 274 files; main
  and renderer typecheck clean except one error from another session's uncommitted work
  (`features/extensions/firstParty.ts` importing a not-yet-present `bom/BomScreen`). Full API suite
  on the isolated DB: see the note at the end of this report.
- **Real run, API** (private uvicorn on :8001 with the dev Redis): seeded an Onshape account grant
  for the dev user and the ledger at 1 440 of 1 800; `GET /users/me/connections` answered
  `health: degraded`, `quota: {status: degraded, used: 1440, allowance: 1800, estimated: true}`,
  and ONE `integration.quota_degraded` row landed in `data_events`. **The first live load recorded a
  fresh event on every call** — the real redis client answers `get` in bytes and the fake in str, so
  the "already seen" comparison never matched. Fixed and pinned by
  `test_the_transition_marker_survives_a_bytes_answering_redis` (commit 13d2b14). Exactly the class
  of defect the "run the product for real" rule exists for.
- **Real run, desktop** (the real Electron app over CDP against that API), screenshots in the job
  scratch dir: `h4-degraded.png` — DEGRADED badge, "At least 1,440 of 1,800 Onshape calls this year
  (estimate)", the bar at 80%, the approaching note; `h4-exhausted.png` after latching the 402 —
  the cache-only note, "This is not an error and needs no sign-in", Revoke still present, no
  Re-authorize; `h4-expired.png` after flipping the grant to a rejected token — TOKEN EXPIRED badge,
  the note, **Re-authorize** in place; clicking it opened the account-mode connect wizard
  ("Choose access → Sign in") (`h4-expired-reauth.png`). The seeded grant, Redis keys and events
  were removed afterwards.
- The expired screenshot showed the badge wrapping inside the name line and the re-auth note
  missing a full stop after the provider's message; both polished (`whiteSpace: nowrap`, sentence
  punctuation) after the run.

## Decisions under delegated judgment (design gate answers recorded)

- Health is derived, never probed (user answer). "Approaching" is the existing 70% degrade band —
  one threshold, coinciding with the behaviour change; an account at 80% is therefore flagged
  (user answer). Unmetered providers say nothing about quota (user answer). The NO_SIGNAL fix and the
  quota events are in scope (user answer).
- Health precedence: token trouble outranks quota, because re-auth is what fixes it.
- The transition marker lives in Redis beside the ledger (`…:seen`, 400-day TTL) rather than a DB
  column: it is accounting state, best-effort by ADR-024, and dies with the ledger.
- `GET /users/me/connections` commits only when an event was queued; a plain read stays read-only.
- The 402 latch expiry (24 h) is not shown as a countdown; the note says "until the allowance
  resets" because the true reset (the provider's licence anniversary) is unknowable (ADR-019).

## Deviations / open concerns

- **Phase 4 subagent reviews for H4 were not run** in this session (the spend-limit pauses earlier
  in the day consumed the budget on H3's reviews, which did complete and were remediated — see H3's
  report). A self-review was done (no `console.*`, no `any`, immutability, typed client, owner-only
  routes, events consent-gated, best-effort Redis). Re-run `code-reviewer` and `security-reviewer`
  over commits `b4083c3 d914c76 13d2b14` before the MR.
- `Source.quota` (already emitted by the Sources list API) is still not in the desktop's `Source`
  type nor rendered on the Sources page — pre-existing gap, out of H4's scope, noted for W2.
- `integration.listing_refreshed` is documented in `API.md` but emitted nowhere (pre-existing;
  found in the survey). Not fixed here.
- Values a human must set: none new. `SOLUS_REDIS_URL` must be set for any quota to surface (it is
  in the local `.env`); without it the card shows health only.
