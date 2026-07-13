import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProfileSection } from './ProfileSection'
import type { SettingsData } from '../useSettingsData'
import type { Me } from '../../../lib/api/resources'

const ME: Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya K',
  avatar_url: null,
  created_at: '',
  teams: []
}

function data(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    status: 'ready',
    profile: ME,
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

describe('ProfileSection', () => {
  it('renders the current name and email', () => {
    render(<ProfileSection data={data()} />)
    expect(screen.getByDisplayValue('Maya K')).toBeInTheDocument()
    expect(screen.getByText('maya@strider.dev')).toBeInTheDocument()
  })

  it('saves an edited name through the action', async () => {
    const updateName = vi.fn(async () => true)
    render(<ProfileSection data={data({ actions: { ...data().actions, updateName } })} />)
    const input = screen.getByLabelText('Display name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Ada Lovelace')
    await userEvent.click(screen.getByText('Save'))
    expect(updateName).toHaveBeenCalledWith('Ada Lovelace')
  })

  it('renders the envelope error inline when the save fails', () => {
    render(
      <ProfileSection
        data={data({ errors: { sol_mode: null, consent: null, name: 'Name too long' } })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Name too long')
  })
})
