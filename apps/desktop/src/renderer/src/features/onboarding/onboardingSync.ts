// FND-08 onboarding state sync. The step lives server-side (settings endpoint)
// so a reload or a login on another machine resumes the right step — while the
// API being unreachable (dev bypass) degrades to local-only flow, never a block.
import {
  getSettings,
  updateOnboardingStep,
  type OnboardingStepName,
  type UserSettings
} from '../../lib/api/resources'
import type { OnboardingStep } from './onboardingStore'

const STEP_NAMES: readonly OnboardingStepName[] = ['about', 'connect', 'build']

export function stepIndexToName(step: OnboardingStep): OnboardingStepName {
  return STEP_NAMES[step]
}

/** Server step -> local index; `done` (or anything unknown) is not resumable. */
export function stepNameToIndex(name: string): OnboardingStep | null {
  const index = STEP_NAMES.indexOf(name as OnboardingStepName)
  return index === -1 ? null : (index as OnboardingStep)
}

export type HydrateResult =
  | { status: 'done' }
  | { status: 'resume'; step: OnboardingStep }
  | { status: 'offline' }

/**
 * Fetch the persisted onboarding state. `done` sends the user straight to the
 * workspace; an unknown/missing step resumes from the start; an unreachable
 * API resolves `offline` so onboarding still completes locally.
 */
export async function hydrateOnboarding(
  fetchSettings: () => Promise<UserSettings> = getSettings
): Promise<HydrateResult> {
  try {
    const settings = await fetchSettings()
    if (settings.onboarding_step === 'done') return { status: 'done' }
    return { status: 'resume', step: stepNameToIndex(settings.onboarding_step) ?? 0 }
  } catch {
    return { status: 'offline' }
  }
}

/** Persist a step transition. Best-effort: an API failure never blocks the UI. */
export async function persistOnboardingStep(
  step: OnboardingStepName,
  update: (step: OnboardingStepName) => Promise<unknown> = updateOnboardingStep
): Promise<void> {
  try {
    await update(step)
  } catch {
    // Offline / dev bypass — local flow carries on; the step re-persists on
    // the next transition that succeeds.
  }
}
