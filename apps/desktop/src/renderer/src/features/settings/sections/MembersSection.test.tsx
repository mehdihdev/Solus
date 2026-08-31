import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MembersSection } from './MembersSection'
import type { TeamData } from '../../team/useTeamData'
import type { TeamMemberApi } from '../../../lib/api/resources'

const MEMBERS: TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya K', role: 'owner', joined_at: '' },
  { user_id: 'u2', email: 'priya@strider.dev', name: 'Priya N', role: 'member', joined_at: '' }
]

function teamData(overrides: Partial<TeamData> = {}): TeamData {
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
      role: 'owner'
    },
    members: MEMBERS,
    invites: [],
    activity: [],
    activityHasMore: false,
    activityTotal: 0,
    loadMoreActivity: vi.fn(async () => undefined),
    teams: [],
    myRole: 'owner',
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

describe('MembersSection', () => {
  it('renders the Members section with the roster and roles', () => {
    render(<MembersSection team={teamData()} />)
    expect(screen.getByText('Members')).toBeInTheDocument()
    expect(screen.getByText('Maya K')).toBeInTheDocument()
    expect(screen.getByText('priya@strider.dev')).toBeInTheDocument()
    expect(screen.getByLabelText('Role for priya@strider.dev')).toBeInTheDocument()
  })

  it('offers the invite affordance to a manager', () => {
    render(<MembersSection team={teamData()} />)
    expect(screen.getByText('Invite teammate')).toBeInTheDocument()
  })
})
