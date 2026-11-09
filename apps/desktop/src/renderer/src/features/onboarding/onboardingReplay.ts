// SOLUSDEV-323: `pnpm dev:onboarding` — replay the whole onboarding flow on
// every launch, for testing it, even with an account that already finished it.
// Dev builds only: the literal `import.meta.env.DEV` folds to `false` in a
// production build, so the switch can never turn on for a real user.

export interface ReplayEnv {
  DEV?: boolean
  VITE_FORCE_ONBOARDING?: string
}

/** On only in a dev build launched with VITE_FORCE_ONBOARDING=1. */
export function replayRequested(env: ReplayEnv): boolean {
  return env.DEV === true && env.VITE_FORCE_ONBOARDING === '1'
}

let active = import.meta.env.DEV && replayRequested(import.meta.env)

/** True from launch until the replayed flow finishes (once per launch). */
export function isOnboardingReplay(): boolean {
  return active
}

export function startOnboardingReplay(): void {
  active = true
}

export function endOnboardingReplay(): void {
  active = false
}
