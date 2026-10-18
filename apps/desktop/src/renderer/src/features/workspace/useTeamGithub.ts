// SOLUSDEV-216 / ADR-039: the active team's GitHub organization on Home —
// the installation, its repo count, and the link / unlink / roster / invite
// actions. Modelled on useHomeTeam: keyed on the team id, stale replies are
// dropped, state is immutable, and `team.updated` (ADR-037) refetches quietly.
import { useCallback, useEffect, useRef, useState } from 'react'
import { planLimitFromError, type PlanLimitRefusal } from '../../lib/api/planLimit'
import { createInvite } from '../../lib/api/resources'
import {
  completeGithubInstall,
  getTeamInstallation,
  githubOrgErrorCode,
  listTeamGithubMembers,
  listTeamGithubRepos,
  startGithubInstall,
  unlinkTeamInstallation,
  type GithubOrgMember,
  type TeamInstallation
} from '../../lib/api/resources.teamGithub'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { liveKeys } from '../../store/liveRevisionStore'
import { useLiveRefetch } from '../live/useLiveRefetch'
import { runGithubInstall, type InstallOutcome } from './githubInstallFlow'

export type TeamGithubStatus = 'idle' | 'loading' | 'ready' | 'offline'

/** The last link attempt's non-success verdict, shown inline on the card. */
export type LinkNotice = Exclude<InstallOutcome, { kind: 'linked' }>

export type UnlinkOutcome = { ok: true; disabledSources: number; manageUrl: string } | { ok: false }
export type RosterOutcome =
  | { ok: true; items: GithubOrgMember[]; cursor: string | null }
  | { ok: false }
export type MemberInviteOutcome =
  | { ok: true; token: string | null }
  | { ok: false; reason: 'not_an_org_member' | 'failed' }
  | { ok: false; reason: 'plan_limit'; limit: PlanLimitRefusal }

export interface TeamGithubActions {
  link: () => Promise<void>
  unlink: () => Promise<UnlinkOutcome>
  loadRoster: (cursor?: string) => Promise<RosterOutcome>
  inviteMember: (member: GithubOrgMember) => Promise<MemberInviteOutcome>
  refresh: () => Promise<void>
}

export interface TeamGithub {
  status: TeamGithubStatus
  installation: TeamInstallation | null
  /** `meta.total` of the repos listing (docs/api/github-orgs.md §6); null if unknown. */
  repoCount: number | null
  /** The server has no GitHub App configured — the card says so, quietly. */
  unconfigured: boolean
  linking: boolean
  notice: LinkNotice | null
  actions: TeamGithubActions
}

interface Snapshot {
  installation: TeamInstallation | null
  repoCount: number | null
  unconfigured: boolean
}

const EMPTY: Snapshot = { installation: null, repoCount: null, unconfigured: false }

async function fetchSnapshot(teamId: string): Promise<Snapshot> {
  let installation: TeamInstallation | null
  try {
    installation = await getTeamInstallation(teamId)
  } catch (error: unknown) {
    if (githubOrgErrorCode(error) === 'github_app_unconfigured') {
      return { ...EMPTY, unconfigured: true }
    }
    throw error
  }
  if (!installation) return EMPTY
  const repoCount = await listTeamGithubRepos(teamId, { limit: 1 })
    .then((page) => page.total)
    .catch(() => null)
  return { installation, repoCount, unconfigured: false }
}

function inviteRefusal(error: unknown): MemberInviteOutcome {
  const limit = planLimitFromError(error)
  if (limit) return { ok: false, reason: 'plan_limit', limit }
  if (githubOrgErrorCode(error) === 'not_an_org_member') {
    return { ok: false, reason: 'not_an_org_member' }
  }
  return { ok: false, reason: 'failed' }
}

