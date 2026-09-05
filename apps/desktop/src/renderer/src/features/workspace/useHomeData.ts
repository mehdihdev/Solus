// Home-screen data (SOLUSDEV-242 / HOME H1): the ACTIVE TEAM's projects — the
// grid — with recent activity split per project, plus the signed-in user's
// teams for the team selector. Home manages ACROSS projects; everything
// project-specific lives in the workspace screens. Exposes the project and
// team mutations with re-fetch. Degrades to `offline` (dev bypass /
// unreachable API) so the shell can show a friendly empty home.
import { useCallback, useEffect, useRef, useState } from 'react'
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
  type Me,
  type Project,
  type TeamSummary
} from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { graphCache } from '../graph/graphCache'
import { resolveTeam } from './activeTeam'
import { switchWorkspaceProject } from './projectSwitch'
import {
  groupActivityByProject,
  HOME_ACTIVITY_FETCH_LIMIT,
  type ActivityByProject
} from './projectActivity'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type HomeStatus = 'loading' | 'ready' | 'offline'

export interface HomeActions {
  /** Make another of my teams the active team; the hook reloads for it. */
  switchTeam: (teamId: string) => void
  /** Create a project in the active team. */
  createProject: (name: string) => Promise<Project | null>
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
  /** Every team I belong to (the selector). */
  teams: TeamSummary[]
  /** The active team, or null when I am on no team. */
  team: TeamSummary | null
  /** The active team's projects, archived included (the grid splits them). */
  projects: Project[]
  /** The active team's recent feed, split by project (newest first). */
  activityByProject: ActivityByProject
  actions: HomeActions
}

interface HomeSnapshot {
  me: Me
  team: TeamSummary | null
  projects: Project[]
  activityByProject: ActivityByProject
}

/** Fetch the profile, resolve the active team, then its projects and feed. */
async function fetchHome(storedTeamId: string | null): Promise<HomeSnapshot> {
  const me = await getMe()
  const team = resolveTeam(me, storedTeamId)
  if (!team) return { me, team: null, projects: [], activityByProject: {} }
  const [projects, feed] = await Promise.all([
    listProjects(team.team_id, { includeArchived: true }),
    // A failed feed must not blank the grid — cards just show no activity.
    listActivityPage(team.team_id, { limit: HOME_ACTIVITY_FETCH_LIMIT }).catch(() => null)
  ])
  return { me, team, projects, activityByProject: groupActivityByProject(feed?.data ?? []) }
}

export function useHomeData(): HomeData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const storedTeamId = useWorkspaceStore((s) => s.teamId)
  const [status, setStatus] = useState<HomeStatus>(fetchEnabled ? 'loading' : 'offline')
  const [me, setMe] = useState<Me | null>(null)
  const [team, setTeam] = useState<TeamSummary | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [activityByProject, setActivityByProject] = useState<ActivityByProject>({})
  // Loads are sequenced: a team switch mid-flight must not let the previous
  // team's answer land on the new one (nothing carried across — SOLUSDEV-242).
  const loadSeq = useRef(0)
  const loadedTeamId = useRef<string | null>(null)

  const load = useCallback(async (): Promise<void> => {
    const seq = ++loadSeq.current
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    // A different team than the one on screen: clear the grid rather than show
    // the previous team's projects under the new team's name while it loads.
    if (loadedTeamId.current !== null && loadedTeamId.current !== storedTeamId) {
      setProjects([])
      setActivityByProject({})
      setStatus('loading')
    }
    try {
      const snap = await fetchHome(storedTeamId)
      if (seq !== loadSeq.current) return
      setMe(snap.me)
      setTeam(snap.team)
      setProjects(snap.projects)
      setActivityByProject(snap.activityByProject)
      setStatus('ready')
      loadedTeamId.current = storedTeamId
    } catch {
      if (seq === loadSeq.current) setStatus('offline')
    }
  }, [fetchEnabled, storedTeamId])

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

  const setActiveTeam = (teamId: string): void => useWorkspaceStore.getState().setTeamId(teamId)

  // Archiving or deleting the OPEN project closes it: the shell must not stay
  // scoped to a project that is hidden or gone (its retained entity list goes
  // with a deletion). Through the choke point, so everything else clears too.
  const closeIfOpen = (projectId: string, forget: boolean): void => {
    if (forget) graphCache.delete(projectId)
    if (useWorkspaceStore.getState().project?.id === projectId) {
      switchWorkspaceProject(null, 'home')
    }
  }

  const actions: HomeActions = {
    switchTeam: setActiveTeam,
    createProject: async (name) => {
      if (!team) return null
      try {
        const project = await createProjectApi(team.team_id, { name })
        await load().catch(() => undefined)
        return project
      } catch {
        return null
      }
    },
    createTeam: async (name) => {
      try {
        const created = await createTeamApi(name)
        // Focus the new team; the load effect re-resolves off the stored id.
        setActiveTeam(created.id)
        return true
      } catch {
        return false
      }
    },
    joinTeam: async (token) => {
      try {
        const result = await acceptInvite(token)
        // Focus the newly-joined team so it (and its projects) is in view.
        setActiveTeam(result.team_id)
        return result
      } catch {
        return null
      }
    },
    renameProject: (projectId, name) => runAction(() => updateProjectApi(projectId, { name })),
    archiveProject: (projectId) =>
      runAction(async () => {
        await archiveProjectApi(projectId)
        closeIfOpen(projectId, false)
      }),
    unarchiveProject: (projectId) => runAction(() => unarchiveProjectApi(projectId)),
    deleteProject: (projectId) =>
      runAction(async () => {
        await deleteProjectApi(projectId)
        closeIfOpen(projectId, true)
      }),
    refresh: load
  }

  return { status, me, teams: me?.teams ?? [], team, projects, activityByProject, actions }
}
