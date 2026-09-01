// Team data hook: parallel load, offline fallback, action round-trips.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useTeamData } from './useTeamData'
import { useWorkspaceStore } from '../../store/workspaceStore'
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
    revokeInvite: vi.fn(),
    changeMemberRole: vi.fn(),
    removeMember: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn(),
    listProjects: vi.fn(),
    createTeam: vi.fn(),
    createProject: vi.fn(),
    acceptInvite: vi.fn()
  }
})

const PROJECT: resources.Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover',
  description: null,
  archived_at: null,
  created_at: '2026-07-02T00:00:00Z',
  updated_at: '2026-07-02T00:00:00Z'
}

const TEAM: resources.TeamDetail = {
  id: 't1',
  name: 'Strider Robotics',
  is_personal: false,
  plan_status: 'trial',
  settings: { notify_project_created: true },
  created_at: '2026-07-01T00:00:00Z',
  member_count: 2,
  role: 'owner'
}
const MEMBERS: resources.TeamMemberApi[] = [
  {
    user_id: 'u1',
    email: 'maya@strider.dev',
    name: 'Maya',
    role: 'owner',
    joined_at: '2026-07-01T00:00:00Z'
  },
  {
    user_id: 'u2',
    email: 'noor@example.dev',
    name: 'Noor',
    role: 'member',
    joined_at: '2026-07-02T00:00:00Z'
  }
]

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, teamId: 't1' })
  vi.mocked(resources.getMe).mockResolvedValue({
    id: 'u1',
    email: 'maya@strider.dev',
    name: 'Maya',
    avatar_url: null,
    created_at: '',
    teams: [
      {
        team_id: 't1',
        name: 'Strider',
        role: 'owner',
        is_personal: false,
        plan_status: 'trial',
        trial_ends_at: ''
      }
    ]
  })
  vi.mocked(resources.getTeamDetail).mockResolvedValue(TEAM)
  vi.mocked(resources.listMembers).mockResolvedValue(MEMBERS)
  vi.mocked(resources.listInvites).mockResolvedValue([])
  vi.mocked(resources.listActivityPage).mockResolvedValue({ data: [], meta: {} })
  vi.mocked(resources.listProjects).mockResolvedValue([PROJECT])
})

describe('useTeamData', () => {
  it('loads detail, members, invites, activity for the workspace team', async () => {
    const { result } = renderHook(() => useTeamData())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team?.name).toBe('Strider Robotics')
    expect(result.current.members).toHaveLength(2)
    expect(result.current.myRole).toBe('owner')
  })

  it('degrades to offline when the API is unreachable', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('is offline immediately when the workspace is not linked', async () => {
    useWorkspaceStore.setState({ linked: false, teamId: null })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(resources.getTeamDetail).not.toHaveBeenCalled()
  })

  it('resolves the team via getMe when only linked is set', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: null })
    vi.mocked(resources.getMe).mockResolvedValue({
      id: 'u1',
      email: 'maya@strider.dev',
      name: null,
      avatar_url: null,
      created_at: '',
      teams: [
        {
          team_id: 't9',
          name: 'Personal',
          role: 'owner',
          is_personal: true,
          plan_status: 'trial',
          trial_ends_at: ''
        }
      ]
    })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(resources.getTeamDetail).toHaveBeenCalledWith('t9')
  })

  it('invite action posts then refreshes invites', async () => {
    vi.mocked(resources.createInvite).mockResolvedValue({
      id: 'i1',
      team_id: 't1',
      email: 'new@strider.dev',
      role: 'member',
      status: 'pending',
      created_at: '',
      expires_at: '',
      token: 'tok-once'
    })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let invite: resources.InviteApi | null = null
    await act(async () => {
      invite = await result.current.actions.invite('new@strider.dev')
    })
    expect(invite).not.toBeNull()
    expect(vi.mocked(resources.createInvite)).toHaveBeenCalledWith('t1', {
      email: 'new@strider.dev',
      role: 'member'
    })
    expect(vi.mocked(resources.listInvites).mock.calls.length).toBeGreaterThan(1)
  })

  it('is offline synchronously (no loading flash) when not linked', () => {
    useWorkspaceStore.setState({ linked: false, teamId: null })
    const { result } = renderHook(() => useTeamData())
    expect(result.current.status).toBe('offline')
  })

  it('updateTeam and deleteTeam report success, and failure as false', async () => {
    vi.mocked(resources.updateTeam).mockResolvedValue({ ...TEAM, name: 'Renamed' })
    vi.mocked(resources.deleteTeam).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.updateTeam({ name: 'Renamed' })).toBe(true)
    })
    expect(vi.mocked(resources.updateTeam)).toHaveBeenCalledWith('t1', { name: 'Renamed' })
    await act(async () => {
      expect(await result.current.actions.deleteTeam()).toBe(false)
    })
  })

  it('exposes the caller’s teams and switches the active team', async () => {
    vi.mocked(resources.getMe).mockResolvedValue({
      id: 'u1',
      email: 'maya@strider.dev',
      name: 'Maya',
      avatar_url: null,
      created_at: '',
      teams: [
        {
          team_id: 't1',
          name: 'Strider',
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
    })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.teams.map((t) => t.team_id)).toEqual(['t1', 't2'])
    act(() => result.current.actions.switchTeam('t2'))
    expect(useWorkspaceStore.getState().teamId).toBe('t2')
  })

  it('role change succeeds and removal surfaces failure as false', async () => {
    vi.mocked(resources.changeMemberRole).mockResolvedValue(MEMBERS[1])
    vi.mocked(resources.removeMember).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.changeRole('u2', 'admin')).toBe(true)
    })
    await act(async () => {
      expect(await result.current.actions.remove('u2')).toBe(false)
    })
  })

  it('loads the active team’s projects', async () => {
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(vi.mocked(resources.listProjects)).toHaveBeenCalledWith('t1')
    expect(result.current.projects.map((p) => p.id)).toEqual(['p1'])
  })

  it('stays ready even if the projects fetch fails', async () => {
    vi.mocked(resources.listProjects).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.projects).toEqual([])
  })

  it('createTeam switches the workspace to the new team', async () => {
    vi.mocked(resources.createTeam).mockResolvedValue({ ...TEAM, id: 't5', name: 'New Team' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.createTeam('New Team')).toBe(true)
    })
    expect(vi.mocked(resources.createTeam)).toHaveBeenCalledWith('New Team')
    expect(useWorkspaceStore.getState().teamId).toBe('t5')
  })

  it('joinTeam redeems the token and switches to the joined team', async () => {
    vi.mocked(resources.acceptInvite).mockResolvedValue({ team_id: 't7', role: 'member' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      const joined = await result.current.actions.joinTeam('tok-abc')
      expect(joined?.team_id).toBe('t7')
    })
    expect(vi.mocked(resources.acceptInvite)).toHaveBeenCalledWith('tok-abc')
    expect(useWorkspaceStore.getState().teamId).toBe('t7')
  })

  it('joinTeam returns null when the token is rejected', async () => {
    vi.mocked(resources.acceptInvite).mockRejectedValue(new Error('invalid'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.joinTeam('bad')).toBeNull()
    })
  })

  it('createProject posts to the active team then refreshes projects', async () => {
    vi.mocked(resources.createProject).mockResolvedValue({ ...PROJECT, id: 'p2', name: 'Arm' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      const created = await result.current.actions.createProject('Arm')
      expect(created?.id).toBe('p2')
    })
    expect(vi.mocked(resources.createProject)).toHaveBeenCalledWith('t1', { name: 'Arm' })
    expect(vi.mocked(resources.listProjects).mock.calls.length).toBeGreaterThan(1)
  })

  it('pages the activity feed via loadMoreActivity', async () => {
    const a1: resources.ActivityApi = {
      id: 'act1',
      type: 'project.created',
      domain: null,
      actor_id: 'u1',
      project_id: 'p1',
      payload: {},
      created_at: '2026-07-03T00:00:00Z'
    }
    const a2: resources.ActivityApi = { ...a1, id: 'act2' }
    vi.mocked(resources.listActivityPage)
      .mockResolvedValueOnce({ data: [a1], meta: { has_next: true, next_cursor: 'c2', total: 2 } })
      .mockResolvedValueOnce({ data: [a2], meta: { has_next: false, total: 2 } })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.activityHasMore).toBe(true)
    expect(result.current.activityTotal).toBe(2)
    await act(async () => {
      await result.current.loadMoreActivity()
    })
    expect(result.current.activity.map((a) => a.id)).toEqual(['act1', 'act2'])
    expect(result.current.activityHasMore).toBe(false)
    expect(vi.mocked(resources.listActivityPage)).toHaveBeenLastCalledWith('t1', { cursor: 'c2' })
  })

  it('falls back to the loaded count when the feed meta has no total', async () => {
    const a1: resources.ActivityApi = {
      id: 'act1',
      type: 'project.created',
      domain: null,
      actor_id: 'u1',
      project_id: 'p1',
      payload: {},
      created_at: '2026-07-03T00:00:00Z'
    }
    vi.mocked(resources.listActivityPage).mockResolvedValue({ data: [a1], meta: {} })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.activityTotal).toBe(1)
  })
})

