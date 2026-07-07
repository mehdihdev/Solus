// FND-08 state-machine sync: server step <-> local step index, hydrate + persist.
import { describe, it, expect, vi } from 'vitest'
import {
  stepIndexToName,
  stepNameToIndex,
  hydrateOnboarding,
  persistOnboardingStep
} from './onboardingSync'

describe('step mapping', () => {
  it('maps indices to server names and back', () => {
    expect(stepIndexToName(0)).toBe('about')
    expect(stepIndexToName(1)).toBe('connect')
    expect(stepIndexToName(2)).toBe('build')
    expect(stepNameToIndex('about')).toBe(0)
    expect(stepNameToIndex('connect')).toBe(1)
    expect(stepNameToIndex('build')).toBe(2)
  })

  it('treats done as no resumable step', () => {
    expect(stepNameToIndex('done')).toBeNull()
  })
})

describe('hydrateOnboarding', () => {
  it('reports done when the server says onboarding finished', async () => {
    const fetchSettings = vi.fn().mockResolvedValue({
      sol_mode: 'guide',
      data_collection_consent: false,
      onboarding_step: 'done'
    })
    expect(await hydrateOnboarding(fetchSettings)).toEqual({ status: 'done' })
  })

  it('reports the saved step for a mid-flow user', async () => {
    const fetchSettings = vi.fn().mockResolvedValue({
      sol_mode: 'guide',
      data_collection_consent: false,
      onboarding_step: 'connect'
    })
    expect(await hydrateOnboarding(fetchSettings)).toEqual({ status: 'resume', step: 1 })
  })

  it('degrades to offline when the API is unreachable (dev bypass)', async () => {
    const fetchSettings = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'))
    expect(await hydrateOnboarding(fetchSettings)).toEqual({ status: 'offline' })
  })

  it('treats an unknown server step as a fresh start', async () => {
    const fetchSettings = vi.fn().mockResolvedValue({
      sol_mode: 'guide',
      data_collection_consent: false,
      onboarding_step: 'mystery'
    })
    expect(await hydrateOnboarding(fetchSettings)).toEqual({ status: 'resume', step: 0 })
  })
})

describe('persistOnboardingStep', () => {
  it('sends the step to the API', async () => {
    const update = vi.fn().mockResolvedValue({})
    await persistOnboardingStep('build', update)
    expect(update).toHaveBeenCalledWith('build')
  })

  it('never throws when the API is down (best-effort)', async () => {
    const update = vi.fn().mockRejectedValue(new Error('down'))
    await expect(persistOnboardingStep('done', update)).resolves.toBeUndefined()
  })
})
