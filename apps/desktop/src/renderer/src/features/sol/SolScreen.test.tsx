// SOL screen (SOLX-02 / SOLUSDEV-201): the backend IS wired now — the empty
// "not connected" state is replaced by the full-page chat surface reusing
// OrbChat. Still no fabricated robot data (SOLUSDEV-152 stands), and the
// universal Guide/Expert mode setting (ADR-016) stays in the header.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import * as solApi from './solApi'
import { SolScreen } from './SolScreen'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useOrbStore } from './orbStore'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', () => ({ classifyQuery: vi.fn() }))
const listSolTurns = vi.mocked(solApi.listSolTurns)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  listSolTurns.mockResolvedValue([])
  useSettingsStore.setState({ solMode: 'Guide' })
  useWorkspaceStore.setState({
    teamId: 't1',
    project: { id: 'p1', name: 'Rover MK2' },
    linked: true
  })
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
})

describe('SolScreen — live chat surface', () => {
  it('keeps the SOL identity and scopes to the open project', () => {
    render(<SolScreen />)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText('Rover MK2')).toBeInTheDocument()
  })

  it('renders the chat input — the backend is wired (replaces the SOLUSDEV-152 pin)', () => {
    render(<SolScreen />)
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('loads the project conversation history', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([
      {
        id: 't1',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'The IMU shares the I2C bus.',
        attrs: {},
        created_at: ''
      }
    ])
    render(<SolScreen />)
    expect(await screen.findByText('The IMU shares the I2C bus.')).toBeInTheDocument()
    expect(listSolTurns).toHaveBeenCalledWith('p1', 'c1')
  })

  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    render(<SolScreen />)
    expect(screen.getByText(/Open a project to chat with SOL/)).toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })

  it('contains no scripted replies, fake grounding, or flash flow (SOLUSDEV-152 stands)', () => {
    const { container } = render(<SolScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/247 NODES|GROUNDED IN/)
    expect(text).not.toMatch(/STM32H743|Apply & flash/)
    expect(text).not.toMatch(/τ_FL_knee|U4|DRV/)
    expect(text).not.toMatch(/strider/i)
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
