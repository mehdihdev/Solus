// The active team's layer on Home (SOLUSDEV-244 / HOME H5): detail, members,
// pending invites, the team activity feed, my role, and where I stand against
// my plan's team limit — plus the team mutations, each naming its refusal.
// Consolidates what TeamScreen / useTeamData carried; keyed on the team id with
// a stale-response guard so a slow answer for a team the user has since left
// never lands on the new one (nothing carried across — SOLUSDEV-242).
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
  type RefObject
} from 'react'
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
import { liveKeys } from '../../store/liveRevisionStore'
import { EMAIL_PATTERN } from '../team/MembersPanel'
import { mergeActivityRefresh } from '../live/mergeActivity'
import { useLiveRefetch } from '../live/useLiveRefetch'
import { switchWorkspaceTeam } from './teamSwitch'

/** `idle`: no active team. `gone`: the team no longer exists (not an outage). */
export type HomeTeamStatus = 'idle' | 'loading' | 'ready' | 'offline' | 'gone'

export type InviteOutcome =
  | { ok: true; token: string | null; movedToTeamId: string | null }
  | { ok: false; reason: 'plan_limit'; limit: PlanLimitRefusal }
  | { ok: false; reason: 'already_member' | 'invite_pending' | 'invalid_email' | 'failed' }

export type LeaveOutcome = { ok: true } | { ok: false; reason: 'last_owner' | 'failed' }

/** A member/invite mutation's verdict — named, never a swallowed 403. */
export type MemberOutcome =
  | { ok: true }
  | { ok: false; reason: 'forbidden' | 'last_owner' | 'failed' }

function memberRefusal(error: unknown): MemberOutcome {
  if (error instanceof ApiError && error.status === 403) return { ok: false, reason: 'forbidden' }
  if (error instanceof ApiError && error.code === 'last_owner') {
    return { ok: false, reason: 'last_owner' }
  }
  return { ok: false, reason: 'failed' }
}

/** Invites list for admins only: a member's or viewer's 403 (or a 404) is
 *  "none visible"; anything else is a real failure and propagates. */
async function invitesOrNone(teamId: string): Promise<InviteApi[]> {
  try {
    return await listInvites(teamId)
  } catch (error: unknown) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) return []
    throw error
  }
}

export interface HomeTeamActions {
  /** Create a one-time invite. On a PERSONAL team the server spins up a new
   *  collaborative team and issues the invite there — Home follows it. */
  invite: (email: string, role?: Exclude<TeamRole, 'owner'>) => Promise<InviteOutcome>
  revoke: (inviteId: string) => Promise<MemberOutcome>
  changeRole: (userId: string, role: TeamRole) => Promise<MemberOutcome>
  remove: (userId: string) => Promise<MemberOutcome>
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
    invitesOrNone(teamId),
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
  // The team the hook is CURRENTLY for — a refresh that resolves after a team
  // switch must not land the previous team's roster under the new team's name
  // (HOME H5 code review H2).
  const teamIdRef = useRef(teamId)
  teamIdRef.current = teamId

  const load = useCallback(
    () =>
      loadHomeTeam(teamId, loadSeq, {
        setStatus,
        setDetail,
        setMembers,
        setInvites,
        setActivity,
        setMeta
      }),
    [teamId]
  )

  useEffect(() => {
    void load()
  }, [load])

  useSubscriptionLimits(me?.id, setLimits)
  useLiveTeamRefresh({
    teamId,
    role: detail?.role ?? null,
    loadSeq,
    teamIdRef,
    feed: { activity, meta },
    writers: { setDetail, setMembers, setInvites, setActivity, setMeta }
  })

  const { refreshMembers, refreshInvites } = useSliceRefreshers(
    teamId,
    teamIdRef,
    setMembers,
    setInvites
  )

  const actions = createHomeTeamActions({
    teamId,
    me,
    refreshHome,
    load,
    refreshMembers,
    refreshInvites,
    meta,
    teamIdRef,
    setActivity,
    setMeta
  })

  return {
    status,
    detail,
    members,
    invites,
    activity,
    ...deriveTeamView(detail, activity, meta, me, limits),
    actions
  }
}

