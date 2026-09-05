// Live team data for the Team screen and Settings team section: loads the
// team detail, roster, pending invites, and activity feed in parallel, and
// exposes the mutations (invite/revoke/role-change/remove/rename/delete) with
// re-fetch. Degrades to `offline` when the workspace isn't linked or the API
// is unreachable, so callers render an honest sign-in state (dev bypass).
import { useCallback, useEffect, useState } from 'react'
import {
  acceptInvite,
  changeMemberRole,
  createInvite,
  createProject as createProjectApi,
  createTeam as createTeamApi,
  deleteTeam as deleteTeamApi,
  getMe,
  getTeamDetail,
  listActivityPage,
  listInvites,
  listMembers,
  listProjects,
  removeMember,
  revokeInvite,
  updateTeam as updateTeamApi,
  type AcceptInviteResult,
  type ActivityApi,
  type InviteApi,
  type Project,
  type TeamDetail,
  type TeamMemberApi,
  type TeamRole,
  type TeamSummary
} from '../../lib/api/resources'
import type { ApiMeta } from '../../lib/api/envelope.types'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { resolveTeamId } from '../workspace/activeTeam'

/** `gone` is distinct from `offline` on purpose: the server ANSWERED, and said
 *  this team no longer exists. Rendering that as "can't reach the API" sends the
 *  user to restart a backend that is working perfectly. */
export type TeamDataStatus = 'loading' | 'ready' | 'offline' | 'gone'

export interface TeamSettingsInput {
  name?: string
  settings?: { notify_project_created: boolean }
}

export interface TeamActions {
  invite: (email: string, role?: Exclude<TeamRole, 'owner'>) => Promise<InviteApi | null>
  revoke: (inviteId: string) => Promise<boolean>
  changeRole: (userId: string, role: TeamRole) => Promise<boolean>
  remove: (userId: string) => Promise<boolean>
  updateTeam: (input: TeamSettingsInput) => Promise<boolean>
  deleteTeam: () => Promise<boolean>
  switchTeam: (teamId: string) => void
  /** Create a new team and switch the workspace to it (individual→team upgrade). */
  createTeam: (name: string) => Promise<boolean>
  /** Redeem a one-time invite token and switch to the joined team. */
  joinTeam: (token: string) => Promise<AcceptInviteResult | null>
  /** Create a project under the active team, then refresh the projects list. */
  createProject: (name: string) => Promise<Project | null>
  refresh: () => Promise<void>
}

export interface TeamData {
  status: TeamDataStatus
  team: TeamDetail | null
  members: TeamMemberApi[]
  invites: InviteApi[]
  activity: ActivityApi[]
  activityHasMore: boolean
  /** Count of ALL activity rows for the team (server-reported); falls back to
   *  the loaded count when the meta carries no total. */
  activityTotal: number
  loadMoreActivity: () => Promise<void>
  /** Active (non-archived) projects owned by the current team. */
  projects: Project[]
  /** Every team the caller belongs to — powers the team switcher. */
  teams: TeamSummary[]
  myRole: TeamRole | null
  actions: TeamActions
}

interface Setters {
  setMembers: (m: TeamMemberApi[]) => void
  setInvites: (i: InviteApi[]) => void
  setTeam: (t: TeamDetail | null) => void
  setProjects: (p: Project[]) => void
}

/** Run an action, refresh the affected slice, and report success as a boolean. */
async function runAction(
  action: () => Promise<unknown>,
  refresh: () => Promise<void>
): Promise<boolean> {
  try {
    await action()
    await refresh().catch(() => undefined)
    return true
  } catch {
    return false
  }
}

