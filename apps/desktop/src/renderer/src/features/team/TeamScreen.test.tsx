// Team screen (SOLUSDEV-152): the prototype's fabricated roster/activity demo
// is gone. Linked workspaces render live API data; offline (dev bypass) shows
// an honest sign-in state instead of a mock team.
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamScreen } from './TeamScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    getTeamDetail: vi.fn(),
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    listActivityPage: vi.fn(),
    createInvite: vi.fn(),
    listProjects: vi.fn(),
    createTeam: vi.fn(),
    createProject: vi.fn(),
    acceptInvite: vi.fn()
  }
})

const LIVE_PROJECT: resources.Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover Nav',
  description: null,
  archived_at: null,
  created_at: '2026-07-02T00:00:00Z',
  updated_at: '2026-07-02T00:00:00Z'
}

function meWithTeams(teams: resources.TeamSummary[]): resources.Me {
  return {
    id: 'u1',
    email: 'maya@example.dev',
    name: 'Maya K',
    avatar_url: null,
    created_at: '',
    teams
  }
}

const SOLO_TEAM: resources.TeamSummary = {
  team_id: 't1',
  name: 'Vector Robotics',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}

afterEach(() => {
  vi.useRealTimers()
  useWorkspaceStore.getState().reset()
})

describe('TeamScreen — offline (dev bypass)', () => {
  it('shows an honest sign-in state instead of a mock roster', () => {
    render(<TeamScreen />)
    expect(screen.getByText(/Sign in to Solus to see your team/)).toBeInTheDocument()
  })

  it('renders no fabricated members, activity, or invite controls', () => {
    const { container } = render(<TeamScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/Maya Krishnan|Jonas Weber|Marcus Hale/)
    expect(text).not.toMatch(/strider/i)
    expect(text).not.toMatch(/AFFECTS YOUR CODE/)
    expect(text).not.toMatch(/swapped U4/)
    expect(screen.queryByText('Invite teammate')).not.toBeInTheDocument()
  })
})

const LIVE_TEAM: resources.TeamDetail = {
  id: 't1',
  name: 'Vector Robotics',
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
    email: 'maya@example.dev',
    name: 'Maya K',
    role: 'owner',
    joined_at: '2026-07-01T00:00:00Z'
  },
  {
    user_id: 'u2',
    email: 'noor@example.dev',
    name: 'Noor A',
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
    payload: { email: 'noor@example.dev' },
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
    vi.mocked(resources.listProjects).mockResolvedValue([LIVE_PROJECT])
  })

  it('renders the real team name, roster, and humanized activity', async () => {
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    expect(screen.getByText('Maya K')).toBeInTheDocument()
    expect(screen.getByText('noor@example.dev')).toBeInTheDocument()
    expect(screen.getByText(/joined the team/)).toBeInTheDocument()
  })

  it('sends a real invite and reveals the one-time token', async () => {
    vi.mocked(resources.createInvite).mockResolvedValue({
      id: 'i1',
      team_id: 't1',
      email: 'new@example.dev',
      role: 'member',
      status: 'pending',
      created_at: '',
      expires_at: '',
      token: 'join-tok-once'
    })
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Invite teammate'))
    await userEvent.type(screen.getByPlaceholderText('teammate@team.dev'), 'new@example.dev')
    await userEvent.click(screen.getByText('Send invite'))
    await waitFor(() => expect(screen.getByText('join-tok-once')).toBeInTheDocument())
    expect(vi.mocked(resources.createInvite)).toHaveBeenCalledWith('t1', {
      email: 'new@example.dev',
      role: 'member'
    })
  })

  it('offers role management to an owner', async () => {
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    // The member (not the owner) gets a role selector.
    expect(screen.getByLabelText('Role for noor@example.dev')).toBeInTheDocument()
  })

  it('hides the team switcher when the user belongs to one team', async () => {
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
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
    render(<TeamScreen />)
    const switcher = await screen.findByLabelText('Switch team')
    await userEvent.selectOptions(switcher, 't2')
    expect(useWorkspaceStore.getState().teamId).toBe('t2')
  })

  it('lists the active team’s projects', async () => {
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Rover Nav')).toBeInTheDocument())
    expect(screen.getByText('PROJECTS')).toBeInTheDocument()
  })

  it('creates a team from the Team page and switches to it', async () => {
    vi.mocked(resources.createTeam).mockResolvedValue({ ...LIVE_TEAM, id: 't9', name: 'New Co' })
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    await userEvent.click(screen.getByText('New team'))
    await userEvent.type(screen.getByLabelText('Team name'), 'New Co')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(vi.mocked(resources.createTeam)).toHaveBeenCalledWith('New Co'))
    await waitFor(() => expect(useWorkspaceStore.getState().teamId).toBe('t9'))
  })

  it('joins a team with an invite token from the Team page', async () => {
    vi.mocked(resources.acceptInvite).mockResolvedValue({ team_id: 't7', role: 'member' })
    render(<TeamScreen />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Join team'))
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok-xyz')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    await waitFor(() => expect(vi.mocked(resources.acceptInvite)).toHaveBeenCalledWith('tok-xyz'))
    await waitFor(() => expect(useWorkspaceStore.getState().teamId).toBe('t7'))
  })

  it('creates a project and opens it', async () => {
    const onOpen = vi.fn()
    vi.mocked(resources.createProject).mockResolvedValue({ ...LIVE_PROJECT, id: 'p2', name: 'Arm' })
    render(<TeamScreen onOpenProject={onOpen} />)
    await waitFor(() => expect(screen.getByText('Vector Robotics')).toBeInTheDocument())
    await userEvent.click(screen.getByText('New project'))
    await userEvent.type(screen.getByLabelText('Project name'), 'Arm')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() =>
      expect(vi.mocked(resources.createProject)).toHaveBeenCalledWith('t1', { name: 'Arm' })
    )
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith({ id: 'p2', name: 'Arm' }))
  })

  it('opens an existing project when its row is clicked', async () => {
    const onOpen = vi.fn()
    render(<TeamScreen onOpenProject={onOpen} />)
    await waitFor(() => expect(screen.getByText('Rover Nav')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Rover Nav'))
    expect(onOpen).toHaveBeenCalledWith({ id: 'p1', name: 'Rover Nav' })
  })
})

describe('TeamScreen — a team that is gone is not an outage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Signed in: `useOfflineReason` only reports `api_unreachable` for an
    // authenticated user — signed out, every failure is "sign in" instead.
    useAuthStore.setState({ status: 'authenticated', user: { email: 'maya@example.dev' } })
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getMe).mockResolvedValue(meWithTeams([SOLO_TEAM]))
    vi.mocked(resources.listProjects).mockResolvedValue([])
  })

  it('does not tell the user to go restart a backend that is answering', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(
      new ApiError(404, 'not_found', 'No such team')
    )
    render(<TeamScreen />)
    // The exact sentence that sent a real user chasing a healthy API.
    await waitFor(() =>
      expect(screen.queryByText(/Make sure the backend is running/)).not.toBeInTheDocument()
    )
    expect(screen.getByText(/no longer exists|no longer have access/i)).toBeInTheDocument()
  })

  it('still says the API is unreachable when it genuinely is', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new TypeError('Failed to fetch'))
    render(<TeamScreen />)
    await waitFor(() =>
      expect(screen.getByText(/Make sure the backend is running/)).toBeInTheDocument()
    )
  })
})