/** Quiet refetchers for the roster and invites that drop a reply for a team the hook has left. */
function useSliceRefreshers(
  teamId: string | null,
  teamIdRef: RefObject<string | null>,
  setMembers: Dispatch<SetStateAction<TeamMemberApi[]>>,
  setInvites: Dispatch<SetStateAction<InviteApi[]>>
): { refreshMembers: () => Promise<void>; refreshInvites: () => Promise<void> } {
  const refreshMembers = useCallback(async () => {
    if (!teamId) return
    const rows = await listMembers(teamId)
    if (teamIdRef.current === teamId) setMembers(rows)
  }, [teamId, teamIdRef, setMembers])
  const refreshInvites = useCallback(async () => {
    if (!teamId) return
    const rows = await invitesOrNone(teamId)
    if (teamIdRef.current === teamId) setInvites(rows)
  }, [teamId, teamIdRef, setInvites])
  return { refreshMembers, refreshInvites }
}

type DerivedTeamView = Pick<HomeTeam, 'activityTotal' | 'activityHasMore' | 'myRole' | 'teamLimit'>

/** Fields computed from the loaded slices rather than stored. */
function deriveTeamView(
  detail: TeamDetail | null,
  activity: ActivityApi[],
  meta: ApiMeta,
  me: Me | null,
  limits: Record<string, number | null> | null
): DerivedTeamView {
  return {
    activityTotal: meta.total ?? activity.length,
    activityHasMore: meta.has_next ?? false,
    myRole: detail?.role ?? null,
    teamLimit: me ? teamLimitPosition(me.teams, limits) : null
  }
}

interface HomeTeamActionContext {
  teamId: string | null
  me: Me | null
  refreshHome: () => Promise<void>
  load: () => Promise<void>
  refreshMembers: () => Promise<void>
  refreshInvites: () => Promise<void>
  meta: ApiMeta
  teamIdRef: RefObject<string | null>
  setActivity: Dispatch<SetStateAction<ActivityApi[]>>
  setMeta: Dispatch<SetStateAction<ApiMeta>>
}

function createHomeTeamActions(context: HomeTeamActionContext): HomeTeamActions {
  const {
    teamId,
    me,
    refreshHome,
    load,
    refreshMembers,
    refreshInvites,
    meta,
    teamIdRef,
    setActivity,
    setMeta
  } = context
  /** Where Home lands after I leave or delete the active team. */
  const fallBackToPersonal = async (): Promise<void> => {
    const home = me ? personalTeam(me) : undefined
    if (home && home.team_id !== teamId) switchWorkspaceTeam(home.team_id, 'home')
    await refreshHome().catch(() => undefined)
  }

  return {
    invite: (email, role = 'member') =>
      inviteHomeTeam(teamId, email, role, refreshHome, refreshInvites),
    revoke: (inviteId) =>
      teamId
        ? runMemberAction(() => revokeInvite(teamId, inviteId), refreshInvites)
        : Promise.resolve({ ok: false, reason: 'failed' }),
    changeRole: (userId, role) =>
      teamId
        ? runMemberAction(() => changeMemberRole(teamId, userId, role), refreshMembers)
        : Promise.resolve({ ok: false, reason: 'failed' }),
    remove: (userId) =>
      teamId
        ? runMemberAction(() => removeMember(teamId, userId), refreshMembers)
        : Promise.resolve({ ok: false, reason: 'failed' }),
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
        ? runTeamAction(
            () => updateTeam(teamId, { name }),
            async () => {
              await load()
              await refreshHome()
            }
          )
        : Promise.resolve(false),
    deleteTeam: () =>
      teamId
        ? runTeamAction(() => deleteTeamApi(teamId), fallBackToPersonal)
        : Promise.resolve(false),
    loadMoreActivity: async () => {
      if (!teamId || !meta.has_next || !meta.next_cursor) return
      try {
        const page = await listActivityPage(teamId, { cursor: meta.next_cursor })
        if (teamIdRef.current !== teamId) return
        setActivity((prev) => [...prev, ...page.data])
        setMeta(page.meta)
      } catch {
        /* keep the current feed */
      }
    },
    refresh: load
  }
}

