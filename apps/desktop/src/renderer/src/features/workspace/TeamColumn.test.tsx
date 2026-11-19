// SOLUSDEV-328 — the overview's full-height team column: every member (role and when they joined),
// the pending invites for managers, then the team's activity feed filling the rest, paging older
// rows on request. The personal workspace has no roster, only its feed.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ActivityApi, InviteApi, TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import type { HomeTeam } from './useHomeTeam'
import { TeamColumn } from './TeamColumn'

const ARM: TeamSummary = {
  team_id: 't-arm',
  name: 'Arm Lab',
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
}

function member(n: number, role: TeamMemberApi['role'] = 'member'): TeamMemberApi {
  return {
    user_id: `u${n}`,
    email: `m${n}@example.com`,
    name: `Member ${n}`,
    role,
    joined_at: new Date(Date.now() - 3 * 86_400_000).toISOString()
  }
}
const INVITE = {
  id: 'i1',
  team_id: 't-arm',
  email: 'sam@example.com',
  role: 'member',
  status: 'pending',
  created_at: new Date(Date.now() - 86_400_000).toISOString(),
  expires_at: ''
} as InviteApi
function row(n: number): ActivityApi {
  return {
    id: `a${n}`,
    team_id: 't-arm',
    actor_id: 'u1',
    type: 'project.created',
    payload: { name: `Project ${n}` },
    created_at: new Date(Date.now() - n * 3_600_000).toISOString()
  } as unknown as ActivityApi
}

function homeTeam(overrides: Partial<HomeTeam> = {}): HomeTeam {
  return {
    status: 'ready',
    detail: null,
    members: [member(0, 'owner'), member(1), member(2, 'viewer')],
    invites: [INVITE],
    activity: [row(1), row(2)],
    activityTotal: 2,
    activityHasMore: false,
    myRole: 'owner',
    teamLimit: null,
    actions: {
      loadMoreActivity: vi.fn().mockResolvedValue(undefined)
    } as unknown as HomeTeam['actions'],
    ...overrides
  }
}

describe('TeamColumn', () => {
  it('lists every member with their role and when they joined, past the old preview of six', async () => {
    const onManage = vi.fn()
    const many = [member(0, 'owner'), ...[1, 2, 3, 4, 5, 6, 7].map((n) => member(n))]
    render(
      <TeamColumn team={ARM} homeTeam={homeTeam({ members: many })} onManageMembers={onManage} />
    )
    const list = screen.getByRole('list', { name: 'Members' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(8)
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('Member 0')
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('Owner · joined 3d ago')
    await userEvent.click(screen.getByRole('button', { name: 'All 8 members and invites' }))
    expect(onManage).toHaveBeenCalled()
  })

  it('shows pending invites to managers only', () => {
    const { unmount } = render(
      <TeamColumn team={ARM} homeTeam={homeTeam()} onManageMembers={vi.fn()} />
    )
    expect(screen.getByRole('region', { name: 'Pending invites' })).toHaveTextContent(
      'sam@example.com'
    )
    unmount()
    render(
      <TeamColumn
        team={{ ...ARM, role: 'member' }}
        homeTeam={homeTeam({ myRole: 'member' })}
        onManageMembers={vi.fn()}
      />
    )
    expect(screen.queryByRole('region', { name: 'Pending invites' })).toBeNull()
  })

  it('fills the rest with the team activity feed and loads older rows on request', async () => {
    const team = homeTeam({ activityHasMore: true })
    render(<TeamColumn team={ARM} homeTeam={team} onManageMembers={vi.fn()} />)
    const feed = screen.getByRole('region', { name: 'Team activity' })
    expect(within(feed).getByText(/Project 1/)).toBeInTheDocument()
    await userEvent.click(within(feed).getByRole('button', { name: 'Load older activity' }))
    expect(team.actions.loadMoreActivity).toHaveBeenCalled()
  })

  it('says so when there is no activity, and offers no paging', () => {
    render(
      <TeamColumn
        team={ARM}
        homeTeam={homeTeam({ activity: [], activityTotal: 0 })}
        onManageMembers={vi.fn()}
      />
    )
    expect(screen.getByText(/No activity yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load older activity' })).toBeNull()
  })

  it('waits for the roster without inventing one', () => {
    render(
      <TeamColumn
        team={ARM}
        homeTeam={homeTeam({ status: 'loading', members: [], activity: [] })}
        onManageMembers={vi.fn()}
      />
    )
    expect(screen.getByText('Loading the team…')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull()
  })
})

describe('TeamColumn — fit (column vs stacked)', () => {
  it('as its own column, caps members at 40% and lets the feed take the rest, each scrolling', () => {
    render(<TeamColumn team={ARM} homeTeam={homeTeam()} onManageMembers={vi.fn()} />)
    expect(screen.getByTestId('team-column')).toHaveStyle({ height: '100%' })
    expect(screen.getByRole('region', { name: 'Team members' })).toHaveStyle({
      maxHeight: '40%',
      overflowY: 'auto'
    })
    expect(screen.getByRole('region', { name: 'Team activity' })).toHaveStyle({
      flexGrow: '1',
      overflowY: 'auto'
    })
  })

  it('stacked under the projects, lets every section take its natural height', () => {
    render(<TeamColumn team={ARM} homeTeam={homeTeam()} onManageMembers={vi.fn()} stacked />)
    expect(screen.getByTestId('team-column')).toHaveAttribute('data-fit', 'stacked')
    expect(screen.getByRole('region', { name: 'Team members' })).not.toHaveStyle({
      maxHeight: '40%'
    })
  })

  it('keeps only the feed on the personal workspace', () => {
    render(
      <TeamColumn
        team={{ ...ARM, is_personal: true }}
        homeTeam={homeTeam({ members: [member(0, 'owner')], invites: [] })}
        onManageMembers={vi.fn()}
      />
    )
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Team activity' })).toBeInTheDocument()
  })
})
