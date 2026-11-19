// SOLUSDEV-328 (design P2): on the project page the team rail folds to an initials strip — every
// team (active marked), create and join, a count when invitations wait, and the two ACCOUNT views
// as icon buttons — so the projects list fits beside the project.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { TeamSummary } from '../../lib/api/resources'
import { TeamRailStrip, type TeamRailStripProps } from './TeamRailStrip'

const ARM: TeamSummary = {
  team_id: 't-arm',
  name: 'Arm Lab',
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
}
const ME: TeamSummary = { ...ARM, team_id: 't-me', name: 'Maya', is_personal: true }
const FSAE: TeamSummary = { ...ARM, team_id: 't-fsae', name: 'FSAE Robotics', role: 'member' }

function props(overrides: Partial<TeamRailStripProps> = {}): TeamRailStripProps {
  return {
    teams: [ME, ARM, FSAE],
    activeTeamId: 't-arm',
    invitations: 0,
    view: 'project',
    onSwitch: vi.fn(),
    onNewTeam: vi.fn(),
    onJoin: vi.fn(),
    onShow: vi.fn(),
    ...overrides
  }
}

const rail = (): HTMLElement => screen.getByRole('complementary', { name: 'Teams' })

describe('TeamRailStrip', () => {
  it('shows every team by initials, collaborative first, the active one current', () => {
    render(<TeamRailStrip {...props()} />)
    const list = within(rail()).getByRole('list', { name: 'Your teams' })
    const buttons = within(list).getAllByRole('button')
    expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Arm Lab',
      'FSAE Robotics',
      'Personal workspace'
    ])
    expect(buttons[0]).toHaveAttribute('aria-current', 'true')
    expect(buttons[0]).toHaveTextContent('AL')
  })

  it('switches team on a click', async () => {
    const p = props()
    render(<TeamRailStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'FSAE Robotics' }))
    expect(p.onSwitch).toHaveBeenCalledWith('t-fsae')
  })

  it('creates or joins a team', async () => {
    const p = props()
    render(<TeamRailStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Create a team' }))
    await userEvent.click(screen.getByRole('button', { name: 'Join with an invite code' }))
    expect(p.onNewTeam).toHaveBeenCalled()
    expect(p.onJoin).toHaveBeenCalled()
  })

  it('counts waiting invitations and opens the overview, where they are answered', async () => {
    const p = props({ invitations: 2 })
    render(<TeamRailStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: '2 invitations waiting' }))
    expect(p.onShow).toHaveBeenCalledWith('team')
  })

  it('offers no invitation button when none wait', () => {
    render(<TeamRailStrip {...props()} />)
    expect(screen.queryByRole('button', { name: /invitation/ })).toBeNull()
  })

  it('keeps the two ACCOUNT views one click away', async () => {
    const p = props()
    render(<TeamRailStrip {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Connected accounts' }))
    await userEvent.click(screen.getByRole('button', { name: 'Team & invites' }))
    expect(p.onShow).toHaveBeenCalledWith('accounts')
    expect(p.onShow).toHaveBeenCalledWith('members')
    expect(screen.getByRole('button', { name: 'Connected accounts' })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
  })
})
