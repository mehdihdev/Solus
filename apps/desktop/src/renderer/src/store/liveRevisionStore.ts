// Live revision counters (ADR-037). A live frame is only a HINT: it bumps the
// revision of the data it names, and the REST hooks that read that data list
// the revision in their load trigger and refetch. Updates are immutable and
// bursts are coalesced so a flurry of frames costs one refetch, not twenty.
import { create } from 'zustand'

export const LIVE_COALESCE_MS = 250

export type AccountStreamStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'stopped'

const TEAM_PREFIX = 'team:'

export const liveKeys = {
  me: 'me',
  teams: 'teams',
  notifications: 'notifications',
  team: (id: string): string => `${TEAM_PREFIX}${id}`,
  teamMembers: (id: string): string => `${TEAM_PREFIX}${id}:members`,
  teamInvites: (id: string): string => `${TEAM_PREFIX}${id}:invites`,
  teamProjects: (id: string): string => `${TEAM_PREFIX}${id}:projects`,
  teamActivity: (id: string): string => `${TEAM_PREFIX}${id}:activity`,
  projectDetail: (id: string): string => `project:${id}`,
  projectSources: (id: string): string => `project:${id}:sources`,
  projectLayout: (id: string): string => `project:${id}:layout`,
  projectJobs: (id: string): string => `project:${id}:jobs`,
  /** Every per-team key (detail, members, invites, projects, activity). */
  isTeamKey: (key: string): boolean => key.startsWith(TEAM_PREFIX)
}

type KeyPredicate = (key: string) => boolean

interface LiveRevisionState {
  revisions: Readonly<Record<string, number>>
  /** Newest `layout.changed` version seen per project id. */
  layoutVersions: Readonly<Record<string, number>>
  accountStream: AccountStreamStatus
  bump: (keys: readonly string[]) => void
  bumpWhere: (predicate: KeyPredicate) => void
  recordLayoutVersion: (projectId: string, version: number) => void
  setAccountStream: (status: AccountStreamStatus) => void
}

interface Pending {
  keys: Set<string>
  predicates: KeyPredicate[]
}

let pending: Pending = { keys: new Set(), predicates: [] }
let timer: ReturnType<typeof setTimeout> | undefined

function nextRevisions(
  current: Readonly<Record<string, number>>,
  batch: Pending
): Readonly<Record<string, number>> | null {
  const targets = new Set(batch.keys)
  for (const key of Object.keys(current)) {
    if (batch.predicates.some((matches) => matches(key))) targets.add(key)
  }
  if (targets.size === 0) return null
  const next: Record<string, number> = { ...current }
  for (const key of targets) next[key] = (current[key] ?? 0) + 1
  return Object.freeze(next)
}

function schedule(flush: () => void): void {
  if (timer !== undefined) return
  timer = setTimeout(() => {
    timer = undefined
    flush()
  }, LIVE_COALESCE_MS)
}

export const useLiveRevisionStore = create<LiveRevisionState>()((set, get) => {
  const flush = (): void => {
    const batch = pending
    pending = { keys: new Set(), predicates: [] }
    const revisions = nextRevisions(get().revisions, batch)
    if (revisions) set({ revisions })
  }
  return {
    revisions: Object.freeze({}),
    layoutVersions: Object.freeze({}),
    accountStream: 'idle',
    bump: (keys) => {
      if (keys.length === 0) return
      for (const key of keys) pending.keys.add(key)
      schedule(flush)
    },
    bumpWhere: (predicate) => {
      pending.predicates.push(predicate)
      schedule(flush)
    },
    recordLayoutVersion: (projectId, version) => {
      const known = get().layoutVersions[projectId]
      if (known !== undefined && known >= version) return
      set({ layoutVersions: Object.freeze({ ...get().layoutVersions, [projectId]: version }) })
    },
    setAccountStream: (accountStream) => set({ accountStream })
  }
})

/** The revision of one live key (0 until a frame names it). `null` is a key-less no-op. */
export function useLiveRevision(key: string | null): number {
  return useLiveRevisionStore((state) => (key === null ? 0 : (state.revisions[key] ?? 0)))
}

/** Test seam: clear all state and any queued bumps. */
export function resetLiveRevisions(): void {
  if (timer !== undefined) clearTimeout(timer)
  timer = undefined
  pending = { keys: new Set(), predicates: [] }
  useLiveRevisionStore.setState({
    revisions: Object.freeze({}),
    layoutVersions: Object.freeze({}),
    accountStream: 'idle'
  })
}
