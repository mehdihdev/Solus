import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamSection } from './TeamSection'
import type { TeamData } from '../../team/useTeamData'
import type { TeamRole } from '../../../lib/api/resources'

function teamData(overrides: Partial<TeamData> = {}, role: TeamRole = 'owner'): TeamData {
  return {
    status: 'ready',
    team: {
      id: 't1',
      name: 'Strider Robotics',
      is_personal: false,
      plan_status: 'trial',
      settings: { notify_project_created: true },
      created_at: '',
      member_count: 2,
      role
    },
    members: [],
    invites: [],
    activity: [],
    activityHasMore: false,
    activityTotal: 0,
    loadMoreActivity: vi.fn(async () => undefined),
    teams: [],
    myRole: role,
    actions: {
      invite: vi.fn(async () => null),
      revoke: vi.fn(async () => true),
      changeRole: vi.fn(async () => true),
      remove: vi.fn(async () => true),
      updateTeam: vi.fn(async () => true),
      deleteTeam: vi.fn(async () => true),
      switchTeam: vi.fn(),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  } as TeamData
}

describe('TeamSection', () => {
  it('renames the team through the action', async () => {
    const updateTeam = vi.fn(async () => true)
    const team = teamData({ actions: { ...teamData().actions, updateTeam } })
    render(<TeamSection team={team} />)
    const input = screen.getByLabelText('Team name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Rocket Lab')
    await userEvent.click(screen.getByText('Save'))
    expect(updateTeam).toHaveBeenCalledWith({ name: 'Rocket Lab' })
  })

  it('toggles the new-project notification', async () => {
    const updateTeam = vi.fn(async () => true)
    const team = teamData({ actions: { ...teamData().actions, updateTeam } })
    render(<TeamSection team={team} />)
    await userEvent.click(screen.getByText('Off'))
    expect(updateTeam).toHaveBeenCalledWith({ settings: { notify_project_created: false } })
  })

  it('shows the team name read-only to a member', () => {
    render(<TeamSection team={teamData({}, 'member')} />)
    expect(screen.queryByLabelText('Team name')).not.toBeInTheDocument()
    expect(screen.getByText('Strider Robotics')).toBeInTheDocument()
  })

  it('deletes the team after confirmation (owner, non-personal only)', async () => {
    const deleteTeam = vi.fn(async () => true)
    const team = teamData({ actions: { ...teamData().actions, deleteTeam } })
    render(<TeamSection team={team} />)
    await userEvent.click(screen.getByText('Delete team'))
    await userEvent.click(screen.getByText('Confirm delete'))
    expect(deleteTeam).toHaveBeenCalled()
  })

  it('hides the danger zone for a personal workspace', () => {
    const team = teamData({
      team: {
        id: 't1',
        name: 'Personal',
        is_personal: true,
        plan_status: 'trial',
        settings: { notify_project_created: true },
        created_at: '',
        member_count: 1,
        role: 'owner'
      }
    })
    render(<TeamSection team={team} />)
    expect(screen.queryByText('Delete team')).not.toBeInTheDocument()
  })
})
