// Live team data for the Team screen and Settings team section: loads the
// team detail, roster, pending invites, and activity feed in parallel, and
// exposes the mutations (invite/revoke/role-change/remove/rename/delete) with
// re-fetch. Degrades to `offline` when the workspace isn't linked or the API is
// unreachable, so the prototype mock rendering can take over (dev bypass).
import { useCallback, useEffect, useState } from 'react'
import {
  changeMemberRole,
  createInvite,
  deleteTeam as deleteTeamApi,
  getMe,
  getTeamDetail,
  listActivityPage,
  listInvites,
  listMembers,
  personalTeam,
  removeMember,
  revokeInvite,
  updateTeam as updateTeamApi,
  type ActivityApi,
  type InviteApi,
  type TeamDetail,
  type TeamMemberApi,
  type TeamRole
} from '../../lib/api/resources'
import type { ApiMeta } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'

export type TeamDataStatus = 'loading' | 'ready' | 'offline'

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
  refresh: () => Promise<void>
}

export interface TeamData {
  status: TeamDataStatus
  team: TeamDetail | null
  members: TeamMemberApi[]
  invites: InviteApi[]
  activity: ActivityApi[]
  activityHasMore: boolean
  loadMoreActivity: () => Promise<void>
  myRole: TeamRole | null
  actions: TeamActions
}

interface Setters {
  setMembers: (m: TeamMemberApi[]) => void
  setInvites: (i: InviteApi[]) => void
  setTeam: (t: TeamDetail | null) => void
}

async function resolveTeamId(storedId: string | null): Promise<string | null> {
  if (storedId) return storedId
  const me = await getMe()
  return personalTeam(me)?.team_id ?? null
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
    refresh: load
  }
}

export function useTeamData(): TeamData {
  const linked = useWorkspaceStore((s) => s.linked)
  const storedTeamId = useWorkspaceStore((s) => s.teamId)
  // Init from `linked` so an offline workspace renders the demo synchronously
  // (no loading flash) and stays deterministic in tests.
  const [status, setStatus] = useState<TeamDataStatus>(linked ? 'loading' : 'offline')
  const [teamId, setTeamId] = useState<string | null>(null)
  const [team, setTeam] = useState<TeamDetail | null>(null)
  const [members, setMembers] = useState<TeamMemberApi[]>([])
  const [invites, setInvites] = useState<InviteApi[]>([])
  const [activity, setActivity] = useState<ActivityApi[]>([])
  const [activityMeta, setActivityMeta] = useState<ApiMeta>({})

  const load = useCallback(async (): Promise<void> => {
    if (!linked) {
      setStatus('offline')
      return
    }
    try {
      const id = await resolveTeamId(storedTeamId)
      if (!id) {
        setStatus('offline')
        return
      }
      const [detail, roster, pending, feed] = await Promise.all([
        getTeamDetail(id),
        listMembers(id),
        listInvites(id),
        listActivityPage(id)
      ])
      setTeamId(id)
      setTeam(detail)
      setMembers(roster)
      setInvites(pending)
      setActivity(feed.data)
      setActivityMeta(feed.meta)
      setStatus('ready')
    } catch {
      setStatus('offline')
    }
  }, [linked, storedTeamId])

  useEffect(() => {
    void load()
  }, [load])

  // Append the next cursor page of activity; keeps the current feed on failure.
  const loadMoreActivity = async (): Promise<void> => {
    if (!teamId || !activityMeta.has_next || !activityMeta.next_cursor) return
    try {
      const page = await listActivityPage(teamId, activityMeta.next_cursor)
      setActivity((prev) => [...prev, ...page.data])
      setActivityMeta(page.meta)
    } catch {
      /* keep the current feed */
    }
  }

  const actions = createTeamActions(teamId, { setMembers, setInvites, setTeam }, load)
  return {
    status,
    team,
    members,
    invites,
    activity,
    activityHasMore: activityMeta.has_next ?? false,
    loadMoreActivity,
    myRole: team?.role ?? null,
    actions
  }
}
