// Home data hook: teams+projects, merged activity, create actions, offline.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useHomeData } from './useHomeData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    listProjects: vi.fn(),
    listActivity: vi.fn(),
    createProject: vi.fn(),
    createTeam: vi.fn(),
    acceptInvite: vi.fn(),
    updateProject: vi.fn(),
    archiveProject: vi.fn(),
    unarchiveProject: vi.fn(),
    deleteProject: vi.fn()
  }
})

const ME: resources.Me = {
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
}
const PROJECT: resources.Project = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: null,
  archived_at: null,
  created_at: '2026-07-05T00:00:00Z',
  updated_at: '2026-07-05T00:00:00Z'
}
const ACTIVITY: resources.ActivityApi[] = [
  {
    id: 'a1',
    type: 'project.created',
    domain: null,
    actor_id: 'u1',
    project_id: 'p1',
    payload: {},
    created_at: '2026-07-05T10:00:00Z'
  },
  {
    id: 'a2',
    type: 'invite.accepted',
    domain: null,
    actor_id: 'u2',
    project_id: null,
    payload: {},
    created_at: '2026-07-06T10:00:00Z'
  }
]

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  vi.mocked(resources.getMe).mockResolvedValue(ME)
  vi.mocked(resources.listProjects).mockResolvedValue([PROJECT])
  vi.mocked(resources.listActivity).mockResolvedValue(ACTIVITY)
})

describe('useHomeData', () => {
  it('loads teams with their projects and a merged, newest-first activity feed', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].projects[0].name).toBe('Rover MK2')
    expect(result.current.activity[0].id).toBe('a2') // newest first
  })

  it('is offline when the workspace is not linked', async () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(resources.getMe).not.toHaveBeenCalled()
  })

  it('createProject posts then refreshes', async () => {
    vi.mocked(resources.createProject).mockResolvedValue(PROJECT)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      const created = await result.current.actions.createProject('t1', 'Rover MK2')
      expect(created?.id).toBe('p1')
    })
    expect(vi.mocked(resources.createProject)).toHaveBeenCalledWith('t1', { name: 'Rover MK2' })
    expect(vi.mocked(resources.getMe).mock.calls.length).toBeGreaterThan(1)
  })

  it('createTeam returns false on failure', async () => {
    vi.mocked(resources.createTeam).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.createTeam('New Lab')).toBe(false)
    })
  })

  it('requests archived projects so the archived section can render', async () => {
    renderHook(() => useHomeData())
    await waitFor(() =>
      expect(resources.listProjects).toHaveBeenCalledWith('t1', { includeArchived: true })
    )
  })

  it('joinTeam accepts the token, selects the joined team, then refreshes', async () => {
    vi.mocked(resources.acceptInvite).mockResolvedValue({ team_id: 't9', role: 'member' })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      const joined = await result.current.actions.joinTeam('tok_abc')
      expect(joined?.team_id).toBe('t9')
    })
    expect(resources.acceptInvite).toHaveBeenCalledWith('tok_abc')
    expect(useWorkspaceStore.getState().teamId).toBe('t9')
    expect(vi.mocked(resources.getMe).mock.calls.length).toBeGreaterThan(1)
  })

  it('joinTeam returns null on a bad token', async () => {
    vi.mocked(resources.acceptInvite).mockRejectedValue(new Error('404'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.joinTeam('nope')).toBeNull()
    })
  })

  it('renames a project then refreshes', async () => {
    vi.mocked(resources.updateProject).mockResolvedValue({
      ...PROJECT,
      name: 'Rover MK3',
      stats: { entities: 0, relations: 0 },
      sources: []
    })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.renameProject('p1', 'Rover MK3')).toBe(true)
    })
    expect(resources.updateProject).toHaveBeenCalledWith('p1', { name: 'Rover MK3' })
    expect(vi.mocked(resources.getMe).mock.calls.length).toBeGreaterThan(1)
  })

  it('archives, unarchives, and deletes a project', async () => {
    vi.mocked(resources.archiveProject).mockResolvedValue({ ...PROJECT, archived_at: 'now' })
    vi.mocked(resources.unarchiveProject).mockResolvedValue(PROJECT)
    vi.mocked(resources.deleteProject).mockResolvedValue(undefined)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.archiveProject('p1')).toBe(true)
      expect(await result.current.actions.unarchiveProject('p1')).toBe(true)
      expect(await result.current.actions.deleteProject('p1')).toBe(true)
    })
    expect(resources.archiveProject).toHaveBeenCalledWith('p1')
    expect(resources.unarchiveProject).toHaveBeenCalledWith('p1')
    expect(resources.deleteProject).toHaveBeenCalledWith('p1')
  })

  it('project actions return false on failure', async () => {
    vi.mocked(resources.deleteProject).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.deleteProject('p1')).toBe(false)
    })
  })
})
