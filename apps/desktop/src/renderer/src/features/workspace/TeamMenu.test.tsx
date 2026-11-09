// SOLUSDEV-244 / HOME H5 (on the team overview since SOLUSDEV-319): the active team's ⋯
// menu — role-gated actions, never leave/delete on the personal workspace — and the plan
// limit stated with its upgrade path.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TeamSummary } from '../../lib/api/resources'
import { AT_LIMIT_MESSAGE, teamLimitText } from './teamLabels'
import { TeamLimitLine, TeamMenu, type TeamMenuProps } from './TeamMenu'

const PERSONAL: TeamSummary = {
  team_id: 't-me',
  name: 'Maya',
  role: 'owner',
  is_personal: true,
  plan_status: 'trial',
  trial_ends_at: ''
}
const TEAM: TeamSummary = { ...PERSONAL, team_id: 't1', name: 'Strider', is_personal: false }

function props(overrides: Partial<TeamMenuProps> = {}): TeamMenuProps {
  return {
    team: TEAM,
    myRole: 'owner',
    onJoin: vi.fn(),
    onNewTeam: vi.fn(),
    onInvite: vi.fn(),
    onRename: vi.fn(),
    onLeave: vi.fn(),
    onDelete: vi.fn(),
    ...overrides
  }
}

describe('TeamMenu', () => {
  it('never offers leave or delete on the personal workspace', async () => {
    render(<TeamMenu {...props({ team: PERSONAL })} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Rename team' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Leave team' })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
  })

  it('gates the menu by role: owner deletes, admin renames, member only leaves', async () => {
    const owner = props()
    const first = render(<TeamMenu {...owner} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete team' }))
    expect(owner.onDelete).toHaveBeenCalled()
    first.unmount()

    const second = render(<TeamMenu {...props({ myRole: 'admin' })} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.getByRole('menuitem', { name: 'Rename team' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Leave team' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Delete team' })).toBeNull()
    second.unmount()

    const member = props({ myRole: 'member' })
    render(<TeamMenu {...member} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    expect(screen.queryByRole('menuitem', { name: /invite teammate/i })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: 'Rename team' })).toBeNull()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Leave team' }))
    expect(member.onLeave).toHaveBeenCalled()
  })

  it('offers Invite (managers), Join and New team', async () => {
    const p = props()
    render(<TeamMenu {...p} />)
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

  it('opens leftward from the ⋯ so it stays inside its container', async () => {
    render(<TeamMenu {...props()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Team menu' }))
    const menu = screen.getByRole('menu')
    expect(menu).toHaveStyle({ right: '0px' })
    expect(menu.style.left).toBe('')
  })
})

describe('TeamLimitLine', () => {
  it('states the plan position, and at the limit the upgrade path', async () => {
    const onUpgrade = vi.fn()
    render(
      <TeamLimitLine teamLimit={{ current: 2, max: 2, atLimit: true }} onUpgrade={onUpgrade} />
    )
    expect(screen.getByTestId('team-limit')).toHaveTextContent('2 of 2 collaborative teams')
    expect(screen.getByTestId('team-limit')).toHaveTextContent('personal team never counts')
    expect(screen.getByRole('note')).toHaveTextContent(AT_LIMIT_MESSAGE)
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(onUpgrade).toHaveBeenCalled()
  })

  it('says nothing about a limit that is unknown or unlimited', () => {
    expect(teamLimitText(null)).toBeNull()
    expect(teamLimitText({ current: 5, max: null, atLimit: false })).toBeNull()
    render(<TeamLimitLine teamLimit={null} />)
    expect(screen.queryByTestId('team-limit')).toBeNull()
  })
})
