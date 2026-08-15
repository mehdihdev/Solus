// SOLX-02: the detached always-on-top window's surface (#/orb) — the same
// renderer, compact chrome, OrbChat body, and a re-attach hand-back.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { OrbWindow } from './OrbWindow'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useOrbStore } from './orbStore'
import type { SolWindowBridge } from './solWindowBridge'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', () => ({ classifyQuery: vi.fn() }))

const w = window as unknown as { solus?: { solWindow: SolWindowBridge } }

beforeEach(() => {
  localStorage.clear()
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'a@b.dev' },
    accessToken: null,
    onboarded: true
  })
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

afterEach(() => {
  delete w.solus
})

describe('OrbWindow', () => {
  it('renders the compact chat surface scoped to the persisted project', () => {
    render(<OrbWindow />)
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText('Rover MK2')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toBeInTheDocument()
  })

  it('hands back to the app through the attach invoke', () => {
    const bridge: SolWindowBridge = {
      detach: vi.fn(),
      attach: vi.fn().mockResolvedValue({ detached: false })
    }
    w.solus = { solWindow: bridge }
    render(<OrbWindow />)
    fireEvent.click(screen.getByRole('button', { name: 'Return to app' }))
    expect(bridge.attach).toHaveBeenCalledTimes(1)
  })

  it('asks the user to sign in from the main window when unauthenticated', () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null, onboarded: false })
    render(<OrbWindow />)
    expect(screen.getByText(/Sign in from the main Solus window/)).toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })

  it('shows nothing but the spinner while the session resolves', () => {
    useAuthStore.setState({ status: 'loading' })
    render(<OrbWindow />)
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })
})
