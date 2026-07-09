import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamScreen } from './TeamScreen'
import { TEAM, ACTIVITY } from '../workspace/workspaceData.constants'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    getTeamDetail: vi.fn(),
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    listActivityPage: vi.fn(),
    createInvite: vi.fn()
  }
})

function meWithTeams(teams: resources.TeamSummary[]): resources.Me {
  return {
    id: 'u1',
    email: 'maya@strider.dev',
    name: 'Maya K',
    avatar_url: null,
    created_at: '',
    teams
  }
}

const SOLO_TEAM: resources.TeamSummary = {
  team_id: 't1',
  name: 'Strider Robotics',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}

afterEach(() => {
  vi.useRealTimers()
  useWorkspaceStore.getState().reset()
})

describe('TeamScreen — roster', () => {
  it('renders all four members with their roles', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    for (const member of TEAM) {
      expect(screen.getByText(member.name)).toBeInTheDocument()
      expect(screen.getByText(`● ${member.role.toUpperCase()}`)).toBeInTheDocument()
      expect(screen.getByText(member.email)).toBeInTheDocument()
    }
  })

  it('marks the current user with a YOU badge', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    expect(screen.getByText('(you)')).toBeInTheDocument()
  })

  it('shows member last-active times', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    expect(screen.getByText('12 min ago')).toBeInTheDocument()
    expect(screen.getByText('1h ago')).toBeInTheDocument()
  })
})

describe('TeamScreen — activity feed', () => {
  it('renders every activity row', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    for (const item of ACTIVITY) {
      expect(screen.getByText(new RegExp(escapeRegExp(item.what)))).toBeInTheDocument()
    }
  })

  it('flags cross-domain rows with an AFFECTS YOUR CODE badge', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    const affected = ACTIVITY.filter((a) => a.affects).length
    expect(screen.getAllByText('AFFECTS YOUR CODE')).toHaveLength(affected)
  })

  it('opens the linked alert when an affects-row is clicked', async () => {
    const onOpenAlert = vi.fn()
    render(<TeamScreen onOpenAlert={onOpenAlert} />)
    await userEvent.click(screen.getByText(/swapped U4: DRV8833 → DRV8316C/))
    expect(onOpenAlert).toHaveBeenCalledWith('a1')
  })

  it('does nothing when a row without an alert is clicked', async () => {
    const onOpenAlert = vi.fn()
    render(<TeamScreen onOpenAlert={onOpenAlert} />)
    await userEvent.click(screen.getByText(/tuned standing-gait stride/))
    expect(onOpenAlert).not.toHaveBeenCalled()
  })
})

