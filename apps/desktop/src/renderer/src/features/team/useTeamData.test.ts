// Team data hook: parallel load, offline fallback, action round-trips.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useTeamData } from './useTeamData'
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
    createInvite: vi.fn(),
    revokeInvite: vi.fn(),
    changeMemberRole: vi.fn(),
    removeMember: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn()
  }
})

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
    email: 'priya@strider.dev',
    name: 'Priya',
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
      .mockResolvedValueOnce({ data: [a1], meta: { has_next: true, next_cursor: 'c2' } })
      .mockResolvedValueOnce({ data: [a2], meta: { has_next: false } })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.activityHasMore).toBe(true)
    await act(async () => {
      await result.current.loadMoreActivity()
    })
    expect(result.current.activity.map((a) => a.id)).toEqual(['act1', 'act2'])
    expect(result.current.activityHasMore).toBe(false)
    expect(vi.mocked(resources.listActivityPage)).toHaveBeenLastCalledWith('t1', 'c2')
  })
})
