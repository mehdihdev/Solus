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
  it('always names the active team; the name is the switcher only with more than one team', () => {
    const { unmount } = render(<TeamStrip {...props()} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.getByText('3 members')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /switch team/i })).toHaveTextContent('Strider')
    expect(screen.queryByRole('combobox')).toBeNull()
    unmount()
    render(<TeamStrip {...props({ teams: [TEAM] })} />)
    expect(screen.getByTestId('team-name')).toHaveTextContent('Strider')
    expect(screen.queryByRole('button', { name: /switch team/i })).toBeNull()
  })

  it('switches team from the title’s menu, marking the active one', async () => {
    const p = props()
    render(<TeamStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: /switch team/i }))
    const items = screen.getAllByRole('menuitemradio')
    expect(items.find((i) => i.getAttribute('aria-checked') === 'true')).toHaveTextContent(
      'Strider'
    )
    await userEvent.click(
      items.find((i) => i.getAttribute('aria-checked') === 'false') as HTMLElement
    )
    expect(p.onSwitch).toHaveBeenCalledWith(
      p.teams.find((t) => t.team_id !== p.team?.team_id)?.team_id
    )
    expect(screen.queryAllByRole('menuitemradio')).toHaveLength(0)
  })

  it('marks the personal workspace and never offers leave or delete on it', async () => {
    render(<TeamStrip {...props({ team: PERSONAL, memberCount: 1 })} />)
    expect(screen.getByText(/personal workspace/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Rename team' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Leave team' })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
  })

})

describe('TeamStrip (continued)', () => {
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
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.queryByRole('menuitem', { name: /invite teammate/i })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Rename team' })).toBeNull()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Leave team' }))
    expect(member.onLeave).toHaveBeenCalled()
  })

  it('offers Invite (managers), Join and New team from the team menu', async () => {
    const p = props()
    render(<TeamStrip {...p} />)
    const pick = async (name: RegExp): Promise<void> => {
      await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
      await userEvent.click(screen.getByRole('menuitem', { name }))
    }
    await pick(/invite teammate/i)
    await pick(/join team/i)
    await pick(/new team/i)
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

  it('opens the team menu leftward from the ⋯ so it stays inside the sidebar', async () => {
    render(<TeamStrip {...props()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    const menu = screen.getByRole('menu')
    expect(menu).toHaveStyle({ right: '0px' })
    expect(menu.style.left).toBe('')
  })
})
