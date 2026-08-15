# Completion report — SOLUS-RBT-04 Active identification (SOLUSDEV-231)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified against synthetic
telemetry including the mandatory cannot-tell case; **the physical-robot verification is NOT
RUN** — there is no actuator on this bench (audited), and the end-to-end gated dispatch is
unverifiable until the SOLUSDEV-60 approval surface merges. Both stated plainly, not claimed.

## What was built — `livebench/recognition/active.py`

- `MotionPlan` — bounded at construction: |magnitude| ≤ 0.2 normalized (a twitch, not a
  sweep), duration ≤ 5s. An out-of-bound plan cannot exist.
- `propose_motion` — the CTR-03 `ToolConfirmationEvent`: summary + `DiffRow` preview showing
  the EXACT actuator and commanded value before anything moves.
- `run_active_identification(plan, command=…, capture=…, approval=…)` — propose → gate →
  baseline capture → bounded motion → during capture → correlate. **Refusal returns before
  the command callable is ever invoked** (tested: refusing leaves the hardware untouched).
  The `approval` seam is where SOLUSDEV-60's flow plugs in; on this branch the runtime gate
  can only refuse (flagged at Phase 0), so tests drive fakes and the report says so.
- `correlate` — pure per-channel deflection scoring (|mean shift| in baseline-noise σ).
  A channel identifies ONLY when it clears 5σ AND beats the runner-up 3×; otherwise the
  verdict is an explicit **NO RESULT** — including the deliberate two-channels-deflect
  ambiguous case the ticket requires. An unambiguous hit emits bus-grade evidence
  (`telemetry_channel` @ 0.9 MATCHED, "observed, not inferred") feeding RBT-03; the user
  still confirms.

## Verification

171 livebench tests green (this ticket: 8 — bounds, exact-value proposal, refusal,
exact-command approval, identified, ambiguous→no-result, silent→no-result, deterministic
scores). mypy strict clean; ruff clean. TDD RED→GREEN.

## Unmet gates (for the humans)

- Physical robot incl. a real "cannot tell": needs an actuator + telemetry on this bench.
- Live gate flow: needs SOLUSDEV-60 merged; then `approval` binds to the real SSE confirm.