/** Build the mutation set for a resolved team. Rebuilt each render (cheap). */
function createTeamActions(
  teamId: string | null,
  setters: Setters,
  load: () => Promise<void>
): TeamActions {
  const refreshInvites = async (): Promise<void> =>
    setters.setInvites(await listInvites(teamId as string))
  const refreshMembers = async (): Promise<void> =>
    setters.setMembers(await listMembers(teamId as string))
  const refreshProjects = async (): Promise<void> =>
    setters.setProjects(await listProjects(teamId as string))
  return {
    invite: async (email, role = 'member') => {
      if (!teamId) return null
      try {
        const invite = await createInvite(teamId, { email, role })
        await refreshInvites().catch(() => undefined)
        return invite
      } catch {
        return null
      }
    },
    revoke: (inviteId) =>
      teamId
        ? runAction(() => revokeInvite(teamId, inviteId), refreshInvites)
        : Promise.resolve(false),
    changeRole: (userId, role) =>
      teamId
        ? runAction(() => changeMemberRole(teamId, userId, role), refreshMembers)
        : Promise.resolve(false),
    remove: (userId) =>
      teamId
        ? runAction(() => removeMember(teamId, userId), refreshMembers)
        : Promise.resolve(false),
    updateTeam: (input) =>
      teamId ? runAction(() => updateTeamApi(teamId, input), load) : Promise.resolve(false),
    deleteTeam: () =>
      teamId ? runAction(() => deleteTeamApi(teamId), load) : Promise.resolve(false),
    // Point the workspace at another team; the hook re-resolves off storedTeamId.
    switchTeam: (id) => useWorkspaceStore.getState().setTeamId(id),
    createTeam: async (name) => {
      try {
        const created = await createTeamApi(name)
        // Switch to the new team; the load effect re-resolves off storedTeamId.
        useWorkspaceStore.getState().setTeamId(created.id)
        return true
      } catch {
        return false
      }
    },
    joinTeam: async (token) => {
      try {
        const result = await acceptInvite(token)
        useWorkspaceStore.getState().setTeamId(result.team_id)
        return result
      } catch {
        return null
      }
    },
    createProject: async (name) => {
      if (!teamId) return null
      try {
        const project = await createProjectApi(teamId, { name })
        await refreshProjects().catch(() => undefined)
        return project
      } catch {
        return null
      }
    },
    refresh: load
  }
}

export function useTeamData(): TeamData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const storedTeamId = useWorkspaceStore((s) => s.teamId)
  // Init synchronously so an offline workspace renders its offline state
  // without a loading flash and stays deterministic in tests.
  const [status, setStatus] = useState<TeamDataStatus>(fetchEnabled ? 'loading' : 'offline')
  const [teamId, setTeamId] = useState<string | null>(null)
  const [team, setTeam] = useState<TeamDetail | null>(null)
  const [members, setMembers] = useState<TeamMemberApi[]>([])
  const [invites, setInvites] = useState<InviteApi[]>([])
  const [activity, setActivity] = useState<ActivityApi[]>([])
  const [activityMeta, setActivityMeta] = useState<ApiMeta>({})
  const [projects, setProjects] = useState<Project[]>([])
  const [teams, setTeams] = useState<TeamSummary[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    try {
      // Fetch the profile first so the team switcher always has the full list,
      // and resolve the active team from the stored id or the personal team.
      const me = await getMe().catch(() => null)
      setTeams(me?.teams ?? [])
      const id = resolveTeamId(me, storedTeamId)
      if (!id) {
        setStatus('offline')
        return
      }
      const [detail, roster, pending, feed, teamProjects] = await Promise.all([
        getTeamDetail(id),
        listMembers(id),
        listInvites(id),
        listActivityPage(id),
        // Projects are secondary — a failure here must not blank the whole screen.
        listProjects(id).catch(() => [] as Project[])
      ])
      setTeamId(id)
      setTeam(detail)
      setMembers(roster)
      setInvites(pending)
      setActivity(feed.data)
      setActivityMeta(feed.meta)
      setProjects(teamProjects)
      setStatus('ready')
    } catch (error: unknown) {
      // A 404 here means the team really is gone (a race: it existed in `getMe`
      // and was deleted, or I was removed, before we fetched it). That is not
      // "the backend is down", and telling the user to go restart a healthy
      // server is the failure this whole classification exists to prevent.
      setStatus(classifyFetchError(error) === 'gone' ? 'gone' : 'offline')
    }
  }, [fetchEnabled, storedTeamId])

  useEffect(() => {
    void load()
  }, [load])

  // Append the next cursor page of activity; keeps the current feed on failure.
  const loadMoreActivity = async (): Promise<void> => {
    if (!teamId || !activityMeta.has_next || !activityMeta.next_cursor) return
    try {
      const page = await listActivityPage(teamId, { cursor: activityMeta.next_cursor })
      setActivity((prev) => [...prev, ...page.data])
      setActivityMeta(page.meta)
    } catch {
      /* keep the current feed */
    }
  }

  const actions = createTeamActions(teamId, { setMembers, setInvites, setTeam, setProjects }, load)
  return {
    status,
    team,
    members,
    invites,
    activity,
    activityHasMore: activityMeta.has_next ?? false,
    activityTotal: activityMeta.total ?? activity.length,
    loadMoreActivity,
    projects,
    teams,
    myRole: team?.role ?? null,
    actions
  }
}
