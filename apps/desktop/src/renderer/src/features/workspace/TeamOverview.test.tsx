// SOLUSDEV-319 (design D) + SOLUSDEV-328 (A2, fills the window): the active team's overview — a
// header bar with plan, size and a role-aware Invite, then full-height columns picked from the
// overview's own width: projects │ team on a split Home, projects │ current project │ team on a wide
// one, all stacked on a narrow one. "You in <team>" and "Work with others" are retired.
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
    projects: (layout) => <div>projects table ({layout})</div>,
    projectColumn: <div>project column</div>,
    menu: {
      onJoin: vi.fn(),
      onNewTeam: vi.fn(),
      onInvite: vi.fn(),
      onRename: vi.fn(),
      onLeave: vi.fn(),
      onDelete: vi.fn()
    },
    onInvite: vi.fn(),
    onManageMembers: vi.fn(),
    ...overrides
  }
}

describe('TeamOverview — header', () => {
  it('heads the overview with the team, its plan and size', () => {
    render(<TeamOverview {...props()} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Arm Lab' })).toBeInTheDocument()
    expect(screen.getByText('ACTIVE · 3 MEMBERS')).toBeInTheDocument()
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

  it('no longer carries the You-in or Work-with-others cards', () => {
    render(<TeamOverview {...props()} />)
    expect(screen.queryByRole('region', { name: 'You in Arm Lab' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Work with others' })).toBeNull()
  })
})

describe('TeamOverview — columns from its own width', () => {
  it('splits into projects and the team column, the project column held back', () => {
    render(<TeamOverview {...props({ layout: 'split' })} />)
    expect(screen.getByTestId('team-overview')).toHaveAttribute('data-layout', 'split')
    expect(screen.getByText('projects table (split)')).toBeInTheDocument()
    expect(screen.queryByText('project column')).toBeNull()
    expect(screen.getByRole('list', { name: 'Members' })).toBeInTheDocument()
  })

  it('adds the current project as its own column when wide, between projects and team', () => {
    render(<TeamOverview {...props({ layout: 'wide' })} />)
    const columns = within(screen.getByTestId('team-overview-body')).getAllByTestId(/^home-col-/)
    expect(columns.map((c) => c.dataset.testid)).toEqual([
      'home-col-projects',
      'home-col-project',
      'home-col-team'
    ])
    expect(screen.getByText('projects table (wide)')).toBeInTheDocument()
    expect(screen.getByText('project column')).toBeInTheDocument()
  })

  it('stacks projects over the team column when narrow, as one scroll', () => {
    render(<TeamOverview {...props({ layout: 'stack' })} />)
    const overview = screen.getByTestId('team-overview')
    expect(overview).toHaveAttribute('data-layout', 'stack')
    expect(overview).toHaveStyle({ overflowY: 'auto' })
    expect(screen.queryByText('project column')).toBeNull()
  })

  it('lets each column scroll on its own when split or wide; the team column via its sections', () => {
    render(<TeamOverview {...props({ layout: 'wide' })} />)
    for (const id of ['home-col-projects', 'home-col-project'])
      expect(screen.getByTestId(id)).toHaveStyle({ overflowY: 'auto' })
    expect(screen.getByTestId('home-col-team')).toHaveStyle({ overflow: 'hidden' })
    expect(screen.getByTestId('team-column')).toHaveAttribute('data-fit', 'fitted')
  })

  it('hands the team column the stacked fit when narrow', () => {
    render(<TeamOverview {...props({ layout: 'stack' })} />)
    expect(screen.getByTestId('team-column')).toHaveAttribute('data-fit', 'stacked')
  })
})

describe('TeamOverview — the personal workspace', () => {
  it('is only mine: no members, its feed kept', () => {
    const p = props({ team: PERSONAL, homeTeam: homeTeam({ members: [ME], invites: [] }) })
    render(<TeamOverview {...p} />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'Personal workspace' })
    ).toBeInTheDocument()
    expect(screen.getByText('ONLY YOU')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Team activity' })).toBeInTheDocument()
  })
})
