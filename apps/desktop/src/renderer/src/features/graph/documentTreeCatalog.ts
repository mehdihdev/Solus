import type { ApiClient } from '../../lib/api/client'
import { ApiError } from '../../lib/api/envelope.types'
import { listDocumentTree, type DocumentTreeItem } from '../../lib/api/resources.documentTree'

export interface TreeListing {
  status: 'loading' | 'ready' | 'missing' | 'error'
  items: DocumentTreeItem[]
  nextOffset: number | null
  error: string | null
}

export class DocumentTreeCatalog {
  private state: Record<string, TreeListing> = {}
  private listeners = new Set<() => void>()
  private pending = new Map<string, Promise<void>>()
  private disposed = false
  constructor(private client: ApiClient) {}
  snapshot = (): Record<string, TreeListing> => this.state
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  load(connectionId: string, node = 'root', refresh = false): Promise<void> {
    if (!refresh && this.state[`${connectionId}:${node}`]) return Promise.resolve()
    return this.fetch(connectionId, node, 0, refresh, node === 'root' && !refresh)
  }
  more(connectionId: string, node: string): Promise<void> {
    const offset = this.state[`${connectionId}:${node}`]?.nextOffset
    return offset == null ? Promise.resolve() : this.fetch(connectionId, node, offset)
  }
  private fetch(
    connectionId: string,
    node: string,
    offset: number,
    refresh = false,
    cacheOnly = false
  ): Promise<void> {
    if (this.disposed) return Promise.resolve()
    const key = `${connectionId}:${node}`
    const pending = this.pending.get(key)
    if (pending) return pending
    const previous = this.state[key] ?? { items: [], nextOffset: null, error: null }
    this.publish(key, { ...previous, status: 'loading', error: null })
    const options = {
      node,
      offset,
      ...(refresh ? { refresh: true } : {}),
      ...(cacheOnly ? { cacheOnly: true } : {})
    }
    const request = listDocumentTree(connectionId, options, this.client)
      .then((page) => {
        const items = offset === 0 ? page.items : [...previous.items, ...page.items]
        const unique = new Map(items.map((item) => [`${item.kind}:${item.id}`, item]))
        this.publish(key, {
          status: 'ready',
          items: [...unique.values()],
          nextOffset: page.next_offset,
          error: null
        })
      })
      .catch((error: unknown) =>
        this.publish(key, {
          ...previous,
          status:
            error instanceof ApiError && error.code === 'listing_not_cached' ? 'missing' : 'error',
          error: error instanceof Error ? error.message : 'Could not load documents.'
        })
      )
      .finally(() => this.pending.delete(key))
    this.pending.set(key, request)
    return request
  }
  private publish(key: string, listing: TreeListing): void {
    if (this.disposed) return
    this.state = { ...this.state, [key]: listing }
    this.listeners.forEach((listener) => listener())
  }
  dispose(): void {
    this.disposed = true
    this.state = {}
    this.listeners.clear()
  }
}