async function inviteHomeTeam(
  teamId: string | null,
  email: string,
  role: Exclude<TeamRole, 'owner'>,
  refreshHome: () => Promise<void>,
  refreshInvites: () => Promise<void>
): Promise<InviteOutcome> {
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
}

async function runTeamAction(
  action: () => Promise<unknown>,
  after: () => Promise<void>
): Promise<boolean> {
  try {
    await action()
    await after().catch(() => undefined)
    return true
  } catch {
    return false
  }
}
async function runMemberAction(
  action: () => Promise<unknown>,
  after: () => Promise<void>
): Promise<MemberOutcome> {
  try {
    await action()
    await after().catch(() => undefined)
    return { ok: true }
  } catch (error: unknown) {
    return memberRefusal(error)
  }
}

interface HomeTeamStateWriters {
  setStatus: Dispatch<SetStateAction<HomeTeamStatus>>
  setDetail: Dispatch<SetStateAction<TeamDetail | null>>
  setMembers: Dispatch<SetStateAction<TeamMemberApi[]>>
  setInvites: Dispatch<SetStateAction<InviteApi[]>>
  setActivity: Dispatch<SetStateAction<ActivityApi[]>>
  setMeta: Dispatch<SetStateAction<ApiMeta>>
}

async function loadHomeTeam(
  teamId: string | null,
  loadSeq: RefObject<number>,
  writers: HomeTeamStateWriters
): Promise<void> {
  const { setStatus, setDetail, setMembers, setInvites, setActivity, setMeta } = writers
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
}

interface LiveTeamRefresh {
  teamId: string | null
  role: TeamRole | null
  loadSeq: RefObject<number>
  teamIdRef: RefObject<string | null>
  feed: { activity: ActivityApi[]; meta: ApiMeta }
  writers: Pick<
    HomeTeamStateWriters,
    'setDetail' | 'setMembers' | 'setInvites' | 'setActivity' | 'setMeta'
  >
}

/** Only admins and owners may list invites; a hint must not make anyone else try. */
const canListInvites = (role: TeamRole | null): boolean => role === 'owner' || role === 'admin'

/** ADR-037: each live hint refetches ONLY the slice it names, quietly (no
 *  loading flash). A reply is dropped when the team changed or a full load
 *  started meanwhile, so a slow answer never lands on the wrong team. */
function useLiveTeamRefresh(context: LiveTeamRefresh): void {
  const { teamId, role, loadSeq, teamIdRef, writers } = context
  const feedRef = useRef(context.feed)
  feedRef.current = context.feed
  const refresh = async <T>(
    fetch: (id: string) => Promise<T>,
    apply: (value: T) => void
  ): Promise<void> => {
    if (!teamId) return
    const seq = loadSeq.current
    try {
      const value = await fetch(teamId)
      if (teamIdRef.current === teamId && loadSeq.current === seq) apply(value)
    } catch {
      /* keep what is on screen; the next hint or a reload recovers */
    }
  }
  const useWatch = (key: (id: string) => string, run: () => Promise<void>, enabled = true): void =>
    useLiveRefetch([teamId ? key(teamId) : null], () => void run(), enabled && teamId !== null)
  useWatch(liveKeys.team, () => refresh(getTeamDetail, writers.setDetail))
  useWatch(liveKeys.teamMembers, () => refresh(listMembers, writers.setMembers))
  useWatch(
    liveKeys.teamInvites,
    () => refresh(invitesOrNone, writers.setInvites),
    canListInvites(role)
  )
  useWatch(liveKeys.teamActivity, () =>
    refresh(
      (id) => listActivityPage(id),
      (page) => {
        const merged = mergeActivityRefresh(
          { items: feedRef.current.activity, meta: feedRef.current.meta },
          page
        )
        writers.setActivity(merged.items)
        writers.setMeta(merged.meta)
      }
    )
  )
}

function useSubscriptionLimits(
  userId: string | undefined,
  setLimits: Dispatch<SetStateAction<Record<string, number | null> | null>>
): void {
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
  }, [userId, setLimits])
}
