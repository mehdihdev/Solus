// Home data hook (SOLUSDEV-242): the ACTIVE team's projects with per-project
// activity, the team selector's list, team/project mutations, offline.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useHomeData } from './useHomeData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'
import { useFocusStore } from './focusStore'
import { graphCache } from '../graph/graphCache'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    listProjects: vi.fn(),
    listActivityPage: vi.fn(),
    createProject: vi.fn(),
    createTeam: vi.fn(),
    acceptInvite: vi.fn(),
    updateProject: vi.fn(),
    archiveProject: vi.fn(),
    unarchiveProject: vi.fn(),
    deleteProject: vi.fn()
  }
})

const TEAM: resources.TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'trial',
  trial_ends_at: ''
}
const PERSONAL: resources.TeamSummary = {
  ...TEAM,
  team_id: 't-me',
  name: 'Maya',
  is_personal: true
}
const ME: resources.Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya',
  avatar_url: null,
  created_at: '',
  teams: [PERSONAL, TEAM]
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
  useWorkspaceStore.setState({ linked: true, teamId: 't1' })
  vi.mocked(resources.getMe).mockResolvedValue(ME)
  vi.mocked(resources.listProjects).mockResolvedValue([PROJECT])
  vi.mocked(resources.listActivityPage).mockResolvedValue({ data: ACTIVITY, meta: { total: 9 } })
})

describe('useHomeData — the active team', () => {
  it('loads the active team’s projects (archived included) and its feed split by project', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team?.team_id).toBe('t1')
    expect(result.current.teams.map((t) => t.team_id)).toEqual(['t-me', 't1'])
    expect(result.current.projects.map((p) => p.name)).toEqual(['Rover MK2'])
    expect(vi.mocked(resources.listProjects)).toHaveBeenCalledWith('t1', { includeArchived: true })
    expect(vi.mocked(resources.listActivityPage)).toHaveBeenCalledWith('t1', { limit: 50 })
    expect(vi.mocked(resources.listProjects)).not.toHaveBeenCalledWith('t-me', expect.anything())
    expect(Object.keys(result.current.activityByProject)).toEqual(['p1'])
    expect(result.current.activityByProject.p1.map((a) => a.id)).toEqual(['a1'])
  })

  it('falls back to the personal team when the stored id is not one of my teams', async () => {
    useWorkspaceStore.setState({ teamId: 't-ghost' })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team?.team_id).toBe('t-me')
    expect(vi.mocked(resources.listProjects)).toHaveBeenCalledWith('t-me', {
      includeArchived: true
    })
  })

  it('is ready with no team and no projects when I am on no team at all', async () => {
    vi.mocked(resources.getMe).mockResolvedValue({ ...ME, teams: [] })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team).toBe(null)
    expect(result.current.projects).toEqual([])
    expect(resources.listProjects).not.toHaveBeenCalled()
  })

  it('switchTeam reloads for the other team and drops the previous team’s data', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listProjects).mockResolvedValue([])
    vi.mocked(resources.listActivityPage).mockResolvedValue({ data: [], meta: { total: 0 } })
    act(() => result.current.actions.switchTeam('t-me'))
    await waitFor(() => expect(result.current.team?.team_id).toBe('t-me'))
    expect(useWorkspaceStore.getState().teamId).toBe('t-me')
    expect(result.current.projects).toEqual([])
    expect(result.current.activityByProject).toEqual({})
  })

  it('ignores a slow answer for a team the user has since left', async () => {
    let releaseFirst: (rows: resources.Project[]) => void = () => undefined
    vi.mocked(resources.listProjects).mockImplementation((teamId) =>
      teamId === 't1'
        ? new Promise<resources.Project[]>((resolve) => (releaseFirst = resolve))
        : Promise.resolve([])
    )
    const { result } = renderHook(() => useHomeData())
    act(() => useWorkspaceStore.getState().setTeamId('t-me'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      releaseFirst([PROJECT])
      await Promise.resolve()
    })
    expect(result.current.team?.team_id).toBe('t-me')
    expect(result.current.projects).toEqual([])
  })

  it('stays ready with empty per-project activity when the feed fetch fails', async () => {
    vi.mocked(resources.listActivityPage).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.activityByProject).toEqual({})
  })

  it('is offline when the workspace is not linked', async () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(resources.getMe).not.toHaveBeenCalled()
  })

  it('is offline when the profile cannot be fetched', async () => {
    vi.mocked(resources.getMe).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})

