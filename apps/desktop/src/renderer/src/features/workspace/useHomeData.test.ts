// Home data hook (SOLUSDEV-242): the ACTIVE team's projects with per-project
// activity, the team selector's list, team/project mutations, offline.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useHomeData } from './useHomeData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useFocusStore } from './focusStore'
import { forgetWorkspaceGraph } from '../graph/useWorkspaceGraph'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'

vi.mock('../graph/useWorkspaceGraph', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../graph/useWorkspaceGraph')>()),
  forgetWorkspaceGraph: vi.fn()
}))

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
  resetLiveRevisions()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, teamId: 't1' })
  vi.mocked(resources.getMe).mockResolvedValue(ME)
  vi.mocked(resources.listProjects).mockResolvedValue([PROJECT])
  vi.mocked(resources.listActivityPage).mockResolvedValue({ data: ACTIVITY, meta: { total: 9 } })
})

describe('useHomeData — the active team', () => {
  homeActiveTeamLoadingTests()
  homeActiveTeamFailuresTests()
})

describe('useHomeData — actions', () => {
  homeProjectAndTeamCreationTests()
  homeTeamJoinAndSwitchTests()
  homeProjectMutationsTests()
})

describe('useHomeData — the open project is closed when hidden or gone (SOLUSDEV-242)', () => {
  beforeEach(() => {
    useFocusStore.getState().reset()
    vi.mocked(forgetWorkspaceGraph).mockClear()
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover MK2', teamId: 't1' } })
    useFocusStore.setState({ focusedEntityId: 'e1', cache: { 'p1:e1@1': {} as never } })
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
    expect(forgetWorkspaceGraph).toHaveBeenCalledWith('p1')
  })

  it('archiving the open project closes it but keeps its retained entities (archive is not delete)', async () => {
    vi.mocked(resources.archiveProject).mockResolvedValue(PROJECT)
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.archiveProject('p1')).toBe(true)
    })
    expect(useWorkspaceStore.getState().project).toBe(null)
    expect(forgetWorkspaceGraph).not.toHaveBeenCalled()
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

function homeActiveTeamLoadingTests(): void {
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
}

function homeActiveTeamFailuresTests(): void {
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
}

function homeProjectAndTeamCreationTests(): void {
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
      expect(await result.current.actions.createTeam('Rocket Lab')).toEqual({
        ok: true,
        teamId: 't-new'
      })
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t-new')
  })

  it('createTeam names a plain failure and the plan limit (HOME H5)', async () => {
    vi.mocked(resources.createTeam).mockRejectedValue(new Error('nope'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.createTeam('X')).toEqual({ ok: false, reason: 'failed' })

    vi.mocked(resources.createTeam).mockRejectedValue(
      new ApiError(409, 'plan_limit_reached', "You're at your collaborative-team limit.", [
        { limit: 'max_teams', current: 2, max: 2, upgrade: '/settings/billing' }
      ])
    )
    expect(await result.current.actions.createTeam('Y')).toEqual({
      ok: false,
      reason: 'plan_limit',
      limit: {
        limit: 'max_teams',
        current: 2,
        max: 2,
        message: "You're at your collaborative-team limit."
      }
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t1')
  })
}

function homeTeamJoinAndSwitchTests(): void {
  it('joinTeam accepts the token and makes the joined team active', async () => {
    vi.mocked(resources.acceptInvite).mockResolvedValue({ team_id: 't7', role: 'member' })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.actions.joinTeam('tok')).toEqual({
        ok: true,
        teamId: 't7',
        role: 'member'
      })
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t7')
  })

  it('joinTeam names why a token was refused instead of "try again" (HOME H5)', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const cases: Array<[unknown, string]> = [
      [new Error('bad'), 'failed'],
      [new ApiError(404, 'not_found', 'x'), 'invalid_token'],
      [new ApiError(410, 'invite_expired', 'x'), 'expired'],
      [new ApiError(403, 'forbidden', 'x'), 'wrong_email'],
      [new ApiError(409, 'already_member', 'x'), 'already_member'],
      [new ApiError(409, 'invite_revoked', 'x'), 'invalid_token']
    ]
    for (const [error, reason] of cases) {
      vi.mocked(resources.acceptInvite).mockRejectedValue(error)
      expect(await result.current.actions.joinTeam('t')).toMatchObject({ ok: false, reason })
    }
    vi.mocked(resources.acceptInvite).mockRejectedValue(
      new ApiError(409, 'plan_limit_reached', 'Leave a team or upgrade your plan.', [
        { limit: 'max_teams', current: 2, max: 2 }
      ])
    )
    expect(await result.current.actions.joinTeam('t')).toMatchObject({
      ok: false,
      reason: 'plan_limit',
      limit: { current: 2, max: 2 }
    })
    expect(useWorkspaceStore.getState().teamId).toBe('t1')
  })

  it('a deleted active team reads as gone, not as an outage (HOME H5)', async () => {
    vi.mocked(resources.listProjects).mockRejectedValue(new ApiError(404, 'not_found', 'gone'))
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('gone'))
  })

  it('switching teams closes a project of the previous team (HOME H5)', async () => {
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover', teamId: 't1' } })
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listProjects).mockResolvedValue([])
    act(() => result.current.actions.switchTeam('t-me'))
    expect(useWorkspaceStore.getState().project).toBeNull()
    expect(useWorkspaceStore.getState().teamId).toBe('t-me')
  })
}

