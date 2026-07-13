import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PrivacySection } from './PrivacySection'
import type { SettingsData } from '../useSettingsData'

function data(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    status: 'ready',
    profile: null,
    consent: true,
    subscription: null,
    errors: { sol_mode: null, consent: null, name: null },
    actions: {
      setSolMode: vi.fn(async () => true),
      setConsent: vi.fn(async () => true),
      updateName: vi.fn(async () => true),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  }
}

describe('PrivacySection', () => {
  it('reflects the current consent state', () => {
    render(<PrivacySection data={data({ consent: true })} />)
    expect(screen.getByLabelText('Data collection')).toHaveTextContent('On')
  })

  it('opts out through the action', async () => {
    const setConsent = vi.fn(async () => true)
    render(<PrivacySection data={data({ actions: { ...data().actions, setConsent } })} />)
    await userEvent.click(screen.getByText('Off'))
    expect(setConsent).toHaveBeenCalledWith(false)
  })

  it('opts back in through the action', async () => {
    const setConsent = vi.fn(async () => true)
    render(
      <PrivacySection data={data({ consent: false, actions: { ...data().actions, setConsent } })} />
    )
    await userEvent.click(screen.getByText('On'))
    expect(setConsent).toHaveBeenCalledWith(true)
  })

  it('surfaces the consent error inline', () => {
    render(
      <PrivacySection
        data={data({ errors: { sol_mode: null, consent: 'save failed', name: null } })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('save failed')
  })
})
