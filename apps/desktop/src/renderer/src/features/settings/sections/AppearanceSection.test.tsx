import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppearanceSection } from './AppearanceSection'
import { useSettingsStore } from '../../../store/settingsStore'
import { SOLUS_THEMES } from '../../../theme/tokens.constants'

beforeEach(() => {
  useSettingsStore.setState({ theme: 'dark', accent: 'amber', solMode: 'Guide' })
})

describe('AppearanceSection', () => {
  it('shows one pressed tile per theme, the current one pressed', () => {
    render(<AppearanceSection />)
    for (const t of Object.values(SOLUS_THEMES)) {
      expect(screen.getByRole('button', { name: t.name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Solus Dark' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
  })

  it('changes the theme in the local store', async () => {
    render(<AppearanceSection />)
    await userEvent.click(screen.getByRole('button', { name: 'Solus Light' }))
    expect(useSettingsStore.getState().theme).toBe('light')
    expect(screen.getByRole('button', { name: 'Solus Light' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
  })

  it('changes the accent', async () => {
    render(<AppearanceSection />)
    await userEvent.click(screen.getByRole('button', { name: 'Accent teal' }))
    expect(useSettingsStore.getState().accent).toBe('teal')
  })

  it('has no density control (SOLUSDEV-318)', () => {
    render(<AppearanceSection />)
    expect(screen.queryByText(/density/i)).toBeNull()
  })
})
