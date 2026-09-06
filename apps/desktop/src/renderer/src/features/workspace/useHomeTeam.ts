// The active team's layer on Home (SOLUSDEV-244 / HOME H5): detail, members,
// pending invites, the team activity feed, my role, and where I stand against
// my plan's team limit — plus the team mutations, each naming its refusal.
// Consolidates what TeamScreen / useTeamData carried; keyed on the team id with
// a stale-response guard so a slow answer for a team the user has since left
// never lands on the new one (nothing carried across — SOLUSDEV-242).
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, type ApiMeta } from '../../lib/api/envelope.types'
import { classifyFetchError } from '../../lib/api/errors'
import {
  planLimitFromError,
  teamLimitPosition,
  type PlanLimitRefusal,
  type TeamLimitPosition
} from '../../lib/api/planLimit'
import {
  changeMemberRole,
  createInvite,
  deleteTeam as deleteTeamApi,
  getSubscription,
  getTeamDetail,
  listActivityPage,
  listInvites,
  listMembers,
  personalTeam,
  removeMember,
  revokeInvite,
  updateTeam,
  type ActivityApi,
  type InviteApi,
  type Me,
  type TeamDetail,
  type TeamMemberApi,
  type TeamRole,
  type TeamSummary
} from '../../lib/api/resources'
import { EMAIL_PATTERN } from '../team/MembersPanel'
import { switchWorkspaceTeam } from './teamSwitch'

/** `idle`: no active team. `gone`: the team no longer exists (not an outage). */
export type HomeTeamStatus = 'idle' | 'loading' | 'ready' | 'offline' | 'gone'

export type InviteOutcome =
  | { ok: true; token: string | null; movedToTeamId: string | null }
  | { ok: false; reason: 'plan_limit'; limit: PlanLimitRefusal }
  | { ok: false; reason: 'already_member' | 'invite_pending' | 'invalid_email' | 'failed' }

export type LeaveOutcome = { ok: true } | { ok: false; reason: 'last_owner' | 'failed' }

export interface HomeTeamActions {
  /** Create a one-time invite. On a PERSONAL team the server spins up a new
   *  collaborative team and issues the invite there — Home follows it. */
  invite: (email: string, role?: Exclude<TeamRole, 'owner'>) => Promise<InviteOutcome>
  revoke: (inviteId: string) => Promise<boolean>
  changeRole: (userId: string, role: TeamRole) => Promise<boolean>
  remove: (userId: string) => Promise<boolean>
  /** Leave the team (any member); Home moves to my personal team. */
  leave: () => Promise<LeaveOutcome>
  rename: (name: string) => Promise<boolean>
  /** Owner-only, confirmed by the caller; Home moves to my personal team. */
  deleteTeam: () => Promise<boolean>
  loadMoreActivity: () => Promise<void>
  refresh: () => Promise<void>
}

export interface HomeTeam {
  status: HomeTeamStatus
  detail: TeamDetail | null
  members: TeamMemberApi[]
  invites: InviteApi[]
  activity: ActivityApi[]
  activityTotal: number
  activityHasMore: boolean
  myRole: TeamRole | null
  /** My plan's team position, or null until the subscription is known. */
  teamLimit: TeamLimitPosition | null
  actions: HomeTeamActions
}

interface TeamSnapshot {
  detail: TeamDetail
  members: TeamMemberApi[]
  invites: InviteApi[]
  activity: ActivityApi[]
  meta: ApiMeta
}

async function fetchTeam(teamId: string): Promise<TeamSnapshot> {
  const [detail, members, invites, feed] = await Promise.all([
    getTeamDetail(teamId),
    listMembers(teamId),
    // Invites list for admins only; a member's or viewer's 403 is not an error.
    listInvites(teamId).catch(() => [] as InviteApi[]),
    listActivityPage(teamId)
  ])
  return { detail, members, invites, activity: feed.data, meta: feed.meta }
}

function inviteRefusal(error: unknown): InviteOutcome {
  const limit = planLimitFromError(error)
  if (limit) return { ok: false, reason: 'plan_limit', limit }
  if (!(error instanceof ApiError)) return { ok: false, reason: 'failed' }
  if (error.code === 'already_member') return { ok: false, reason: 'already_member' }
  if (error.code === 'invite_pending') return { ok: false, reason: 'invite_pending' }
  if (error.status === 422) return { ok: false, reason: 'invalid_email' }
  return { ok: false, reason: 'failed' }
}