// The persisted team id is a memory of a SERVER row, exactly like the project id
// that useValidateProject already guards. When it goes stale — the database is
// reset, the user is removed from the team, a dev points at a different stack —
// every team-scoped call 404s forever, and the screen used to blame the backend.
describe('useTeamData — a stale persisted team id', () => {
  const ME_WITH_PERSONAL = {
    id: 'u1',
    email: 'maya@strider.dev',
    name: null,
    avatar_url: null,
    created_at: '',
    teams: [
      {
        team_id: 't-real',
        name: 'Personal',
        role: 'owner',
        is_personal: true,
        plan_status: 'trial',
        trial_ends_at: ''
      }
    ]
  }

  it('ignores a stored id that is not one of my teams and uses the personal team', async () => {
    // The live failure: 't-ghost' came from a different database.
    useWorkspaceStore.setState({ linked: true, teamId: 't-ghost' })
    vi.mocked(resources.getMe).mockResolvedValue(ME_WITH_PERSONAL)
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(vi.mocked(resources.getTeamDetail)).toHaveBeenCalledWith('t-real')
    expect(vi.mocked(resources.getTeamDetail)).not.toHaveBeenCalledWith('t-ghost')
  })

  it('keeps a stored id that IS still one of my teams', async () => {
    // Self-healing must not become gratuitous switching: a user who picked a
    // non-personal team stays on it across reloads.
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(vi.mocked(resources.getTeamDetail)).toHaveBeenCalledWith('t1')
  })
})

describe('useTeamData — 404 is not "the backend is down"', () => {
  it('reports a deleted team as gone, not offline', async () => {
    // Race: the team existed in getMe and was removed before we fetched it.
    vi.mocked(resources.getTeamDetail).mockRejectedValue(
      new ApiError(404, 'not_found', 'No such team')
    )
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('gone'))
  })

  it('still reports a 5xx as offline', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new ApiError(500, 'boom', 'boom'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('still reports a network failure as offline', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new TypeError('Failed to fetch'))
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('reports offline when getMe itself fails — we could not even ask', async () => {
    vi.mocked(resources.getMe).mockRejectedValue(new TypeError('Failed to fetch'))
    useWorkspaceStore.setState({ linked: true, teamId: null })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})
