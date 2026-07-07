// Home-screen data: the signed-in user's teams, each team's projects, and a
// merged recent-activity feed across those teams (API.md §2.2/§2.3). Exposes
// create-project / create-team with re-fetch. Degrades to `offline` (dev
// bypass / unreachable API) so the shell can show a friendly empty home.
import { useCallback, useEffect, useState } from 'react'
import {
  createProject as createProjectApi,
  createTeam as createTeamApi,
  getMe,
  listActivity,
  listProjects,
  type ActivityApi,
  type Me,
  type Project,
  type TeamSummary
} from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'

export type HomeStatus = 'loading' | 'ready' | 'offline'

export interface TeamProjects {
  team: TeamSummary
  projects: Project[]
}

export interface HomeActions {
  createProject: (teamId: string, name: string) => Promise<Project | null>
  createTeam: (name: string) => Promise<boolean>
  refresh: () => Promise<void>
}

export interface HomeData {
  status: HomeStatus
  me: Me | null
  groups: TeamProjects[]
  activity: ActivityApi[]
  actions: HomeActions
}

const RECENT_ACTIVITY_LIMIT = 12

interface HomeSnapshot {
  me: Me
  groups: TeamProjects[]
  activity: ActivityApi[]
}

/** Fetch the user's teams, their projects, and a merged recent-activity feed. */
async function fetchHome(): Promise<HomeSnapshot> {
  const me = await getMe()
  const groups = await Promise.all(
    me.teams.map(async (team) => ({ team, projects: await listProjects(team.team_id) }))
  )
  const feeds = await Promise.all(me.teams.map((t) => listActivity(t.team_id).catch(() => [])))
  const activity = feeds
    .flat()
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, RECENT_ACTIVITY_LIMIT)
  return { me, groups, activity }
}

export function useHomeData(): HomeData {
  const linked = useWorkspaceStore((s) => s.linked)
  const [status, setStatus] = useState<HomeStatus>(linked ? 'loading' : 'offline')
  const [me, setMe] = useState<Me | null>(null)
  const [groups, setGroups] = useState<TeamProjects[]>([])
  const [activity, setActivity] = useState<ActivityApi[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!linked) {
      setStatus('offline')
      return
    }
    try {
      const snap = await fetchHome()
      setMe(snap.me)
      setGroups(snap.groups)
      setActivity(snap.activity)
      setStatus('ready')
    } catch {
      setStatus('offline')
    }
  }, [linked])

  useEffect(() => {
    void load()
  }, [load])

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
    createTeam: async (name) => {
      try {
        await createTeamApi(name)
        await load().catch(() => undefined)
        return true
      } catch {
        return false
      }
    },
    refresh: load
  }

  return { status, me, groups, activity, actions }
}
