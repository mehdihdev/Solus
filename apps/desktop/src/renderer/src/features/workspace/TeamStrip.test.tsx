// SOLUSDEV-244 / HOME H5: the team strip — always the active team, the
// switcher only with more than one team, role-gated actions, and the plan
// limit stated with its upgrade path.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TeamSummary } from '../../lib/api/resources'
import { AT_LIMIT_MESSAGE, TeamStrip, teamLimitText, type TeamStripProps } from './TeamStrip'

const PERSONAL: TeamSummary = {
  team_id: 't-me',
  name: 'Maya',
  role: 'owner',
  is_personal: true,
  plan_status: 'trial',
  trial_ends_at: ''
}
const TEAM: TeamSummary = { ...PERSONAL, team_id: 't1', name: 'Strider', is_personal: false }

function props(overrides: Partial<TeamStripProps> = {}): TeamStripProps {
  return {
    team: TEAM,
    teams: [PERSONAL, TEAM],
    memberCount: 3,
    myRole: 'owner',
    teamLimit: { current: 1, max: 2, atLimit: false },
    onSwitch: vi.fn(),
    onJoin: vi.fn(),
    onNewTeam: vi.fn(),
    onInvite: vi.fn(),
    onRename: vi.fn(),
    onLeave: vi.fn(),
    onDelete: vi.fn(),
    onUpgrade: vi.fn(),
    ...overrides
  }
}

describe('TeamStrip', () => {
  it('always names the active team; the switcher only with more than one team', () => {
    const { unmount } = render(<TeamStrip {...props()} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.getByText('3 members')).toBeInTheDocument()
    expect(screen.getByLabelText('Switch team')).toBeInTheDocument()
    unmount()
    render(<TeamStrip {...props({ teams: [TEAM] })} />)
    expect(screen.queryByLabelText('Switch team')).toBeNull()
  })

  it('marks the personal workspace and never offers leave or delete on it', async () => {
    render(<TeamStrip {...props({ team: PERSONAL, memberCount: 1 })} />)
    expect(screen.getByText(/personal workspace/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Rename team' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Leave team' })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
  })

  it('gates the menu by role: owner deletes, admin renames, member only leaves', async () => {
    const owner = props()
    const first = render(<TeamStrip {...owner} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete team' }))
    expect(owner.onDelete).toHaveBeenCalled()
    first.unmount()

    const second = render(<TeamStrip {...props({ myRole: 'admin' })} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Rename team' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Leave team' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
    second.unmount()

    const member = props({ myRole: 'member' })
    render(<TeamStrip {...member} />)
    expect(screen.queryByRole('button', { name: /invite teammate/i })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.queryByRole('menuitem', { name: 'Rename team' })).toBeNull()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Leave team' }))
    expect(member.onLeave).toHaveBeenCalled()
  })

  it('shows Invite only to managers and routes Join / New team', async () => {
    const p = props()
    render(<TeamStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: /invite teammate/i }))
    await userEvent.click(screen.getByRole('button', { name: /join team/i }))
    await userEvent.click(screen.getByRole('button', { name: /new team/i }))
    expect(p.onInvite).toHaveBeenCalled()
    expect(p.onJoin).toHaveBeenCalled()
    expect(p.onNewTeam).toHaveBeenCalled()
  })

  it('states the plan position, and at the limit the upgrade path', async () => {
    const p = props({ teamLimit: { current: 2, max: 2, atLimit: true } })
    render(<TeamStrip {...p} />)
    expect(screen.getByTestId('team-limit')).toHaveTextContent('2 of 2 collaborative teams')
    expect(screen.getByTestId('team-limit')).toHaveTextContent('personal team never counts')
    expect(screen.getByRole('note')).toHaveTextContent(AT_LIMIT_MESSAGE)
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(p.onUpgrade).toHaveBeenCalled()
  })

  it('says nothing about a limit that is unknown or unlimited', () => {
    expect(teamLimitText(null)).toBeNull()
    expect(teamLimitText({ current: 5, max: null, atLimit: false })).toBeNull()
    render(<TeamStrip {...props({ teamLimit: null })} />)
    expect(screen.queryByTestId('team-limit')).toBeNull()
  })
})