/** `teamId` is null on the personal team and when there is no active team. */
export function useTeamGithub(teamId: string | null): TeamGithub {
  const [status, setStatus] = useState<TeamGithubStatus>(teamId ? 'loading' : 'idle')
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY)
  const [linking, setLinking] = useState(false)
  const [notice, setNotice] = useState<LinkNotice | null>(null)
  const loadSeq = useRef(0)
  const teamIdRef = useRef(teamId)
  const statusRef = useRef(status)
  const linkingRef = useRef(false)
  useEffect(() => {
    teamIdRef.current = teamId
  }, [teamId])
  useEffect(() => {
    statusRef.current = status
    linkingRef.current = linking
  }, [status, linking])
  // Leaving mid-link aborts the browser handshake so main stops waiting.
  useEffect(
    () => () => {
      if (linkingRef.current) void getDesktopOAuthBridge()?.cancelOAuth?.()
    },
    []
  )
  // Read lazily (after an await), so a team switch mid-flight drops the result.
  const currentTeamId = useCallback(() => teamIdRef.current, [])

  /** `quiet` keeps what is on screen while refetching (a live hint, a link). */
  const load = useCallback(
    async (quiet: boolean): Promise<void> => {
      const seq = ++loadSeq.current
      if (!teamId) {
        setStatus('idle')
        setSnapshot(EMPTY)
        return
      }
      if (!quiet) {
        setStatus('loading')
        setSnapshot(EMPTY)
      }
      try {
        const next = await fetchSnapshot(teamId)
        if (seq !== loadSeq.current || teamIdRef.current !== teamId) return
        setSnapshot(next)
        setStatus('ready')
      } catch {
        if (seq !== loadSeq.current || teamIdRef.current !== teamId) return
        if (!quiet) setStatus('offline')
      }
    },
    [teamId]
  )

  useEffect(() => {
    setNotice(null)
    setLinking(false)
    void load(false)
  }, [load])
  useLiveRefetch([teamId ? liveKeys.team(teamId) : null], () => void load(true), teamId !== null)

  const actions = createActions({
    teamId,
    currentTeamId,
    load,
    // A Retry from the offline note shows the loading state; anything else is quiet.
    isOffline: () => statusRef.current === 'offline',
    setLinking,
    setNotice,
    clearSnapshot: () => setSnapshot(EMPTY)
  })
  return { status, ...snapshot, linking, notice, actions }
}

interface ActionContext {
  teamId: string | null
  currentTeamId: () => string | null
  load: (quiet: boolean) => Promise<void>
  isOffline: () => boolean
  setLinking: (value: boolean) => void
  setNotice: (value: LinkNotice | null) => void
  clearSnapshot: () => void
}

function createActions({
  teamId,
  currentTeamId,
  load,
  isOffline,
  setLinking,
  setNotice,
  clearSnapshot
}: ActionContext): TeamGithubActions {
  return {
    link: async () => {
      if (!teamId) return
      setNotice(null)
      setLinking(true)
      const bridge = getDesktopOAuthBridge()
      const outcome = await runGithubInstall(
        { start: startGithubInstall, complete: completeGithubInstall, bridge },
        teamId
      )
      setLinking(false)
      if (currentTeamId() !== teamId) return
      if (outcome.kind === 'linked') await load(true)
      else setNotice(outcome)
    },
    unlink: async () => {
      if (!teamId) return { ok: false }
      try {
        const result = await unlinkTeamInstallation(teamId)
        const unlinked = {
          ok: true as const,
          disabledSources: result.disabled_sources,
          manageUrl: result.manage_url
        }
        if (currentTeamId() !== teamId) return unlinked
        // Show "unlinked" now; the quiet refetch only confirms it.
        clearSnapshot()
        void load(true)
        return unlinked
      } catch {
        return { ok: false }
      }
    },
    loadRoster: async (cursor) => {
      if (!teamId) return { ok: false }
      try {
        const page = await listTeamGithubMembers(teamId, cursor ? { cursor } : {})
        return { ok: true, items: page.items, cursor: page.cursor }
      } catch {
        return { ok: false }
      }
    },
    inviteMember: async (member) => {
      if (!teamId) return { ok: false, reason: 'failed' }
      try {
        const invite = await createInvite(teamId, {
          github_user_id: member.github_id,
          github_login: member.github_login,
          role: 'member'
        })
        return { ok: true, token: invite.token ?? null }
      } catch (error: unknown) {
        return inviteRefusal(error)
      }
    },
    refresh: () => load(!isOffline())
  }
}
