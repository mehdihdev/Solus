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
  type Me,
  type Project,
  type TeamSummary
} from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { ApiError } from '../../lib/api/envelope.types'
import { planLimitFromError, type PlanLimitRefusal } from '../../lib/api/planLimit'
import { renameWorkspaceProject } from './projectSwitch'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { forgetWorkspaceGraph } from '../graph/useWorkspaceGraph'
import { resolveTeam } from './activeTeam'
import { switchWorkspaceProject } from './projectSwitch'
import { switchWorkspaceTeam } from './teamSwitch'
import {
  groupActivityByProject,
  HOME_ACTIVITY_FETCH_LIMIT,
  type ActivityByProject
} from './projectActivity'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

/** `gone`: the server answered that the active team no longer exists (deleted,
 *  or I was removed) — not an outage, and the only verdict that discards it. */
export type HomeStatus = 'loading' | 'ready' | 'offline' | 'gone'

/** Why a team could not be created or joined — named, never "try again"
 *  (SOLUSDEV-244 / HOME H5). `plan_limit` carries the server's own numbers. */
export type TeamRefusal =
  | { ok: false; reason: 'plan_limit'; limit: PlanLimitRefusal }
  | {
      ok: false
      reason: 'invalid_token' | 'expired' | 'wrong_email' | 'already_member' | 'failed'
    }
export type CreateTeamResult = { ok: true; teamId: string } | TeamRefusal
export type JoinTeamResult = { ok: true; teamId: string; role: string } | TeamRefusal

/** Map an invite-accept failure to the reason the modal names (invites.py). */
export function joinRefusal(error: unknown): TeamRefusal {
  const limit = planLimitFromError(error)
  if (limit) return { ok: false, reason: 'plan_limit', limit }
  if (!(error instanceof ApiError)) return { ok: false, reason: 'failed' }
  if (error.status === 410) return { ok: false, reason: 'expired' }
  if (error.status === 404) return { ok: false, reason: 'invalid_token' }
  if (error.status === 403) return { ok: false, reason: 'wrong_email' }
  if (error.code === 'already_member') return { ok: false, reason: 'already_member' }
  if (error.code === 'invite_revoked' || error.code === 'invite_already_accepted') {
    return { ok: false, reason: 'invalid_token' }
  }
  return { ok: false, reason: 'failed' }
}

export interface HomeActions {
  /** Make another of my teams the active team through the team choke point:
   *  a project of the previous team is closed, and the hook reloads. */
  switchTeam: (teamId: string) => void
  /** Create a project in the active team. */
  createProject: (name: string) => Promise<Project | null>
  createTeam: (name: string) => Promise<CreateTeamResult>
  joinTeam: (token: string) => Promise<JoinTeamResult>
  renameProject: (projectId: string, name: string) => Promise<boolean>
  /** Rename and re-describe (the retired Overview hub's edit, now on the card). */
  editProject: (projectId: string, name: string, description: string) => Promise<boolean>
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
    } catch (error: unknown) {
      if (seq !== loadSeq.current) return
      // A 404 for the stored team is "gone" (deleted, or I was removed) — the
      // backend is answering; telling the user to restart it is the failure
      // errors.ts exists to prevent. The next load re-resolves to the personal team.
      setStatus(classifyFetchError(error) === 'gone' ? 'gone' : 'offline')
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

  // Through the team choke point (HOME H5): a project of the previous team is
  // closed and every project-scoped store cleared before the team moves.
  const setActiveTeam = (teamId: string): void => switchWorkspaceTeam(teamId, 'home')

  // Archiving or deleting the OPEN project closes it: the shell must not stay
  // scoped to a project that is hidden or gone (its retained entity list goes
  // with a deletion). Through the choke point, so everything else clears too.
  const closeIfOpen = (projectId: string, forget: boolean): void => {
    if (forget) forgetWorkspaceGraph(projectId)
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
        return { ok: true, teamId: created.id }
      } catch (error: unknown) {
        const limit = planLimitFromError(error)
        return limit ? { ok: false, reason: 'plan_limit', limit } : { ok: false, reason: 'failed' }
      }
    },
    joinTeam: async (token) => {
      try {
        const result = await acceptInvite(token)
        // Focus the newly-joined team so it (and its projects) is in view.
        setActiveTeam(result.team_id)
        return { ok: true, teamId: result.team_id, role: result.role }
      } catch (error: unknown) {
        return joinRefusal(error)
      }
    },
    renameProject: (projectId, name) => runAction(() => updateProjectApi(projectId, { name })),
    editProject: (projectId, name, description) =>
      runAction(async () => {
        await updateProjectApi(projectId, { name, description })
        // The open project's pill and switcher follow the new name at once.
        if (useWorkspaceStore.getState().project?.id === projectId) renameWorkspaceProject(name)
      }),
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
