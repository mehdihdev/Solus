// SOLUSDEV-319 (multi-team Home, design D): the team rail — every team I belong to with my
// role and its size, the active one marked, my personal workspace last, switching in one
// click, Create / Join, and the invitations waiting for me with Accept / Decline.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TeamSummary } from '../../lib/api/resources'
import type { MyInvite } from '../../lib/api/resources.myInvites'
import { AT_LIMIT_MESSAGE } from './teamLabels'
import { TeamRail, type TeamRailProps } from './TeamRail'
import type { MyInvites } from './useMyInvites'

const PERSONAL: TeamSummary = {
  team_id: 't-me',
  name: 'Mehdi',
  role: 'owner',
  is_personal: true,
  plan_status: 'trial',
  trial_ends_at: ''
}
const ARM: TeamSummary = { ...PERSONAL, team_id: 't-arm', name: 'Arm Lab', is_personal: false }
const FSAE: TeamSummary = {
  ...ARM,
  team_id: 't-fsae',
  name: 'FSAE Robotics',
  role: 'member'
}
const BRACKET: MyInvite = {
  id: 'inv-1',
  team: { id: 't-9', name: 'Bracket Labs' },
  role: 'member',
  invited_by: { name: 'Lena V' },
  created_at: '2026-11-05T10:00:00Z',
  expires_at: '2026-11-12T10:00:00Z'
}

function invites(overrides: Partial<MyInvites> = {}): MyInvites {
  return {
    status: 'ready',
    invites: [],
    busyId: null,
    notice: null,
    accept: vi.fn(async () => undefined),
    decline: vi.fn(async () => undefined),
    ...overrides
  }
}

function props(overrides: Partial<TeamRailProps> = {}): TeamRailProps {
  return {
    greeting: 'Welcome back, Mehdi',
    teams: [PERSONAL, ARM, FSAE],
    activeTeamId: 't-arm',
    sizes: { 't-arm': 4, 't-fsae': 12, 't-me': 1 },
    invites: invites(),
    teamLimit: null,
    onSwitch: vi.fn(),
    onNewTeam: vi.fn(),
    onJoin: vi.fn(),
    ...overrides
  }
}

const teamList = (): HTMLElement => screen.getByRole('list', { name: 'Your teams' })

describe('TeamRail', () => {
  it('lists every team with my role and its size, personal workspace last', () => {
    render(<TeamRail {...props()} />)
    const rows = within(teamList()).getAllByRole('button')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Arm Lab'),
      expect.stringContaining('FSAE Robotics'),
      expect.stringContaining('Personal workspace')
    ])
    expect(rows[0]).toHaveTextContent('Owner · 4 members')
    expect(rows[1]).toHaveTextContent('Member · 12 members')
    expect(rows[2]).toHaveTextContent('Only you')
  })

  it('marks the active team and switches to another in one click', async () => {
    const p = props()
    render(<TeamRail {...p} />)
    const active = within(teamList()).getByRole('button', { name: /Arm Lab/ })
    expect(active).toHaveAttribute('aria-current', 'true')
    await userEvent.click(within(teamList()).getByRole('button', { name: /FSAE Robotics/ }))
    expect(p.onSwitch).toHaveBeenCalledWith('t-fsae')
  })

  it('leaves out a size that is not known yet', () => {
    render(<TeamRail {...props({ sizes: {} })} />)
    const row = within(teamList()).getByRole('button', { name: /FSAE Robotics/ })
    expect(row).toHaveTextContent('Member')
    expect(row).not.toHaveTextContent('members')
  })

  it('offers Create a team and Join with an invite code', async () => {
    const p = props()
    render(<TeamRail {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Create a team' }))
    await userEvent.click(screen.getByRole('button', { name: 'Join with an invite code' }))
    expect(p.onNewTeam).toHaveBeenCalled()
    expect(p.onJoin).toHaveBeenCalled()
  })

  it('shows each invitation with who sent it, and accepts or declines it', async () => {
    const mine = invites({ invites: [BRACKET] })
    render(<TeamRail {...props({ invites: mine })} />)
    const card = screen.getByRole('region', { name: 'Invitations' })
    expect(card).toHaveTextContent('Bracket Labs')
    expect(card).toHaveTextContent('Lena V invited you as a Member')
    await userEvent.click(
      within(card).getByRole('button', { name: 'Accept invite to Bracket Labs' })
    )
    await userEvent.click(
      within(card).getByRole('button', { name: 'Decline invite to Bracket Labs' })
    )
    expect(mine.accept).toHaveBeenCalledWith('inv-1')
    expect(mine.decline).toHaveBeenCalledWith('inv-1')
  })

  it('disables an invitation while its answer is in flight', () => {
    render(<TeamRail {...props({ invites: invites({ invites: [BRACKET], busyId: 'inv-1' }) })} />)
    const card = screen.getByRole('region', { name: 'Invitations' })
    for (const button of within(card).getAllByRole('button')) expect(button).toBeDisabled()
  })

  it('has no invitations section when nothing is waiting', () => {
    render(<TeamRail {...props()} />)
    expect(screen.queryByRole('region', { name: 'Invitations' })).toBeNull()
  })

  it('asks for a verified email instead of listing invitations', () => {
    render(<TeamRail {...props({ invites: invites({ status: 'unverified' }) })} />)
    expect(screen.getByRole('region', { name: 'Invitations' })).toHaveTextContent(
      'Verify your email to see the invitations sent to it.'
    )
  })

  it('names a refusal: the plan limit, or an invite that closed meanwhile', () => {
    const { unmount } = render(
      <TeamRail
        {...props({
          invites: invites({
            invites: [BRACKET],
            notice: { inviteId: 'inv-1', refusal: 'at_limit' }
          })
        })}
      />
    )
    expect(screen.getByRole('note')).toHaveTextContent(AT_LIMIT_MESSAGE)
    unmount()
    render(
      <TeamRail
        {...props({ invites: invites({ notice: { inviteId: 'inv-1', refusal: 'gone' } }) })}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('That invitation is no longer open.')
  })
})
