import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PreferencesSection } from './PreferencesSection'
import { useSettingsStore } from '../../../store/settingsStore'
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

beforeEach(() => {
  useSettingsStore.setState({
    solMode: 'Guide',
    theme: 'dark',
    accent: 'amber',
    density: 'regular'
  })
})

describe('PreferencesSection — SOL mode', () => {
  it('reflects the current mode from the store', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<PreferencesSection data={data()} />)
    const control = screen.getByLabelText('Answer mode')
    expect(control).toHaveTextContent('Expert')
  })

  it('persists a mode change through the backend action', async () => {
    const setSolMode = vi.fn(async () => true)
    render(<PreferencesSection data={data({ actions: { ...data().actions, setSolMode } })} />)
    await userEvent.click(screen.getByText('Expert'))
    expect(setSolMode).toHaveBeenCalledWith('Expert')
  })

  it('shows the SOL-mode error inline', () => {
    render(
      <PreferencesSection
        data={data({ errors: { sol_mode: 'Not allowed', consent: null, name: null } })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Not allowed')
  })

  it('falls back to a local-only mode change when offline', async () => {
    const setSolMode = vi.fn(async () => true)
    render(
      <PreferencesSection
        data={data({ status: 'offline', actions: { ...data().actions, setSolMode } })}
      />
    )
    await userEvent.click(screen.getByText('Expert'))
    expect(setSolMode).not.toHaveBeenCalled()
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })
})

describe('PreferencesSection — appearance (local)', () => {
  it('changes the theme in the local store', async () => {
    render(<PreferencesSection data={data()} />)
    await userEvent.selectOptions(screen.getByLabelText('Theme'), 'light')
    expect(useSettingsStore.getState().theme).toBe('light')
  })

  it('changes the density in the local store', async () => {
    render(<PreferencesSection data={data()} />)
    await userEvent.click(screen.getByText('compact'))
    expect(useSettingsStore.getState().density).toBe('compact')
  })
})
