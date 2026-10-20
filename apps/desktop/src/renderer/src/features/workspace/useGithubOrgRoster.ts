// SOLUSDEV-317 (ADR-039 amendment 2026-10-19): the GITHUB ORG MEMBERS section's
// data — the org roster, paged, plus optimistic assign / unassign / invite with a
// pending flag, an error and an announcement PER ROW (other rows never block).
// Admin-only: `enabled` is false for anyone else, so a viewer never makes the
// 403 roster call. Keyed on the team id; a reply for a team the user has since
// left is dropped. `team.members_changed` / `team.updated` refetch quietly.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { TeamMemberApi } from '../../lib/api/resources'
import {
  assignGithubMember,
  listTeamGithubMembers,
  unassignGithubMember,
  type GithubOrgMember
} from '../../lib/api/resources.teamGithub'
import { liveKeys } from '../../store/liveRevisionStore'
import { useLiveRefetch } from '../live/useLiveRefetch'
import {
  appendUnique,
  assignRefusal,
  keepPending,
  commonRefusal,
  optimisticAssignment,
  restoreRow,
  teammateName,
  withAssignment,
  type Refusal,
  type RowAnnounce,
  type RowProblem
} from './githubOrgRoster'
import type { MemberInviteOutcome } from './useTeamGithub'

export type RosterStatus = 'idle' | 'loading' | 'ready' | 'failed'

export interface RowState {
  pending: boolean
  error: RowProblem | null
  /** Read out by the row's `role="status"` after a mutation. */
  announce: RowAnnounce | null
}

export interface RosterDeps {
  teamId: string
  /** Owner/admin AND a live Organization link — else no roster call at all. */
  enabled: boolean
  inviteMember: (member: GithubOrgMember) => Promise<MemberInviteOutcome>
  /** The team's member list is stale (`not_a_team_member`). */
  onMembersStale: () => void
  /** The link itself is stale (missing / suspended): the card refetches. */
  onLinkStale: () => void
}

export interface GithubOrgRosterActions {
  retry: () => Promise<void>
  loadMore: () => Promise<void>
  assign: (githubId: number, teammate: TeamMemberApi) => Promise<void>
  unassign: (githubId: number) => Promise<void>
  invite: (member: GithubOrgMember) => Promise<MemberInviteOutcome>
}

export interface GithubOrgRoster {
  status: RosterStatus
  items: GithubOrgMember[]
  total: number | null
  cursor: string | null
  loadingMore: boolean
  rows: Readonly<Record<number, RowState>>
  actions: GithubOrgRosterActions
}

export const ROSTER_PAGE = 50
/** A quiet refetch re-reads every loaded row, up to this many. */
const ROSTER_REFETCH_MAX = 100

const IDLE_ROW: RowState = { pending: false, error: null, announce: null }

interface Page {
  items: GithubOrgMember[]
  total: number | null
  cursor: string | null
}

/** A quiet refetch re-reads every loaded row (capped); a first load reads a page. */
const pageLimit = (quiet: boolean, loaded: number): number =>
  quiet ? Math.min(Math.max(loaded, ROSTER_PAGE), ROSTER_REFETCH_MAX) : ROSTER_PAGE

const EMPTY_PAGE: Page = { items: [], total: null, cursor: null }

export function useGithubOrgRoster(deps: RosterDeps): GithubOrgRoster {
  const { teamId, enabled } = deps
  const [status, setStatus] = useState<RosterStatus>(enabled ? 'loading' : 'idle')
  const [page, setPage] = useState<Page>(EMPTY_PAGE)
  const [loadingMore, setLoadingMore] = useState(false)
  const [rows, setRows] = useState<Record<number, RowState>>({})
  const latest = useRef(deps)
  const teamRef = useRef(teamId)
  const pageRef = useRef(page)
  const rowsRef = useRef(rows)
  const statusRef = useRef(status)
  const seq = useRef(0)
  useEffect(() => {
    latest.current = deps
    teamRef.current = teamId
    pageRef.current = page
    rowsRef.current = rows
    statusRef.current = status
  })

  const load = useCallback(
    async (quiet: boolean): Promise<void> => {
      const mine = ++seq.current
      if (!enabled) return void setStatus('idle')
      if (!quiet) setStatus('loading')
      const limit = pageLimit(quiet, pageRef.current.items.length)
      const stale = (): boolean => mine !== seq.current || teamRef.current !== teamId
      try {
        const next = await listTeamGithubMembers(teamId, { limit })
        if (stale()) return
        // A row mid-mutation keeps its optimistic state; its own hint refetches it.
        setPage((prev) => keepPending(prev, next, rowsRef.current))
        setStatus('ready')
      } catch {
        if (stale()) return
        // A quiet load that superseded the first one must not strand the spinner.
        if (!quiet || statusRef.current === 'loading') setStatus('failed')
      }
    },
    [teamId, enabled]
  )

  useEffect(() => {
    teamRef.current = teamId
    pageRef.current = EMPTY_PAGE
    setPage(EMPTY_PAGE)
    setRows({})
    void load(false)
  }, [load, teamId])
  useLiveRefetch(
    [liveKeys.teamMembers(teamId), liveKeys.team(teamId)],
    () => void load(true),
    enabled
  )

  const ctx: ActionContext = {
    teamId,
    teamRef,
    pageRef,
    rowsRef,
    seq,
    latest,
    load,
    setPage,
    setRows,
    setLoadingMore
  }
  return { status, ...page, loadingMore, rows, actions: createActions(ctx) }
}

