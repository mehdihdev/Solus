// SOL screen (SOLUSDEV-152): the scripted prototype conversation, fake
// think-delays, fabricated grounding footer, and fake apply-&-flash flow are
// gone. Chat wiring to the real SOL backend is SOLUSDEV-132/134; until then
// the screen is an honest not-connected state that keeps the orb identity
// and the universal Guide/Expert mode setting (ADR-016).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SolScreen } from './SolScreen'
import { useSettingsStore } from '../../store/settingsStore'

beforeEach(() => {
  vi.clearAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('SolScreen — honest not-connected state', () => {
  it('keeps the SOL identity and explains it is not wired yet', () => {
    render(<SolScreen />)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText('NOT CONNECTED')).toBeInTheDocument()
    expect(screen.getByText(/SOL isn't wired to this workspace yet/)).toBeInTheDocument()
    expect(screen.getByText(/evidence from the graph/)).toBeInTheDocument()
  })

  it('contains no scripted replies, fake grounding, or flash flow', () => {
    const { container } = render(<SolScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES|GROUNDED IN/)
    expect(text).not.toMatch(/STM32H743|Apply & flash/)
    expect(text).not.toMatch(/τ_FL_knee|U4|DRV/)
    expect(text).not.toMatch(/strider/i)
  })

  it('renders no chat input until the backend is wired', () => {
    render(<SolScreen />)
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
  })
})

describe('SolScreen — mode setting (ADR-016)', () => {
  it('switches the universal SOL mode from the header', () => {
    render(<SolScreen />)
    expect(screen.getByText('explains and teaches')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    expect(screen.getByText('terse, direct')).toBeInTheDocument()
  })
})
