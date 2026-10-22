import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamSection } from './TeamSection'
import { teamData } from '../settings.fixtures'
import { switchWorkspaceTeam } from '../../workspace/teamSwitch'

vi.mock('../../workspace/teamSwitch', () => ({ switchWorkspaceTeam: vi.fn() }))

async function openEditor(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Edit team' }))
}

describe('TeamSection — summary', () => {
  it('says which team, your role and its size, and links to the team page', async () => {
    const onOpenTeam = vi.fn()
    render(<TeamSection team={teamData({}, 'admin')} onOpenTeam={onOpenTeam} />)
    expect(screen.getByText(/Strider Robotics/)).toBeInTheDocument()
    expect(screen.getByText(/Admin/)).toBeInTheDocument()
    expect(screen.getByText(/6 members/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Open team page/ }))
    expect(onOpenTeam).toHaveBeenCalled()
  })

  it('keeps the editing controls folded away until asked for', async () => {
    render(<TeamSection team={teamData()} onOpenTeam={vi.fn()} />)
    expect(screen.queryByLabelText('Team name')).toBeNull()
    expect(screen.getByRole('button', { name: 'Edit team' })).toHaveAttribute(
      'aria-expanded',
      'false'
    )
    await openEditor()
    expect(screen.getByRole('button', { name: 'Edit team' })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
  })
})

describe('TeamSection — all my teams', () => {
  const TEAMS = [
    {
      team_id: 't0',
      name: 'Maya (personal)',
      role: 'owner',
      is_personal: true,
      plan_status: 'trial',
      trial_ends_at: ''
    },
    {
      team_id: 't1',
      name: 'Strider Robotics',
      role: 'owner',
      is_personal: false,
      plan_status: 'trial',
      trial_ends_at: ''
    },
    {
      team_id: 't2',
      name: 'Rocket Lab',
      role: 'member',
      is_personal: false,
      plan_status: 'active',
      trial_ends_at: ''
    }
  ]

  it('lists every team I belong to, marking the current one', () => {
    render(<TeamSection team={teamData({ teams: TEAMS })} onOpenTeam={vi.fn()} />)
    const list = screen.getByRole('list', { name: 'Your teams' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Maya (personal)'),
      expect.stringContaining('Strider Robotics'),
      expect.stringContaining('Rocket Lab')
    ])
    expect(rows[1]).toHaveTextContent('Current')
    expect(rows[2]).toHaveTextContent('Member')
    expect(rows[0]).toHaveTextContent('Personal')
    expect(within(rows[1]).queryByRole('button', { name: /Switch/ })).toBeNull()
  })

  it('switches the active team through the shared choke point', async () => {
    render(<TeamSection team={teamData({ teams: TEAMS })} onOpenTeam={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to Rocket Lab' }))
    expect(switchWorkspaceTeam).toHaveBeenCalledWith('t2', 'settings')
  })

  it('shows no list when I am on a single team', () => {
    render(<TeamSection team={teamData({ teams: [TEAMS[1]] })} onOpenTeam={vi.fn()} />)
    expect(screen.queryByRole('list', { name: 'Your teams' })).toBeNull()
  })
})

describe('TeamSection — editor', () => {
  it('renames the team through the action', async () => {
    const team = teamData()
    render(<TeamSection team={team} onOpenTeam={vi.fn()} />)
    await openEditor()
    const input = screen.getByLabelText('Team name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Rocket Lab')
    await userEvent.click(screen.getByText('Save'))
    expect(team.actions.updateTeam).toHaveBeenCalledWith({ name: 'Rocket Lab' })
  })

  it('toggles the new-project notification', async () => {
    const team = teamData()
    render(<TeamSection team={team} onOpenTeam={vi.fn()} />)
    await openEditor()
    await userEvent.click(screen.getByRole('switch', { name: 'Notify team on new projects' }))
    expect(team.actions.updateTeam).toHaveBeenCalledWith({
      settings: { notify_project_created: false }
    })
  })

  it('shows the team name read-only to a member', async () => {
    render(<TeamSection team={teamData({}, 'member')} onOpenTeam={vi.fn()} />)
    await openEditor()
    expect(screen.queryByLabelText('Team name')).not.toBeInTheDocument()
  })

  it('deletes the team after confirmation (owner, non-personal only)', async () => {
    const team = teamData()
    render(<TeamSection team={team} onOpenTeam={vi.fn()} />)
    await openEditor()
    await userEvent.click(screen.getByText('Delete team'))
    expect(screen.getByText(/every project in it/)).toBeInTheDocument()
    expect(team.actions.deleteTeam).not.toHaveBeenCalled()
    const buttons = screen.getAllByRole('button', { name: 'Delete team' })
    await userEvent.click(buttons[buttons.length - 1])
    expect(team.actions.deleteTeam).toHaveBeenCalled()
  })

  it('hides the danger zone for a personal workspace', async () => {
    const base = teamData()
    const personal = teamData({
      team: { ...base.team!, name: 'Personal', is_personal: true, member_count: 1 }
    })
    render(<TeamSection team={personal} onOpenTeam={vi.fn()} />)
    expect(screen.getByText(/personal workspace/i)).toBeInTheDocument()
    await openEditor()
    expect(screen.queryByText('Delete team')).not.toBeInTheDocument()
  })
})
