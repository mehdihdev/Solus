// SOLUSDEV-319 (multi-team Home, design D): the active team's overview — header with plan,
// size and a role-aware Invite, the projects (passed in), a members preview, "You in <team>",
// the team's pending invites for managers; and the personal workspace's own variant.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { InviteApi, TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import type { HomeTeam } from './useHomeTeam'
import { TeamOverview, type TeamOverviewProps } from './TeamOverview'

const ARM: TeamSummary = {
  team_id: 't-arm',
  name: 'Arm Lab',
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
}
const PERSONAL: TeamSummary = { ...ARM, team_id: 't-me', name: 'Mehdi', is_personal: true }

function member(n: number, role: TeamMemberApi['role'] = 'member'): TeamMemberApi {
  return {
    user_id: `u${n}`,
    email: `m${n}@example.com`,
    name: `Member ${n}`,
    role,
    joined_at: new Date(Date.now() - 3 * 86_400_000).toISOString()
  }
}
const ME: TeamMemberApi = { ...member(0, 'owner'), user_id: 'me', name: 'Mehdi H' }
const INVITE: InviteApi = {
  id: 'i1',
  team_id: 't-arm',
  email: 'sam@example.com',
  role: 'member',
  status: 'pending',
  created_at: new Date(Date.now() - 86_400_000).toISOString(),
  expires_at: ''
} as InviteApi

function homeTeam(overrides: Partial<HomeTeam> = {}): HomeTeam {
  return {
    status: 'ready',
    detail: null,
    members: [ME, member(1), member(2, 'viewer')],
    invites: [INVITE],
    activity: [],
    activityTotal: 0,
    activityHasMore: false,
    myRole: 'owner',
    teamLimit: null,
    actions: {} as HomeTeam['actions'],
    ...overrides
  }
}

function props(overrides: Partial<TeamOverviewProps> = {}): TeamOverviewProps {
  return {
    team: ARM,
    homeTeam: homeTeam(),
    meId: 'me',
    projectCount: 2,
    projects: <div>projects table</div>,
    menu: {
      onJoin: vi.fn(),
      onNewTeam: vi.fn(),
      onInvite: vi.fn(),
      onRename: vi.fn(),
      onLeave: vi.fn(),
      onDelete: vi.fn()
    },
    onInvite: vi.fn(),
    onJoin: vi.fn(),
    onManageMembers: vi.fn(),
    ...overrides
  }
}

describe('TeamOverview — a team', () => {
  it('heads the pane with the team, its plan and size, and the projects beneath', () => {
    render(<TeamOverview {...props()} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Arm Lab' })).toBeInTheDocument()
    expect(screen.getByText('ACTIVE · 3 MEMBERS')).toBeInTheDocument()
    expect(screen.getByText('projects table')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Team menu' })).toBeInTheDocument()
  })

  it('offers managers Invite to <team>', async () => {
    const p = props()
    render(<TeamOverview {...p} />)
    await userEvent.click(screen.getByRole('button', { name: 'Invite to Arm Lab' }))
    expect(p.onInvite).toHaveBeenCalled()
  })

  it('tells a member who to ask instead of offering Invite', () => {
    render(
      <TeamOverview
        {...props({ team: { ...ARM, role: 'member' }, homeTeam: homeTeam({ myRole: 'member' }) })}
      />
    )
    expect(screen.queryByRole('button', { name: /^Invite/ })).toBeNull()
    expect(
      screen.getByText("You're a Member here · ask an owner or admin to invite")
    ).toBeInTheDocument()
  })

  it('previews the members with their roles and links to the full roster', async () => {
    const p = props({
      homeTeam: homeTeam({ members: [ME, ...[1, 2, 3, 4, 5, 6, 7].map((n) => member(n))] })
    })
    render(<TeamOverview {...p} />)
    const list = screen.getByRole('list', { name: 'Members' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(6)
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('Mehdi H')
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('Owner')
    await userEvent.click(screen.getByRole('button', { name: 'All 8 members and invites' }))
    expect(p.onManageMembers).toHaveBeenCalled()
  })

  it('says where I stand in the team', () => {
    render(<TeamOverview {...props()} />)
    const you = screen.getByRole('region', { name: 'You in Arm Lab' })
    expect(you).toHaveTextContent('Owner')
    expect(you).toHaveTextContent('3d ago')
    expect(you).toHaveTextContent('2')
  })

  it('lists pending invites for managers only', () => {
    const { unmount } = render(<TeamOverview {...props()} />)
    expect(screen.getByRole('region', { name: 'Pending invites' })).toHaveTextContent(
      'sam@example.com'
    )
    unmount()
    render(
      <TeamOverview
        {...props({ team: { ...ARM, role: 'member' }, homeTeam: homeTeam({ myRole: 'member' }) })}
      />
    )
    expect(screen.queryByRole('region', { name: 'Pending invites' })).toBeNull()
  })

  it('waits for the roster without inventing one', () => {
    render(<TeamOverview {...props({ homeTeam: homeTeam({ status: 'loading', members: [] }) })} />)
    expect(screen.getByText('Loading the team…')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull()
  })
})

describe('TeamOverview — the personal workspace', () => {
  it('is only mine: no members, and a way to work with others', async () => {
    const p = props({ team: PERSONAL, homeTeam: homeTeam({ members: [ME], invites: [] }) })
    render(<TeamOverview {...p} />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'Personal workspace' })
    ).toBeInTheDocument()
    expect(screen.getByText('ONLY YOU')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull()
    const card = screen.getByRole('region', { name: 'Work with others' })
    expect(card).toHaveTextContent('your personal workspace stays yours alone')
    await userEvent.click(within(card).getByRole('button', { name: 'Invite a teammate' }))
    await userEvent.click(within(card).getByRole('button', { name: 'Join with an invite code' }))
    expect(p.onInvite).toHaveBeenCalled()
    expect(p.onJoin).toHaveBeenCalled()
  })
})
