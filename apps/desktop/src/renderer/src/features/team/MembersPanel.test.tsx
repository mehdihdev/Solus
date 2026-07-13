import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LiveMembers, InviteModal, MembersManager, EMAIL_PATTERN } from './MembersPanel'
import type { TeamData } from './useTeamData'
import type { InviteApi, TeamMemberApi } from '../../lib/api/resources'

const MEMBERS: TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya K', role: 'owner', joined_at: '' },
  { user_id: 'u2', email: 'priya@strider.dev', name: 'Priya N', role: 'member', joined_at: '' }
]
const INVITES: InviteApi[] = [
  {
    id: 'i1',
    team_id: 't1',
    email: 'new@strider.dev',
    role: 'member',
    status: 'pending',
    created_at: '',
    expires_at: ''
  }
]

function stubActions(overrides: Partial<TeamData['actions']> = {}): TeamData['actions'] {
  return {
    invite: vi.fn(async () => null),
    revoke: vi.fn(async () => true),
    changeRole: vi.fn(async () => true),
    remove: vi.fn(async () => true),
    updateTeam: vi.fn(async () => true),
    deleteTeam: vi.fn(async () => true),
    switchTeam: vi.fn(),
    refresh: vi.fn(async () => undefined),
    ...overrides
  } as TeamData['actions']
}

function stubData(overrides: Partial<TeamData> = {}): TeamData {
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
    invites: INVITES,
    activity: [],
    activityHasMore: false,
    loadMoreActivity: vi.fn(async () => undefined),
    teams: [],
    myRole: 'owner',
    actions: stubActions(),
    ...overrides
  } as TeamData
}

describe('EMAIL_PATTERN', () => {
  it('accepts a valid email and rejects malformed input', () => {
    expect(EMAIL_PATTERN.test('a@b.dev')).toBe(true)
    expect(EMAIL_PATTERN.test('not-an-email')).toBe(false)
  })
})

describe('LiveMembers', () => {
  it('renders the roster with each role', () => {
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage={false}
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={vi.fn()}
      />
    )
    expect(screen.getByText('Maya K')).toBeInTheDocument()
    expect(screen.getByText('priya@strider.dev')).toBeInTheDocument()
    expect(screen.getByText('● OWNER')).toBeInTheDocument()
    expect(screen.getByText('● MEMBER')).toBeInTheDocument()
  })

  it('shows role/remove controls to a manager but never for the owner row', () => {
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={vi.fn()}
      />
    )
    // Owner row stays static; the member gets a role selector + remove button.
    expect(screen.getByLabelText('Role for priya@strider.dev')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role for maya@strider.dev')).not.toBeInTheDocument()
  })

  it('changes a role and removes a member through the callbacks', async () => {
    const onChangeRole = vi.fn()
    const onRemove = vi.fn()
    render(
      <LiveMembers
        members={MEMBERS}
        invites={[]}
        myRole="owner"
        canManage
        onChangeRole={onChangeRole}
        onRemove={onRemove}
        onRevoke={vi.fn()}
      />
    )
    await userEvent.selectOptions(screen.getByLabelText('Role for priya@strider.dev'), 'admin')
    expect(onChangeRole).toHaveBeenCalledWith('u2', 'admin')
    await userEvent.click(screen.getByLabelText('Remove priya@strider.dev'))
    expect(onRemove).toHaveBeenCalledWith('u2')
  })

  it('renders pending invites and revokes them when managing', async () => {
    const onRevoke = vi.fn()
    render(
      <LiveMembers
        members={MEMBERS}
        invites={INVITES}
        myRole="owner"
        canManage
        onChangeRole={vi.fn()}
        onRemove={vi.fn()}
        onRevoke={onRevoke}
      />
    )
    expect(screen.getByText('new@strider.dev')).toBeInTheDocument()
    expect(screen.getByText(/INVITE PENDING/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Revoke invite for new@strider.dev'))
    expect(onRevoke).toHaveBeenCalledWith('i1')
  })
})

describe('InviteModal', () => {
  it('rejects an invalid email inline', async () => {
    const onInvite = vi.fn(async () => null)
    render(<InviteModal onClose={vi.fn()} onInvite={onInvite} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'nope')
    await userEvent.click(screen.getByText('Send invite'))
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
    expect(onInvite).not.toHaveBeenCalled()
  })

  it('reveals the one-time token after a successful invite', async () => {
    const onInvite = vi.fn(async () => ({
      id: 'i9',
      team_id: 't1',
      email: 'new@strider.dev',
      role: 'member' as const,
      status: 'pending' as const,
      created_at: '',
      expires_at: '',
      token: 'join-tok-once'
    }))
    render(<InviteModal onClose={vi.fn()} onInvite={onInvite} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@strider.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await waitFor(() => expect(screen.getByText('join-tok-once')).toBeInTheDocument())
  })

  it('surfaces a failure when the invite is rejected', async () => {
    const onInvite = vi.fn(async () => null)
    render(<InviteModal onClose={vi.fn()} onInvite={onInvite} />)
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@strider.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await waitFor(() => expect(screen.getByText(/Could not send the invite/)).toBeInTheDocument())
  })
})

describe('MembersManager', () => {
  it('shows the member and pending counts', () => {
    render(<MembersManager data={stubData()} />)
    expect(screen.getByText('2 members · 1 pending')).toBeInTheDocument()
  })

  it('opens the invite modal for a manager', async () => {
    render(<MembersManager data={stubData()} />)
    await userEvent.click(screen.getByText('Invite teammate'))
    expect(screen.getByPlaceholderText('teammate@team.dev')).toBeInTheDocument()
  })

  it('hides the invite affordance for a viewer', () => {
    render(<MembersManager data={stubData({ myRole: 'viewer' })} />)
    expect(screen.queryByText('Invite teammate')).not.toBeInTheDocument()
  })
})