interface ActionContext {
  teamId: string
  teamRef: React.RefObject<string>
  pageRef: React.RefObject<Page>
  rowsRef: React.RefObject<Record<number, RowState>>
  seq: React.RefObject<number>
  latest: React.RefObject<RosterDeps>
  load: (quiet: boolean) => Promise<void>
  setPage: React.Dispatch<React.SetStateAction<Page>>
  setRows: React.Dispatch<React.SetStateAction<Record<number, RowState>>>
  setLoadingMore: (value: boolean) => void
}

function createActions(ctx: ActionContext): GithubOrgRosterActions {
  const { teamId, teamRef, setPage, setRows } = ctx
  const stale = (): boolean => teamRef.current !== teamId
  const setRow = (id: number, row: Partial<RowState>): void =>
    setRows((prev) => ({ ...prev, [id]: { ...(prev[id] ?? IDLE_ROW), ...row } }))
  const mapItems = (fn: (items: GithubOrgMember[]) => GithubOrgMember[]): void =>
    setPage((prev) => ({ ...prev, items: fn(prev.items) }))
  // A row already mid-mutation is left alone: its `previous` would be optimistic.
  const find = (id: number): GithubOrgMember | undefined =>
    ctx.rowsRef.current[id]?.pending
      ? undefined
      : ctx.pageRef.current.items.find((m) => m.github_id === id)
  const markPending = (id: number): void => {
    ctx.rowsRef.current = { ...ctx.rowsRef.current, [id]: { ...IDLE_ROW, pending: true } }
    setRow(id, { pending: true, error: null, announce: null })
  }

  const refused = (id: number, previous: GithubOrgMember, refusal: Refusal): void => {
    mapItems((items) => restoreRow(items, previous))
    setRow(id, { pending: false, error: refusal.problem, announce: null })
    if (refusal.stale === 'members') ctx.latest.current.onMembersStale()
    if (refusal.stale === 'link') ctx.latest.current.onLinkStale()
    if (refusal.stale === 'roster') void ctx.load(true)
  }

  return {
    retry: () => ctx.load(false),
    loadMore: () => loadMore(ctx),
    assign: async (githubId, teammate) => {
      const previous = find(githubId)
      if (!previous) return
      markPending(githubId)
      mapItems((items) => withAssignment(items, githubId, optimisticAssignment(teammate), 'member'))
      try {
        const assignment = await assignGithubMember(teamId, githubId, teammate.user_id)
        if (stale()) return
        mapItems((items) => withAssignment(items, githubId, assignment, 'member'))
        const vars = { login: previous.github_login, name: teammateName(teammate) }
        setRow(githubId, { pending: false, announce: { key: 'assign_done', vars } })
      } catch (error: unknown) {
        if (!stale()) refused(githubId, previous, assignRefusal(error, previous, teammate))
      }
    },
    unassign: async (githubId) => {
      const previous = find(githubId)
      if (!previous) return
      markPending(githubId)
      mapItems((items) => withAssignment(items, githubId, null, 'not_on_solus'))
      try {
        await unassignGithubMember(teamId, githubId)
        if (stale()) return
        const vars = { login: previous.github_login }
        setRow(githubId, { pending: false, announce: { key: 'unassign_done', vars } })
      } catch (error: unknown) {
        if (!stale()) refused(githubId, previous, commonRefusal(error))
      }
    },
    invite: async (member) => {
      if (!find(member.github_id)) return { ok: false, reason: 'failed' }
      markPending(member.github_id)
      return invite(ctx, setRow, member)
    }
  }
}

async function loadMore(ctx: ActionContext): Promise<void> {
  const { cursor } = ctx.pageRef.current
  if (!cursor) return
  const mine = ctx.seq.current
  ctx.setLoadingMore(true)
  try {
    const next = await listTeamGithubMembers(ctx.teamId, { cursor, limit: ROSTER_PAGE })
    if (mine !== ctx.seq.current || ctx.teamRef.current !== ctx.teamId) return
    // A refetch that landed meanwhile replaced the page: this cursor is stale.
    if (ctx.pageRef.current.cursor !== cursor) return
    ctx.setPage((prev) => ({
      items: appendUnique(prev.items, next.items),
      total: next.total,
      cursor: next.cursor
    }))
  } catch {
    // Keep what is loaded; Load more stays offered.
  } finally {
    ctx.setLoadingMore(false)
  }
}

async function invite(
  ctx: ActionContext,
  setRow: (id: number, row: Partial<RowState>) => void,
  member: GithubOrgMember
): Promise<MemberInviteOutcome> {
  const id = member.github_id
  const outcome = await ctx.latest.current.inviteMember(member)
  if (ctx.teamRef.current !== ctx.teamId) return outcome
  setRow(id, { pending: false, error: inviteProblem(outcome) })
  if (outcome.ok) {
    ctx.setPage((prev) => ({
      ...prev,
      items: prev.items.map((m) => (m.github_id === id ? { ...m, solus_status: 'invited' } : m))
    }))
  }
  return outcome
}

function inviteProblem(outcome: MemberInviteOutcome): RowProblem | null {
  if (outcome.ok) return null
  if (outcome.reason === 'plan_limit') return { limit: outcome.limit.message }
  const key = outcome.reason === 'not_an_org_member' ? 'not_an_org_member' : 'invite_failed'
  return { key, vars: {} }
}
