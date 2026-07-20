// Workspace shell: rail navigation, topbar, notifications, toast plumbing,
// and the verify-email banner. SOLUSDEV-152: no demo alerts, no scripted
// magic-moment toast, no fabricated project name.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { WorkspaceShell } from './WorkspaceShell'
import { useShellStore } from './shellStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

function renderShell(): ReturnType<typeof render> {
  return render(
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
    user: { email: 'dev@example.dev' },
    onboarded: true
  })
})

describe('WorkspaceShell — chrome', () => {
  it('opens on Home with an honest no-project topbar fallback', async () => {
    renderShell()
    // Authenticated sessions now attempt a real fetch first (spinner), then
    // settle offline in jsdom where the API is unreachable.
    expect(await screen.findByText(/Welcome back/)).toBeInTheDocument()
    expect(screen.getByText('No project')).toBeInTheDocument()
    // Signed-in + unreachable API must never read as "sign in".
    expect(screen.getByText(/can't reach its API/)).toBeInTheDocument()
    expect(screen.queryByText(/Sign in to Solus/)).not.toBeInTheDocument()
  })

  it('shows the real project name when one is linked', () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    renderShell()
    expect(screen.getByText('Rover MK3')).toBeInTheDocument()
  })

  it('navigates between screens from the rail', async () => {
    renderShell()
    await userEvent.click(screen.getByText('Live Bench'))
    expect(useShellStore.getState().lastMain).toBe('bench')
    await userEvent.click(screen.getByText('Team'))
    expect(useShellStore.getState().lastMain).toBe('team')
  })

  it('shows no unread badge when offline — alerts are never fabricated', () => {
    renderShell()
    expect(screen.queryByText('2')).not.toBeInTheDocument()
  })

  it('offline bell opens an honest popover instead of demo alerts', async () => {
    renderShell()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument()
    // Signed in (beforeEach) + unreachable API → the honest unreachable note.
    expect(screen.getByText(/can't reach its API right now/)).toBeInTheDocument()
    expect(screen.queryByText(/Motor driver swap/)).not.toBeInTheDocument()
  })

  it('offline bell shows the sign-in nudge for signed-out sessions', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    renderShell()
    await userEvent.click(screen.getByTestId('rail-bell'))
    expect(screen.getByText(/Sign in to Solus to see notifications/)).toBeInTheDocument()
  })

  it('renders no fabricated robot data anywhere in the shell', () => {
    const { container } = renderShell()
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/Priya|DRV8316C|U4 swap/)
  })
})

describe('WorkspaceShell — no scripted magic-moment toast', () => {
  it('fires no toast after landing on the graph', async () => {
    vi.useFakeTimers()
    try {
      renderShell()
      fireEvent.click(screen.getByText('Context Model'))
      await act(async () => {
        vi.advanceTimersByTime(6000)
      })
      expect(useShellStore.getState().toast).toBeNull()
      expect(screen.queryByText('SOL caught a cross-domain break')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('WorkspaceShell — email verification banner', () => {
  it('shows the verify-email banner when the email is unverified', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: false },
      onboarded: true
    })
    renderShell()
    expect(screen.getByRole('alert')).toHaveTextContent(/Verify your email/)
    expect(screen.getByText('Resend email')).toBeInTheDocument()
  })

  it('hides the banner for a verified email', () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: true },
      onboarded: true
    })
    renderShell()
    expect(screen.queryByText(/Verify your email/)).not.toBeInTheDocument()
  })

  it('resends the verification email on request', async () => {
    useAuthStore.setState({
      status: 'authenticated',
      user: { email: 'dev@example.dev', emailVerified: false },
      onboarded: true
    })
    renderShell()
    await userEvent.click(screen.getByText('Resend email'))
    expect(screen.getByText('Verification email sent.')).toBeInTheDocument()
  })
})