export function useHomeTeam(
  team: TeamSummary | null,
  me: Me | null,
  refreshHome: () => Promise<void>
): HomeTeam {
  const teamId = team?.team_id ?? null
  const [status, setStatus] = useState<HomeTeamStatus>(teamId ? 'loading' : 'idle')
  const [detail, setDetail] = useState<TeamDetail | null>(null)
  const [members, setMembers] = useState<TeamMemberApi[]>([])
  const [invites, setInvites] = useState<InviteApi[]>([])
  const [activity, setActivity] = useState<ActivityApi[]>([])
  const [meta, setMeta] = useState<ApiMeta>({})
  const [limits, setLimits] = useState<Record<string, number | null> | null>(null)
  const loadSeq = useRef(0)

  const load = useCallback(async (): Promise<void> => {
    const seq = ++loadSeq.current
    if (!teamId) {
      setStatus('idle')
      setDetail(null)
      setMembers([])
      setInvites([])
      setActivity([])
      setMeta({})
      return
    }
    setStatus('loading')
    setDetail(null)
    setMembers([])
    setInvites([])
    setActivity([])
    try {
      const snap = await fetchTeam(teamId)
      if (seq !== loadSeq.current) return
      setDetail(snap.detail)
      setMembers(snap.members)
      setInvites(snap.invites)
      setActivity(snap.activity)
      setMeta(snap.meta)
      setStatus('ready')
    } catch (error: unknown) {
      if (seq !== loadSeq.current) return
      setStatus(classifyFetchError(error) === 'gone' ? 'gone' : 'offline')
    }
  }, [teamId])

  useEffect(() => {
    void load()
  }, [load])

  // The plan is per USER (ADR-024), so the limit is fetched once, not per team;
  // an unknown subscription leaves the position unknown rather than guessed.
  useEffect(() => {
    let stale = false
    getSubscription()
      .then((sub) => {
        if (!stale) setLimits(sub.limits)
      })
      .catch(() => undefined)
    return () => {
      stale = true
    }
  }, [me?.id])

  const refreshMembers = useCallback(async () => {
    if (teamId) setMembers(await listMembers(teamId))
  }, [teamId])
  const refreshInvites = useCallback(async () => {
    if (teamId) setInvites(await listInvites(teamId).catch(() => [] as InviteApi[]))
  }, [teamId])

  const run = async (
    action: () => Promise<unknown>,
    after: () => Promise<void>
  ): Promise<boolean> => {
    try {
      await action()
      await after().catch(() => undefined)
      return true
    } catch {
      return false
    }
  }

  /** Where Home lands after I leave or delete the active team. */
  const fallBackToPersonal = async (): Promise<void> => {
    const home = me ? personalTeam(me) : undefined
    if (home && home.team_id !== teamId) switchWorkspaceTeam(home.team_id, 'home')
    await refreshHome().catch(() => undefined)
  }

  const actions: HomeTeamActions = {
    invite: async (email, role = 'member') => {
      if (!teamId) return { ok: false, reason: 'failed' }
      if (!EMAIL_PATTERN.test(email)) return { ok: false, reason: 'invalid_email' }
      try {
        const invite = await createInvite(teamId, { email, role })
        const moved = invite.team_id !== teamId ? invite.team_id : null
        if (moved) {
          // The personal team stays solo (ADR-025): the invite lives on the
          // collaborative team the server just created — go there.
          switchWorkspaceTeam(moved, 'home')
          await refreshHome().catch(() => undefined)
        } else {
          await refreshInvites().catch(() => undefined)
        }
        return { ok: true, token: invite.token ?? null, movedToTeamId: moved }
      } catch (error: unknown) {
        return inviteRefusal(error)
      }
    },
    revoke: (inviteId) =>
      teamId ? run(() => revokeInvite(teamId, inviteId), refreshInvites) : Promise.resolve(false),
    changeRole: (userId, role) =>
      teamId
        ? run(() => changeMemberRole(teamId, userId, role), refreshMembers)
        : Promise.resolve(false),
    remove: (userId) =>
      teamId ? run(() => removeMember(teamId, userId), refreshMembers) : Promise.resolve(false),
    leave: async () => {
      if (!teamId || !me) return { ok: false, reason: 'failed' }
      try {
        await removeMember(teamId, me.id)
        await fallBackToPersonal()
        return { ok: true }
      } catch (error: unknown) {
        const lastOwner = error instanceof ApiError && error.code === 'last_owner'
        return { ok: false, reason: lastOwner ? 'last_owner' : 'failed' }
      }
    },
    rename: (name) =>
      teamId
        ? run(
            () => updateTeam(teamId, { name }),
            async () => {
              await load()
              await refreshHome()
            }
          )
        : Promise.resolve(false),
    deleteTeam: () =>
      teamId ? run(() => deleteTeamApi(teamId), fallBackToPersonal) : Promise.resolve(false),
    loadMoreActivity: async () => {
      if (!teamId || !meta.has_next || !meta.next_cursor) return
      try {
        const page = await listActivityPage(teamId, { cursor: meta.next_cursor })
        setActivity((prev) => [...prev, ...page.data])
        setMeta(page.meta)
      } catch {
        /* keep the current feed */
      }
    },
    refresh: load
  }

  return {
    status,
    detail,
    members,
    invites,
    activity,
    activityTotal: meta.total ?? activity.length,
    activityHasMore: meta.has_next ?? false,
    myRole: detail?.role ?? null,
    teamLimit: me ? teamLimitPosition(me.teams, limits) : null,
    actions
  }
}
