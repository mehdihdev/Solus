import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsScreen } from './SettingsScreen'
import { useSettingsStore } from '../../store/settingsStore'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { INTEGRATIONS } from '../onboarding/integrations.constants'
import { SOLUS_THEMES } from '../../theme/tokens.constants'

function reset(): void {
  useOnboardingStore.getState().reset()
  useSettingsStore.setState({
    theme: 'dark',
    accent: 'amber',
    density: 'regular',
    solMode: 'Guide'
  })
  vi.clearAllMocks()
}

describe('SettingsScreen — SOL', () => {
  beforeEach(reset)

  it('updates the settings store when the answer mode changes', async () => {
    render(<SettingsScreen />)
    await userEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })

  it('reflects the current SOL mode from the store', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<SettingsScreen />)
    expect(screen.getByRole('radio', { name: 'Expert' })).toHaveAttribute('aria-checked', 'true')
  })
})

describe('SettingsScreen — appearance', () => {
  beforeEach(reset)

  it('lists every theme preset and updates the store on change', async () => {
    render(<SettingsScreen />)
    const select = screen.getByRole('combobox')
    for (const preset of Object.values(SOLUS_THEMES)) {
      expect(screen.getByRole('option', { name: preset.name })).toBeInTheDocument()
    }
    await userEvent.selectOptions(select, 'light')
    expect(useSettingsStore.getState().theme).toBe('light')
  })

  it('updates the accent when a swatch is clicked', async () => {
    render(<SettingsScreen />)
    await userEvent.click(screen.getByRole('button', { name: 'Accent teal' }))
    expect(useSettingsStore.getState().accent).toBe('teal')
  })

  it('updates the density via the segmented control', async () => {
    render(<SettingsScreen />)
    await userEvent.click(screen.getByRole('radio', { name: 'compact' }))
    expect(useSettingsStore.getState().density).toBe('compact')
  })
})

describe('SettingsScreen — integrations', () => {
  beforeEach(reset)

  it('shows every integration as not connected by default', () => {
    render(<SettingsScreen />)
    for (const integration of INTEGRATIONS) {
      expect(screen.getByText(integration.name)).toBeInTheDocument()
    }
    expect(screen.getAllByText('○ NOT CONNECTED')).toHaveLength(INTEGRATIONS.length)
    expect(screen.queryByText('● CONNECTED')).not.toBeInTheDocument()
  })

  it('marks integrations connected from the onboarding store', () => {
    useOnboardingStore.getState().completeConnect('github')
    useOnboardingStore.getState().completeConnect('kicad')
    render(<SettingsScreen />)
    expect(screen.getAllByText('● CONNECTED')).toHaveLength(2)
    expect(screen.getAllByText('○ NOT CONNECTED')).toHaveLength(INTEGRATIONS.length - 2)
  })

  it('treats busy or errored sources as not connected', () => {
    useOnboardingStore.getState().beginConnect('github')
    useOnboardingStore.getState().failConnect('ros', 'oauth cancelled')
    render(<SettingsScreen />)
    expect(screen.queryByText('● CONNECTED')).not.toBeInTheDocument()
    expect(screen.getAllByText('○ NOT CONNECTED')).toHaveLength(INTEGRATIONS.length)
  })
})

describe('SettingsScreen — static sections', () => {
  beforeEach(reset)

  it('renders profile, usage, and workspace sections', () => {
    render(<SettingsScreen />)
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Maya Krishnan')).toBeInTheDocument()
    expect(screen.getByText('Usage')).toBeInTheDocument()
    expect(screen.getByText('TEAM PLAN')).toBeInTheDocument()
    expect(screen.getByText('Cross-domain checks')).toBeInTheDocument()
    expect(screen.getByText('strider-qd12')).toBeInTheDocument()
    expect(screen.getByText('Delete workspace')).toBeInTheDocument()
  })

  it('omits prototype-only orb tweak controls that have no store backing', () => {
    render(<SettingsScreen />)
    expect(screen.queryByText('Orb behavior')).not.toBeInTheDocument()
    expect(screen.queryByText('Orb energy')).not.toBeInTheDocument()
  })
})
