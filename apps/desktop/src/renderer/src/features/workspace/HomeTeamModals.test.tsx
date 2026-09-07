// SOLUSDEV-244 / HOME H5: every team dialog names its refusal; the plan limit
// carries the upgrade path; leaving as the last owner is explained.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HomeTeamModals, modalResult, type HomeTeamModalsProps } from './HomeTeamModals'
import type { HomeActions } from './useHomeData'
import type { HomeTeam } from './useHomeTeam'

function homeActions(): HomeActions {
  return {
    switchTeam: vi.fn(),
    createProject: vi.fn(),
    createTeam: vi.fn(),
    joinTeam: vi.fn(),
    renameProject: vi.fn(),
  editProject: vi.fn(),
    archiveProject: vi.fn(),
    unarchiveProject: vi.fn(),
    deleteProject: vi.fn(),
    refresh: vi.fn()
  }
}
function homeTeam(): HomeTeam {
  return {
    status: 'ready',
    detail: null,
    members: [],
    invites: [],
    activity: [],
    activityTotal: 0,
    activityHasMore: false,
    myRole: 'owner',
    teamLimit: null,
    actions: {
      invite: vi.fn(),
      revoke: vi.fn(),
      changeRole: vi.fn(),
      remove: vi.fn(),
      leave: vi.fn(),
      rename: vi.fn(async () => true),
      deleteTeam: vi.fn(async () => true),
      loadMoreActivity: vi.fn(),
      refresh: vi.fn()
    }
  }
}
function props(modal: HomeTeamModalsProps['modal']): HomeTeamModalsProps {
  return {
    modal,
    teamName: 'Strider',
    home: homeActions(),
    team: homeTeam(),
    onClose: vi.fn(),
    onUpgrade: vi.fn()
  }
}

describe('modalResult', () => {
  it('maps a plan limit to the upgrade path and other reasons to sentences', () => {
    expect(
      modalResult({
        ok: false,
        reason: 'plan_limit',
        limit: { limit: 'max_teams', current: 2, max: 2, message: 'At limit.' }
      })
    ).toEqual({ message: 'At limit.', upgrade: true })
    expect(modalResult({ ok: false, reason: 'expired' })).toEqual({
      message: 'This invite has expired. Ask for a new one.'
    })
  })
})

describe('HomeTeamModals', () => {
  it('New team: a BASIC user at the limit sees the limit and the upgrade path', async () => {
    const p = props('newTeam')
    vi.mocked(p.home.createTeam).mockResolvedValue({
      ok: false,
      reason: 'plan_limit',
      limit: {
        limit: 'max_teams',
        current: 2,
        max: 2,
        message: "You're at your collaborative-team limit."
      }
    })
    render(<HomeTeamModals {...p} />)
    await userEvent.type(screen.getByLabelText('Team name'), 'Third')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByTestId('plan-limit')).toHaveTextContent('collaborative-team limit')
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(p.onUpgrade).toHaveBeenCalled()
    expect(p.onClose).not.toHaveBeenCalled()
  })

  it('Join: names an expired token; closes on success', async () => {
    const p = props('join')
    vi.mocked(p.home.joinTeam).mockResolvedValueOnce({ ok: false, reason: 'expired' })
    render(<HomeTeamModals {...p} />)
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(await screen.findByText(/has expired/)).toBeInTheDocument()
    vi.mocked(p.home.joinTeam).mockResolvedValueOnce({ ok: true, teamId: 't7', role: 'member' })
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(p.onClose).toHaveBeenCalled()
  })

  it('Leave: explains the last-owner rule instead of a generic failure', async () => {
    const p = props('leave')
    vi.mocked(p.team.actions.leave).mockResolvedValue({ ok: false, reason: 'last_owner' })
    render(<HomeTeamModals {...p} />)
    expect(screen.getByText(/lose access to/)).toHaveTextContent('Strider')
    await userEvent.click(screen.getByRole('button', { name: 'Leave team' }))
    expect(await screen.findByText(/at least one owner/)).toBeInTheDocument()
    expect(p.onClose).not.toHaveBeenCalled()
  })

  it('Delete: the shared confirm names the team and what goes with it', async () => {
    const p = props('delete')
    render(<HomeTeamModals {...p} />)
    expect(screen.getByText('Strider')).toBeInTheDocument()
    expect(screen.getByText(/every project in it/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete team' }))
    expect(p.team.actions.deleteTeam).toHaveBeenCalled()
  })

  it('Rename: seeds the current name', () => {
    render(<HomeTeamModals {...props('rename')} />)
    expect(screen.getByLabelText('Team name')).toHaveValue('Strider')
  })

  it('renders nothing when closed', () => {
    const { container } = render(<HomeTeamModals {...props(null)} />)
    expect(container).toBeEmptyDOMElement()
  })
})
