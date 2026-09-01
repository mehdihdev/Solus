// Home-screen data: the signed-in user's teams, each team's projects, and a
// merged recent-activity feed across those teams (API.md §2.2/§2.3). Exposes
// create-project / create-team with re-fetch. Degrades to `offline` (dev
// bypass / unreachable API) so the shell can show a friendly empty home.
import { useCallback, useEffect, useState } from 'react'
import {
  acceptInvite,
  archiveProject as archiveProjectApi,
  createProject as createProjectApi,
  createTeam as createTeamApi,
  deleteProject as deleteProjectApi,
  getMe,
  listActivityPage,
  listProjects,
  unarchiveProject as unarchiveProjectApi,
  updateProject as updateProjectApi,
  type AcceptInviteResult,
  type ActivityApi,
  type Me,
  type Project,
  type TeamSummary
} from '../../lib/api/resources'
import type { Page } from '../../lib/api/client'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type HomeStatus = 'loading' | 'ready' | 'offline'

export interface TeamProjects {
  team: TeamSummary
  projects: Project[]
}

export interface HomeActions {
  createProject: (teamId: string, name: string) => Promise<Project | null>
  createTeam: (name: string) => Promise<boolean>
  joinTeam: (token: string) => Promise<AcceptInviteResult | null>
  renameProject: (projectId: string, name: string) => Promise<boolean>
  archiveProject: (projectId: string) => Promise<boolean>
  unarchiveProject: (projectId: string) => Promise<boolean>
  deleteProject: (projectId: string) => Promise<boolean>
  refresh: () => Promise<void>
}

export interface HomeData {
  status: HomeStatus
  me: Me | null
  groups: TeamProjects[]
  activity: ActivityApi[]
  /** Combined server-reported activity count across all teams (SOLUSDEV-233). */
  activityTotal: number
  actions: HomeActions
}

/** Per-team fetch depth for the merged feed — the panel previews it, the
 *  all-activity dialog shows everything loaded. */
const HOME_ACTIVITY_FETCH_LIMIT = 50

interface HomeSnapshot {
  me: Me
  groups: TeamProjects[]
  activity: ActivityApi[]
  activityTotal: number
}

/** Fetch the user's teams, their projects, and a merged recent-activity feed. */
async function fetchHome(): Promise<HomeSnapshot> {
  const me = await getMe()
  const groups = await Promise.all(
    me.teams.map(async (team) => ({
      team,
      projects: await listProjects(team.team_id, { includeArchived: true })
    }))
  )
  // One team's failed feed must not blank the whole home screen.
  const feeds = await Promise.all(
    me.teams.map((t) =>
      listActivityPage(t.team_id, { limit: HOME_ACTIVITY_FETCH_LIMIT }).catch(() => null)
    )
  )
  const pages = feeds.filter((f): f is Page<ActivityApi[]> => f !== null)
  const activity = pages
    .flatMap((p) => p.data)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const activityTotal = pages.reduce((sum, p) => sum + (p.meta.total ?? p.data.length), 0)
  return { me, groups, activity, activityTotal }
}

export function useHomeData(): HomeData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [status, setStatus] = useState<HomeStatus>(fetchEnabled ? 'loading' : 'offline')
  const [me, setMe] = useState<Me | null>(null)
  const [groups, setGroups] = useState<TeamProjects[]>([])
  const [activity, setActivity] = useState<ActivityApi[]>([])
  const [activityTotal, setActivityTotal] = useState(0)

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    try {
      const snap = await fetchHome()
      setMe(snap.me)
      setGroups(snap.groups)
      setActivity(snap.activity)
      setActivityTotal(snap.activityTotal)
      setStatus('ready')
    } catch {
      setStatus('offline')
    }
  }, [fetchEnabled])

  useEffect(() => {
    void load()
  }, [load])

  // Run a mutation, refresh the home snapshot, and report success as a boolean.
  const runAction = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      try {
        await action()
        await load().catch(() => undefined)
        return true
      } catch {
        return false
      }
    },
    [load]
  )

  const actions: HomeActions = {
    createProject: async (teamId, name) => {
      try {
        const project = await createProjectApi(teamId, { name })
        await load().catch(() => undefined)
        return project
      } catch {
        return null
      }
    },
    createTeam: (name) => runAction(() => createTeamApi(name)),
    joinTeam: async (token) => {
      try {
        const result = await acceptInvite(token)
        // Focus the newly-joined team so it (and its projects) is in view.
        useWorkspaceStore.getState().setTeamId(result.team_id)
        await load().catch(() => undefined)
        return result
      } catch {
        return null
      }
    },
    renameProject: (projectId, name) => runAction(() => updateProjectApi(projectId, { name })),
    archiveProject: (projectId) => runAction(() => archiveProjectApi(projectId)),
    unarchiveProject: (projectId) => runAction(() => unarchiveProjectApi(projectId)),
    deleteProject: (projectId) => runAction(() => deleteProjectApi(projectId)),
    refresh: load
  }

  return { status, me, groups, activity, activityTotal, actions }
}
