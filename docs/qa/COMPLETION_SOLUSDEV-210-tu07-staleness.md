# Completion report — SOLUSDEV-210 (SOLUS-TU-07): versioning + staleness / re-verification

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Commit:** `0886177`

## What was built

`packages/api/src/solus_api/toolkb/staleness.py` — the freshness half of TU-07 (version scoping
itself was already delivered in TU-04):

- `is_stale(entry, now)` — an entry not re-verified within `STALE_AFTER_DAYS` (180; ~twice-yearly,
  matching annual tool release cycles), falling back to `created_at` when never verified.
- `effective_confidence(entry, now)` — stored confidence scaled by an age-decay factor with a
  30-day grace (recently-verified = full confidence) reaching zero at 4× the stale threshold. A
  long-unverified entry therefore drops below the Guide tentative threshold and **renders tentative
  instead of confident** — the direct implementation of "staleness triggers re-acquisition rather
  than serving outdated guidance," because stale-but-served-confident is exactly the failure this
  lane exists to prevent.
- `find_stale(session, now)` / `sweep_stale(session, user, now)` — detect stale published entries
  and re-queue them: emit `tool_knowledge.staleness_flagged` per entry (tool, control_id,
  version_range, age — no customer content). The entry stays served but tentative until
  re-verification refreshes `last_verified_at`; it is never silently deleted.

Guide integration (`guides.py`): the resolver now computes each step's `tentative` from
**effective** (decayed) confidence and exposes a per-step `stale` flag (surfaced on the API); the
serialized `confidence` is the effective value, so the panel and the overlay-fallback both see the
honest current trust level.

## Acceptance (met)

- Entries are version-scoped (TU-04). A new tool release surfaces as "unavailable" in Guide (the
  version-scoped query returns nothing for an uncovered version) — an honest gap, not a stale
  answer.
- Entries are flagged stale on confidence decay (age) and the sweep re-queues them for
  re-acquisition.
- Staleness never serves outdated guidance as confident — decayed confidence forces tentative
  rendering.

## Tests

`tests/toolkb/test_staleness.py` — fresh-not-stale, old-verified-stale, never-verified-fallback,
fresh-confidence-unchanged, stale-confidence-decays-below-tentative, monotonic decay, find_stale
(published-only), sweep re-queues + emits the flag event. Plus the updated guides tests. Full
toolkb suite 135 passed; mypy clean.

## Flags / follow-ups

- **Scheduling** — `sweep_stale` is a library callable; wiring it to an ARQ cron is infra
  (out-of-lane) and is left as a follow-up. It takes an operator/system `User` for consent-gated
  event emission (same posture as the review CLI's operator).
- **Actual re-acquisition** — the sweep flags and re-queues; the real re-probe is the acquisition
  ladder's job and needs the tools/probes this host lacks (KiCad install / Onshape creds pending).