function homeProjectMutationsTests(): void {
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
}

describe('useHomeData — live refresh (ADR-037)', () => {
  it('teamProjects(id) reloads the grid without a loading flash', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listProjects).mockResolvedValue([
      PROJECT,
      { ...PROJECT, id: 'p2', name: 'Arm' }
    ])
    const seen: string[] = []
    const stop = setInterval(() => seen.push(result.current.status), 5)
    await bumpLive(liveKeys.teamProjects('t1'))
    clearInterval(stop)
    await waitFor(() => expect(result.current.projects).toHaveLength(2))
    expect(seen).not.toContain('loading')
    expect(resources.listProjects).toHaveBeenCalledTimes(2)
  })

  it('teamActivity(id) refreshes the per-project activity', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(liveKeys.teamActivity('t1'))
    await waitFor(() => expect(resources.listActivityPage).toHaveBeenCalledTimes(2))
  })

  it('teams revalidates the selector list', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.getMe).mockResolvedValue({ ...ME, teams: [PERSONAL] })
    await bumpLive(liveKeys.teams)
    await waitFor(() => expect(result.current.teams).toHaveLength(1))
  })

  it('one burst touching projects and activity causes a single reload', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(liveKeys.teamProjects('t1'), liveKeys.teamActivity('t1'))
    await waitFor(() => expect(resources.listProjects).toHaveBeenCalledTimes(2))
    expect(resources.getMe).toHaveBeenCalledTimes(2)
  })

  it('ignores hints for other teams and unrelated keys', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(
      liveKeys.teamProjects('t2'),
      liveKeys.teamActivity('t2'),
      liveKeys.teamMembers('t1'),
      liveKeys.notifications
    )
    expect(resources.listProjects).toHaveBeenCalledTimes(1)
  })

  it('does not reload while offline', async () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useHomeData())
    await bumpLive(liveKeys.teamProjects('t1'))
    expect(result.current.status).toBe('offline')
    expect(resources.getMe).not.toHaveBeenCalled()
  })

  it('keeps the grid when a live reload fails', async () => {
    const { result } = renderHook(() => useHomeData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listProjects).mockRejectedValue(new Error('blip'))
    await bumpLive(liveKeys.teamProjects('t1'))
    expect(result.current.projects).toHaveLength(1)
  })
})
