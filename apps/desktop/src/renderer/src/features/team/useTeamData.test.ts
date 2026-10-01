// Settings → Team data hook (slimmed in SOLUSDEV-244 / HOME H5): detail + role,
// rename/settings/delete, offline vs gone.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useTeamData } from './useTeamData'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    getTeamDetail: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn()
  }
})
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.extensions')>()),
  postDataEvents: vi.fn(async () => undefined)
}))

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
const ME: resources.Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya',
  avatar_url: null,
  created_at: '',
  teams: [
    {
      team_id: 't-me',
      name: 'Maya',
      role: 'owner',
      is_personal: true,
      plan_status: 'trial',
      trial_ends_at: ''
    },
    {
      team_id: 't1',
      name: 'Strider',
      role: 'owner',
      is_personal: false,
      plan_status: 'trial',
      trial_ends_at: ''
    }
  ]
}

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, teamId: 't1' })
  vi.mocked(resources.getMe).mockResolvedValue(ME)
  vi.mocked(resources.getTeamDetail).mockResolvedValue(TEAM)
})

describe('useTeamData', () => {
  it('loads the active team detail and my role — and nothing Settings does not render', async () => {
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team?.name).toBe('Strider Robotics')
    expect(result.current.myRole).toBe('owner')
    expect(result.current.teams).toHaveLength(2)
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(1)
  })

  it('is offline synchronously when the workspace is not linked', () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useTeamData())
    expect(result.current.status).toBe('offline')
    expect(resources.getMe).not.toHaveBeenCalled()
  })

  it('ignores a stored id that is not one of my teams and uses the personal team', async () => {
    useWorkspaceStore.setState({ teamId: 't-stale' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(resources.getTeamDetail).toHaveBeenCalledWith('t-me')
  })

  it('reports a deleted team as gone and a 5xx / network failure as offline', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new ApiError(404, 'not_found', 'x'))
    const gone = renderHook(() => useTeamData())
    await waitFor(() => expect(gone.result.current.status).toBe('gone'))
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new ApiError(500, 'error', 'x'))
    const offline = renderHook(() => useTeamData())
    await waitFor(() => expect(offline.result.current.status).toBe('offline'))
  })

  it('updateTeam refreshes on success and reports failure as false', async () => {
    vi.mocked(resources.updateTeam).mockResolvedValueOnce({ ...TEAM, name: 'Strider Racing' })
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.updateTeam({ name: 'Strider Racing' })).toBe(true)
    })
    expect(resources.updateTeam).toHaveBeenCalledWith('t1', { name: 'Strider Racing' })
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(2)
    vi.mocked(resources.updateTeam).mockRejectedValueOnce(new ApiError(403, 'forbidden', 'x'))
    expect(await result.current.actions.updateTeam({ name: 'X' })).toBe(false)
  })

  it('deleteTeam moves the workspace to the personal team; failure is false', async () => {
    vi.mocked(resources.deleteTeam).mockResolvedValueOnce(undefined)
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.deleteTeam()).toBe(true)
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t-me')
    vi.mocked(resources.deleteTeam).mockRejectedValueOnce(new ApiError(403, 'forbidden', 'x'))
    expect(await result.current.actions.deleteTeam()).toBe(false)
  })
})

describe('useTeamData — live refresh (ADR-037)', () => {
  it('team(id) refetches the detail', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    vi.mocked(resources.getTeamDetail).mockResolvedValue(TEAM)
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...TEAM, name: 'Renamed' })
    await bumpLive(liveKeys.team('t1'))
    await waitFor(() => expect(result.current.team?.name).toBe('Renamed'))
    expect(result.current.status).toBe('ready')
  })

  it('teams refreshes the team list; other teams and keys are ignored', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    vi.mocked(resources.getTeamDetail).mockResolvedValue(TEAM)
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(liveKeys.team('other'), liveKeys.teamMembers('t1'), liveKeys.me)
    expect(resources.getTeamDetail).toHaveBeenCalledTimes(1)
    vi.mocked(resources.getMe).mockResolvedValue({ ...ME, teams: [ME.teams[0]] })
    await bumpLive(liveKeys.teams)
    await waitFor(() => expect(result.current.teams).toHaveLength(1))
  })

  it('keeps the team on screen when a live refetch fails', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    vi.mocked(resources.getTeamDetail).mockResolvedValue(TEAM)
    const { result } = renderHook(() => useTeamData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new Error('blip'))
    await bumpLive(liveKeys.team('t1'))
    expect(result.current.team?.name).toBe('Strider Robotics')
    expect(result.current.status).toBe('ready')
  })
})
