import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import { apiBaseUrl, createApiClient, type ApiClient } from '../../lib/api/client'
import { useAuthStore } from '../../store/authStore'
import {
  getWorkspaceLayout,
  saveWorkspaceLayout,
  type Point,
  type WorkspaceLayout
} from '../../lib/api/workspace'

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
  private liveIds: ReadonlySet<string> | null
  private removedIds = new Set<string>()
  private status: Status = 'loading'
  private error: string | null = null
  private client: ApiClient

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
    } catch {
      this.show('error', 'Could not load saved positions. Retry to enable dragging.')
    }
  }

  move(entityId: string, point: Point): void {
    if (!this.attached || !this.layout || !this.isLive(entityId) || !sameIdentity(this.identity))
      return
    this.pending = { ...this.pending, [entityId]: point }
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
    try {
      this.accept(await getWorkspaceLayout(this.projectId, this.client))
    } catch {
      /* Keep the unsaved moves for explicit retry. */
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
      saved = true
    } catch (error) {
      await this.failedSave(error, moves)
    } finally {
      this.busy = false
    }
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
  move: (entityId: string, point: Point) => void
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
  const move = useCallback((id: string, point: Point) => {
    session.current?.move(id, point)
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
