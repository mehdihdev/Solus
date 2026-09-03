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
import * as switcherHook from './useProjectSwitcher'

// Populate the topbar project switcher deterministically (its live fetch is
// offline in jsdom). Other tests don't open the switcher, so this is inert.
vi.mock('./useProjectSwitcher', () => ({ useProjectSwitcher: vi.fn() }))

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
  vi.mocked(switcherHook.useProjectSwitcher).mockReturnValue({
    status: 'ready',
    groups: [
      {
        team: { team_id: 't1', name: 'Acme', role: 'member', is_personal: false },
        projects: [
          {
            id: 'p2',
            team_id: 't1',
            name: 'Rover MK3',
            description: null,
            archived_at: null,
            created_at: '',
            updated_at: ''
          }
        ]
      }
    ]
  } as ReturnType<typeof switcherHook.useProjectSwitcher>)
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

  it('exposes the project hub and sources in the rail (SOLUSDEV-164)', async () => {
    renderShell()
    await userEvent.click(screen.getByText('Overview'))
    expect(useShellStore.getState().lastMain).toBe('overview')
    // With no project open the hub honestly asks the user to pick one.
    expect(await screen.findByText(/select a project/i)).toBeInTheDocument()
    await userEvent.click(screen.getByText('Sources'))
    expect(useShellStore.getState().lastMain).toBe('sources')
  })

  it('exposes the Store in the rail and breadcrumbs the open extension (SOLUSDEV-235)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK3' }, linked: true })
    renderShell()
    await userEvent.click(screen.getByText('Store'))
    expect(useShellStore.getState().lastMain).toBe('store')
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open Experiments' }))
    expect(screen.getByText('Store / Experiments')).toBeInTheDocument()
    // Re-clicking the rail returns to the catalog rather than the stale detail page.
    await userEvent.click(screen.getByLabelText('Store'))
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('offers a project switcher in the topbar (SOLUSDEV-164)', () => {
    renderShell()
    expect(screen.getByRole('button', { name: /switch project/i })).toBeInTheDocument()
  })

  it('switching project from the topbar re-scopes the current screen without navigating', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Strider' }, linked: true })
    renderShell()
    // Move to a project-scoped screen, then switch project from the topbar.
    await userEvent.click(screen.getByText('Live Bench'))
    expect(useShellStore.getState().lastMain).toBe('bench')
    await userEvent.click(screen.getByRole('button', { name: /switch project/i }))
    await userEvent.click(await screen.findByText('Rover MK3'))
    // Context changed, but we stayed on Live Bench (no jump to Overview).
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Rover MK3' })
    expect(useShellStore.getState().lastMain).toBe('bench')
    // The topbar now shows the switched-to project as the active context.
    expect(screen.getByText('Rover MK3')).toBeInTheDocument()
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