describe('useHomeData — actions', () => {
  it('createProject posts to the active team then refreshes', async () => {
    vi.mocked(resources.createProject).mockResolvedValue(PROJECT)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let created: resources.Project | null = null
    await act(async () => {
      created = await result.current.actions.createProject('Rover MK2')
    })
    expect(created).toEqual(PROJECT)
    expect(resources.createProject).toHaveBeenCalledWith('t1', { name: 'Rover MK2' })
    expect(vi.mocked(resources.listProjects).mock.calls.length).toBeGreaterThan(1)
  })

  it('createProject returns null without an active team or on failure', async () => {
    vi.mocked(resources.getMe).mockResolvedValue({ ...ME, teams: [] })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.createProject('X')).toBe(null)
    expect(resources.createProject).not.toHaveBeenCalled()
  })

  it('createTeam makes the new team active', async () => {
    vi.mocked(resources.createTeam).mockResolvedValue({ id: 't-new' } as resources.TeamDetail)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.createTeam('Rocket Lab')).toBe(true)
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t-new')
  })

  it('createTeam returns false on failure', async () => {
    vi.mocked(resources.createTeam).mockRejectedValue(new Error('nope'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.createTeam('X')).toBe(false)
  })

  it('joinTeam accepts the token and makes the joined team active', async () => {
    vi.mocked(resources.acceptInvite).mockResolvedValue({ team_id: 't7', role: 'member' })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.joinTeam('tok')).toEqual({
        team_id: 't7',
        role: 'member'
      })
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t7')
  })

  it('joinTeam returns null on a bad token', async () => {
    vi.mocked(resources.acceptInvite).mockRejectedValue(new Error('bad'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.joinTeam('bad')).toBe(null)
  })

  it('renames, archives, unarchives, and deletes a project, refreshing after each', async () => {
    vi.mocked(resources.updateProject).mockResolvedValue({} as resources.ProjectDetail)
    vi.mocked(resources.archiveProject).mockResolvedValue(PROJECT)
    vi.mocked(resources.unarchiveProject).mockResolvedValue(PROJECT)
    vi.mocked(resources.deleteProject).mockResolvedValue(undefined)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.renameProject('p1', 'Rover MK3')).toBe(true)
      expect(await result.current.actions.archiveProject('p1')).toBe(true)
      expect(await result.current.actions.unarchiveProject('p1')).toBe(true)
      expect(await result.current.actions.deleteProject('p1')).toBe(true)
    })
    expect(resources.updateProject).toHaveBeenCalledWith('p1', { name: 'Rover MK3' })
    expect(resources.archiveProject).toHaveBeenCalledWith('p1')
    expect(resources.unarchiveProject).toHaveBeenCalledWith('p1')
    expect(resources.deleteProject).toHaveBeenCalledWith('p1')
    expect(vi.mocked(resources.listProjects).mock.calls.length).toBe(5)
  })

  it('project actions return false on failure', async () => {
    vi.mocked(resources.archiveProject).mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.archiveProject('p1')).toBe(false)
  })
})

describe('useHomeData — the open project is closed when hidden or gone (SOLUSDEV-242)', () => {
  const entry = {
    version: 'v',
    entities: [],
    counts: { entityCount: 0, relationCount: 0, sourceCount: 0 },
    fetchedAtMs: Date.now()
  }
  beforeEach(() => {
    useFocusStore.getState().reset()
    graphCache.clear()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    useFocusStore.setState({ focusedEntityId: 'e1', cache: { 'p1:e1@1': {} as never } })
    graphCache.set('p1', entry)
  })

  it('deleting the open project drops the shell to no project and forgets its entities', async () => {
    vi.mocked(resources.deleteProject).mockResolvedValue(undefined)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.deleteProject('p1')).toBe(true)
    })
    expect(useWorkspaceStore.getState().project).toBe(null)
    expect(useFocusStore.getState().cache).toEqual({})
    expect(graphCache.has('p1')).toBe(false)
  })

  it('archiving the open project closes it but keeps its retained entities (archive is not delete)', async () => {
    vi.mocked(resources.archiveProject).mockResolvedValue(PROJECT)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.archiveProject('p1')).toBe(true)
    })
    expect(useWorkspaceStore.getState().project).toBe(null)
    expect(graphCache.has('p1')).toBe(true)
  })

  it('deleting ANOTHER project leaves the open one alone', async () => {
    vi.mocked(resources.deleteProject).mockResolvedValue(undefined)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.deleteProject('p-other')
    })
    expect(useWorkspaceStore.getState().project?.id).toBe('p1')
    expect(useFocusStore.getState().focusedEntityId).toBe('e1')
  })

  it('clears the grid while another team loads, so no team wears the wrong projects', async () => {
    let release: (rows: resources.Project[]) => void = () => undefined
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.projects).toHaveLength(1)
    vi.mocked(resources.listProjects).mockImplementation(
      () => new Promise<resources.Project[]>((resolve) => (release = resolve))
    )
    act(() => result.current.actions.switchTeam('t-me'))
    await waitFor(() => expect(result.current.status).toBe('loading'))
    expect(result.current.projects).toEqual([])
    await act(async () => {
      release([])
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.team?.team_id).toBe('t-me')
  })
})
