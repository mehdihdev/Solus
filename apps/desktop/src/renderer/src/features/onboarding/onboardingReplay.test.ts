// SOLUSDEV-323: `pnpm dev:onboarding` — a dev-only replay of the whole flow.
import { afterEach, describe, expect, it } from 'vitest'
import {
  endOnboardingReplay,
  isOnboardingReplay,
  replayRequested,
  startOnboardingReplay
} from './onboardingReplay'

describe('replayRequested', () => {
  it('is on only in a dev build with VITE_FORCE_ONBOARDING=1', () => {
    expect(replayRequested({ DEV: true, VITE_FORCE_ONBOARDING: '1' })).toBe(true)
  })

  it('is off in a production build even when the variable is set', () => {
    expect(replayRequested({ DEV: false, VITE_FORCE_ONBOARDING: '1' })).toBe(false)
  })

  it('is off when the variable is missing or anything but 1', () => {
    expect(replayRequested({ DEV: true })).toBe(false)
    expect(replayRequested({ DEV: true, VITE_FORCE_ONBOARDING: 'true' })).toBe(false)
  })
})

describe('the replay switch', () => {
  afterEach(endOnboardingReplay)

  it('is off by default under test', () => {
    expect(isOnboardingReplay()).toBe(false)
  })

  it('stays on until the flow ends it, once per launch', () => {
    startOnboardingReplay()
    expect(isOnboardingReplay()).toBe(true)
    endOnboardingReplay()
    expect(isOnboardingReplay()).toBe(false)
  })
})
