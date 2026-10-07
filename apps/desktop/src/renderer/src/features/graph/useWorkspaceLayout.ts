import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import { apiBaseUrl, createApiClient, type ApiClient } from '../../lib/api/client'
import { useAuthStore } from '../../store/authStore'
import { liveKeys, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { useLiveRefetch } from '../live/useLiveRefetch'
import {
  getWorkspaceLayout,
  saveWorkspaceLayout,
  type Point,
  type WorkspaceLayout
} from '../../lib/api/workspace'

/** `auto`: default placement the app wrote itself; `user`: a drag or deliberate placement. */
export type MoveOrigin = 'user' | 'auto'
type Status = 'loading' | 'ready' | 'saving' | 'error' | 'offline'
interface Identity {
  token: string | null
  email: string | undefined
}
interface LayoutView {
  projectId: string | null
  identity: Identity | null
  positions: Record<string, Point>
  status: Status
  error: string | null
}
const EMPTY: LayoutView = {
  projectId: null,
  identity: null,
  positions: {},
  status: 'offline',
  error: null
}

function sameIdentity(identity: Identity): boolean {
  const auth = useAuthStore.getState()
  return auth.accessToken === identity.token && auth.user?.email === identity.email
}

function sameIds(a: ReadonlySet<string> | null, b: ReadonlySet<string> | null): boolean {
  if (a === null || b === null) return a === b
  return a.size === b.size && [...a].every((id) => b.has(id))
}

/** Disposal stops publication; already authorized writes drain under the captured identity. */
class LayoutSession {
  private attached = true
  private busy = false
  private layout: WorkspaceLayout | null = null
  private pending: Record<string, Point> = {}
  /** Pending ids whose latest write was default placement, not a user move. */
  private autoIds = new Set<string>()
  private liveIds: ReadonlySet<string> | null
  private removedIds = new Set<string>()
  private status: Status = 'loading'
  private error: string | null = null
  private client: ApiClient
  /** Newest remote layout version a live hint has named (ADR-037). */
  private seenVersion = 0
  private reconciling = false

  constructor(
    private projectId: string,
    private identity: Identity,
    private publish: (view: LayoutView) => void,
    liveEntityIds?: readonly string[]
  ) {
    this.liveIds = liveEntityIds ? new Set(liveEntityIds) : null
    this.client = createApiClient({
      baseUrl: apiBaseUrl,
      getToken: () => {
        if (!sameIdentity(identity)) throw new Error('The layout session has ended')
        return identity.token
      }
    })
  }

  private prune(positions: Record<string, Point>): Record<string, Point> {
    return Object.fromEntries(Object.entries(positions).filter(([id]) => !this.removedIds.has(id)))
  }

  private isLive(id: string): boolean {
    return this.liveIds === null || this.liveIds.has(id)
  }

  private accept(layout: WorkspaceLayout): void {
    this.layout = { ...layout, positions: this.prune(layout.positions) }
  }

  setLiveEntityIds(ids: readonly string[] | undefined): void {
    const next = ids ? new Set(ids) : null
    if (sameIds(next, this.liveIds)) return
    // A fresh authorized layout can contain a teammate's newly added node that
    // our graph snapshot has not seen yet. Only known removals are tombstones.
    if (next) {
      for (const id of this.liveIds ?? []) if (!next.has(id)) this.removedIds.add(id)
      for (const id of next) this.removedIds.delete(id)
    }
    this.liveIds = next
    this.pending = this.prune(this.pending)
    this.forgetSettledAutos()
    if (this.layout) this.accept(this.layout)
    this.show(this.status, this.error)
  }

  private show(status: Status, error: string | null = null): void {
    this.status = status
    this.error = error
    if (this.attached && sameIdentity(this.identity))
      this.publish({
        projectId: this.projectId,
        identity: this.identity,
        positions: this.prune({ ...this.layout?.positions, ...this.pending }),
        status,
        error
      })
  }

  async load(): Promise<void> {
    try {
      const layout = await getWorkspaceLayout(this.projectId, this.client)
      if (!this.attached || !sameIdentity(this.identity)) return
      this.accept(layout)
      this.show('ready')
      void this.reconcile()
    } catch {
      this.show('error', 'Could not load saved positions. Retry to enable dragging.')
    }
  }

  /** A live `layout.changed` named this version. Never throws; never drops moves. */
  observeRemoteVersion(version: number): void {
    this.seenVersion = Math.max(this.seenVersion, version)
    void this.reconcile()
  }

  /**
   * Catch up with a teammate's newer layout. Unsaved moves stay layered over the
   * fresh positions (and the fresh version becomes ours), so the next save is
   * based on the latest version and does not 409. A save in flight owns the
   * version, so it defers us: its own 409 path, or the re-check after it
   * settles, covers a teammate who got there first.
   */
  private async reconcile(): Promise<void> {
    if (!this.needsReconcile()) return
    this.reconciling = true
    const target = this.seenVersion
    try {
      await this.applyLatest()
    } catch {
      /* Keep what is on screen; the next hint retries. */
    } finally {
      this.reconciling = false
    }
    if (this.seenVersion > target) void this.reconcile()
  }

  private needsReconcile(): boolean {
    if (this.reconciling || this.busy || !this.layout || !this.canPublish()) return false
    return this.seenVersion > this.layout.version
  }

  private async applyLatest(): Promise<void> {
    const latest = await getWorkspaceLayout(this.projectId, this.client)
    if (!this.canPublish() || !this.layout) return
    const adopted = !this.busy && latest.version > this.layout.version
    if (adopted) this.accept(latest)
    // A banner is about unsaved USER moves; once the newest layout is ours and
    // none remain, it no longer describes anything.
    if (adopted && this.status === 'error' && !this.hasUserMoves(this.pending)) {
      this.dropAutoPending()
      this.show('ready')
      return
    }
    this.show(this.status, this.error)
  }

  private hasUserMoves(moves: Record<string, Point>): boolean {
    return Object.keys(moves).some((id) => !this.autoIds.has(id))
  }

  private forgetSettledAutos(): void {
    for (const id of this.autoIds) if (!(id in this.pending)) this.autoIds.delete(id)
  }

  private dropAutoPending(): void {
    this.pending = Object.fromEntries(
      Object.entries(this.pending).filter(([id]) => !this.autoIds.has(id))
    )
    this.autoIds.clear()
  }

  private canPublish(): boolean {
    return this.attached && sameIdentity(this.identity)
  }

  move(entityId: string, point: Point, origin: MoveOrigin = 'user'): void {
    if (!this.attached || !this.layout || !this.isLive(entityId) || !sameIdentity(this.identity))
      return
    this.pending = { ...this.pending, [entityId]: point }
    if (origin === 'auto') this.autoIds.add(entityId)
    else this.autoIds.delete(entityId)
    this.show('saving')
    void this.flush()
  }

  private async failedSave(error: unknown, moves: Record<string, Point>): Promise<void> {
    if (!sameIdentity(this.identity)) return
    this.pending = this.prune({ ...moves, ...this.pending })
    if (!(error instanceof ApiError) || error.status !== 409) {
      this.show('error', 'Positions could not be saved. Retry to save your moved nodes.')
      return
    }
    let adopted = false
    try {
      this.accept(await getWorkspaceLayout(this.projectId, this.client))
      adopted = true
    } catch {
      /* Keep the unsaved moves for explicit retry. */
    }
    // Two clients opening a new project both write default placement; the
    // loser moved nothing, so the winner's layout simply stands (no banner).
    if (adopted && !this.hasUserMoves(this.pending)) {
      this.dropAutoPending()
      this.show('ready')
      return
    }
    this.show('error', 'Layout changed elsewhere. Retry to save your moved nodes.')
  }

  async flush(): Promise<void> {
    if (!sameIdentity(this.identity) || this.busy || !this.layout) return
    const moves = this.prune(this.pending)
    if (!Object.keys(moves).length) return
    this.busy = true
    this.pending = {}
    const body = {
      version: this.layout.version,
      positions: this.prune({ ...this.layout.positions, ...moves })
    }
    this.layout = body
    this.show('saving')
    let saved = false
    try {
      const layout = await saveWorkspaceLayout(this.projectId, body, this.client)
      if (!sameIdentity(this.identity)) return
      this.accept(layout)
      this.forgetSettledAutos()
      saved = true
    } catch (error) {
      await this.failedSave(error, moves)
    } finally {
      this.busy = false
    }
    void this.reconcile()
    if (saved) {
      this.show(Object.keys(this.pending).length ? 'saving' : 'ready')
      await this.flush()
    }
  }

  retry(): void {
    if (!this.layout) void this.load()
    else void this.flush()
  }
  dispose(): void {
    this.attached = false
  }
}

/** Optimistic positions, serialized writes and explicit conflict retry. */
export function useWorkspaceLayout(
  projectId: string | null,
  enabled: boolean,
  liveEntityIds?: readonly string[]
): {
  positions: Record<string, Point>
  status: Status
  error: string | null
  move: (entityId: string, point: Point, origin?: MoveOrigin) => void
  retry: () => void
} {
  const token = useAuthStore((state) => state.accessToken)
  const email = useAuthStore((state) => state.user?.email)
  const identity = useMemo(() => ({ token, email }), [token, email])
  const [view, setView] = useState(EMPTY)
  const session = useRef<LayoutSession | null>(null)
  const liveIdsRef = useRef(liveEntityIds)
  useEffect(() => {
    liveIdsRef.current = liveEntityIds
    session.current?.setLiveEntityIds(liveEntityIds)
  }, [liveEntityIds])
  useEffect(() => {
    if (!projectId || !enabled) return
    const current = new LayoutSession(projectId, identity, setView, liveIdsRef.current)
    session.current = current
    void current.load()
    return () => {
      current.dispose()
      session.current = null
    }
  }, [projectId, enabled, identity])
  useLiveRefetch(
    [projectId ? liveKeys.projectLayout(projectId) : null],
    () => {
      const version = projectId
        ? useLiveRevisionStore.getState().layoutVersions[projectId]
        : undefined
      if (version !== undefined) session.current?.observeRemoteVersion(version)
    },
    enabled && projectId !== null
  )
  const move = useCallback((id: string, point: Point, origin?: MoveOrigin) => {
    session.current?.move(id, point, origin)
  }, [])
  const retry = useCallback(() => {
    session.current?.retry()
  }, [])
  const current = !enabled
    ? EMPTY
    : view.projectId === projectId && view.identity === identity
      ? view
      : { ...EMPTY, status: 'loading' as const }
  return { positions: current.positions, status: current.status, error: current.error, move, retry }
}
