// Workspace shell: rail navigation, topbar, notifications, toast, screens.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { WorkspaceShell } from './WorkspaceShell'
import { useShellStore } from './shellStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

function renderShell(): void {
  render(
    <MemoryRouter>
      <WorkspaceShell />
    </MemoryRouter>
  )
}

beforeEach(() => {
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'maya@strider.dev' },
    onboarded: true
  })
})

describe('WorkspaceShell — chrome', () => {
  it('opens on the Context Model screen with the fallback project name', () => {
    renderShell()
    expect(screen.getByText('strider-qd12')).toBeInTheDocument()
    expect(screen.getAllByText('Context Model').length).toBeGreaterThan(0)
  })

  it('shows the real project name when one is linked', () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider MK3' }, linked: true })
    renderShell()
    expect(screen.getByText('Strider MK3')).toBeInTheDocument()
  })

  it('navigates between screens from the rail', async () => {
    renderShell()
    await userEvent.click(screen.getByText('Live Bench'))
    expect(screen.getByText('Live Bench', { selector: 'span[style*="font-size: 13"]' })).toBeDefined()
    await userEvent.click(screen.getByText('Team'))
    expect(useShellStore.getState().lastMain).toBe('team')
  })

  it('shows the open-alert badge count on the bell', () => {
    renderShell()
    expect(screen.getByText('2')).toBeInTheDocument() // a1 + a2 open
  })

  it('opens the notifications popover and routes to an alert', async () => {
    renderShell()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    // The graph screen behind the popover lists the same alert; click the
    // popover's row (inside #notif-a1) specifically.
    const popoverRow = document.querySelector('#notif-a1')
    expect(popoverRow).not.toBeNull()
    await userEvent.click(popoverRow as HTMLElement)
    // Alert screen mounts (topbar title flips to Alert; the alert view may
    // repeat the word, so assert at least one).
    expect(screen.getAllByText('Alert').length).toBeGreaterThan(0)
  })
})

describe('WorkspaceShell — magic-moment toast', () => {
  it('fires the SOL toast once after landing on the graph', async () => {
    vi.useFakeTimers()
    try {
      renderShell()
      await act(async () => {
        vi.advanceTimersByTime(5200)
      })
      expect(screen.getByText('SOL caught a cross-domain break')).toBeInTheDocument()
      expect(useShellStore.getState().toastShown).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not fire the toast twice', async () => {
    vi.useFakeTimers()
    try {
      useShellStore.getState().markToastShown()
      renderShell()
      await act(async () => {
        vi.advanceTimersByTime(6000)
      })
      expect(screen.queryByText('SOL caught a cross-domain break')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