describe('TeamScreen — invite flow (visual only)', () => {
  it('opens and closes the invite modal', async () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await userEvent.click(screen.getByText('Invite teammate'))
    expect(screen.getByPlaceholderText('teammate@team.dev')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByPlaceholderText('teammate@team.dev')).not.toBeInTheDocument()
  })

  it('ignores an invalid email', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    fireEvent.click(screen.getByText('Invite teammate'))
    fireEvent.change(screen.getByPlaceholderText('teammate@team.dev'), {
      target: { value: 'not-an-email' }
    })
    fireEvent.click(screen.getByText('Send invite'))
    // Modal stays open, no pending row appears.
    expect(screen.getByPlaceholderText('teammate@team.dev')).toBeInTheDocument()
    expect(screen.queryByText('INVITE PENDING')).not.toBeInTheDocument()
  })

  it('adds a pending member after sending a valid invite', () => {
    vi.useFakeTimers()
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    fireEvent.click(screen.getByText('Invite teammate'))
    fireEvent.change(screen.getByPlaceholderText('teammate@team.dev'), {
      target: { value: 'new@strider.dev' }
    })
    fireEvent.click(screen.getByText('Send invite'))
    expect(screen.getByText(/Sending…/)).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1200)
    })
    expect(screen.getByText('new@strider.dev')).toBeInTheDocument()
    expect(screen.getByText('INVITE PENDING')).toBeInTheDocument()
    // Modal closed after send.
    expect(screen.queryByPlaceholderText('teammate@team.dev')).not.toBeInTheDocument()
  })
})

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const LIVE_TEAM: resources.TeamDetail = {
  id: 't1',
  name: 'Strider Robotics',
  is_personal: false,
  plan_status: 'trial',
  settings: { notify_project_created: true },
  created_at: '2026-07-01T00:00:00Z',
  member_count: 2,
  role: 'owner'
}
const LIVE_MEMBERS: resources.TeamMemberApi[] = [
  {
    user_id: 'u1',
    email: 'maya@strider.dev',
    name: 'Maya K',
    role: 'owner',
    joined_at: '2026-07-01T00:00:00Z'
  },
  {
    user_id: 'u2',
    email: 'priya@strider.dev',
    name: 'Priya N',
    role: 'member',
    joined_at: '2026-07-02T00:00:00Z'
  }
]
const LIVE_ACTIVITY: resources.ActivityApi[] = [
  {
    id: 'ac1',
    type: 'invite.accepted',
    domain: null,
    actor_id: 'u2',
    project_id: null,
    payload: { email: 'priya@strider.dev' },
    created_at: '2026-07-06T00:00:00Z'
  }
]

describe('TeamScreen — live (API-backed)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getMe).mockResolvedValue(meWithTeams([SOLO_TEAM]))
    vi.mocked(resources.getTeamDetail).mockResolvedValue(LIVE_TEAM)
    vi.mocked(resources.listMembers).mockResolvedValue(LIVE_MEMBERS)
    vi.mocked(resources.listInvites).mockResolvedValue([])
    vi.mocked(resources.listActivityPage).mockResolvedValue({ data: LIVE_ACTIVITY, meta: {} })
  })

  it('renders the real team name, roster, and humanized activity', async () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Strider Robotics')).toBeInTheDocument())
    expect(screen.getByText('Maya K')).toBeInTheDocument()
    expect(screen.getByText('priya@strider.dev')).toBeInTheDocument()
    expect(screen.getByText(/joined the team/)).toBeInTheDocument()
  })

  it('sends a real invite and reveals the one-time token', async () => {
    vi.mocked(resources.createInvite).mockResolvedValue({
      id: 'i1',
      team_id: 't1',
      email: 'new@strider.dev',
      role: 'member',
      status: 'pending',
      created_at: '',
      expires_at: '',
      token: 'join-tok-once'
    })
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Strider Robotics')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Invite teammate'))
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@strider.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await waitFor(() => expect(screen.getByText('join-tok-once')).toBeInTheDocument())
    expect(vi.mocked(resources.createInvite)).toHaveBeenCalledWith('t1', {
      email: 'new@strider.dev',
      role: 'member'
    })
  })

  it('offers role management to an owner', async () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Strider Robotics')).toBeInTheDocument())
    // The member (not the owner) gets a role selector.
    expect(screen.getByLabelText('Role for priya@strider.dev')).toBeInTheDocument()
  })

  it('hides the team switcher when the user belongs to one team', async () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Strider Robotics')).toBeInTheDocument())
    expect(screen.queryByLabelText('Switch team')).not.toBeInTheDocument()
  })

  it('switches the active team via the switcher', async () => {
    vi.mocked(resources.getMe).mockResolvedValue(
      meWithTeams([
        SOLO_TEAM,
        {
          team_id: 't2',
          name: 'Rocket Lab',
          role: 'member',
          is_personal: false,
          plan_status: 'active',
          trial_ends_at: ''
        }
      ])
    )
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    const switcher = await screen.findByLabelText('Switch team')
    await userEvent.selectOptions(switcher, 't2')
    expect(useWorkspaceStore.getState().teamId).toBe('t2')
  })
})
