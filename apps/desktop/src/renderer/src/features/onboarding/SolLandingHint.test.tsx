// SOLUSDEV-323 Land (docs/wireflows/onboarding.md §7): a one-time hint pill on
// the workspace after onboarding completes — dismissable, auto-hides.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SolLandingHint, LANDING_HINT_MS } from './SolLandingHint'
import { useOnboardingStore } from './onboardingStore'

beforeEach(() => useOnboardingStore.getState().reset())
afterEach(() => vi.useRealTimers())

describe('SolLandingHint', () => {
  it('renders nothing unless onboarding just completed', () => {
    render(<SolLandingHint />)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('shows once, and Dismiss clears it for good', async () => {
    useOnboardingStore.getState().setLandingHint(true)
    render(<SolLandingHint />)
    expect(screen.getByRole('status')).toHaveTextContent(/double-tap ctrl/i)
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByRole('status')).toBeNull()
    expect(useOnboardingStore.getState().landingHint).toBe(false)
  })

  it('hides itself after a while', () => {
    vi.useFakeTimers()
    useOnboardingStore.getState().setLandingHint(true)
    render(<SolLandingHint />)
    act(() => vi.advanceTimersByTime(LANDING_HINT_MS + 1))
    expect(screen.queryByRole('status')).toBeNull()
  })
})
