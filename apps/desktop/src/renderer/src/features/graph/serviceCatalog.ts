import type { ApiClient } from '../../lib/api/client'
import { DocumentTreeCatalog } from './documentTreeCatalog'
import { ApiError } from '../../lib/api/envelope.types'
import {
  listConnections,
  listConnectionDocuments,
  type Connection,
  type SelectableItem
} from '../../lib/api/resources'

export interface DocumentListing {
  status: 'loading' | 'ready' | 'missing' | 'error'
  items: SelectableItem[]
  fetchedAt: string | null
  error: string | null
}
export interface CatalogSnapshot {
  status: 'idle' | 'loading' | 'ready' | 'error'
  accounts: Connection[]
  error: string | null
  documents: Record<string, DocumentListing>
}
const empty = (): CatalogSnapshot => ({ status: 'idle', accounts: [], error: null, documents: {} })
const message = (error: unknown): string =>
  error instanceof Error ? error.message : 'Could not load the listing.'

/** An account-scoped in-memory view of I1; only explicit refresh may populate its server cache. */
export class ServiceCatalog {
  private state = empty()
  private disposed = false
  private listeners = new Set<() => void>()
  private pending = new Map<string, Promise<void>>()
  readonly tree: DocumentTreeCatalog
  constructor(private client: ApiClient) {
    this.tree = new DocumentTreeCatalog(client)
  }
  snapshot = (): CatalogSnapshot => this.state
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  private publish(state: CatalogSnapshot): void {
    if (this.disposed) return
    this.state = state
    this.listeners.forEach((listener) => listener())
  }
  dispose(): void {
    this.tree.dispose()
    this.state = empty()
    this.disposed = true
    this.listeners.clear()
  }
  loadAccounts(refresh = false): Promise<void> {
    if (this.disposed) return Promise.resolve()
    const pending = this.pending.get('accounts')
    if (pending) return pending
    if (!refresh && this.state.status !== 'idle') return Promise.resolve()
    this.publish({ ...this.state, status: 'loading', error: null })
    const request = listConnections(this.client)
      .then(
        (accounts) => this.publish({ ...this.state, status: 'ready', accounts }),
        (error: unknown) => this.publish({ ...this.state, status: 'error', error: message(error) })
      )
      .finally(() => this.pending.delete('accounts'))
    this.pending.set('accounts', request)
    return request
  }
  loadDocuments(connectionId: string, refresh = false): Promise<void> {
    if (this.disposed) return Promise.resolve()
    const key = `documents:${connectionId}`
    const pending = this.pending.get(key)
    if (pending) return pending
    if (!refresh && this.state.documents[connectionId]) return Promise.resolve()
    this.setListing(connectionId, { status: 'loading', items: [], fetchedAt: null, error: null })
    const request = listConnectionDocuments(
      connectionId,
      refresh ? { refresh: true } : { cacheOnly: true },
      this.client
    )
      .then(
        (listing) =>
          this.setListing(connectionId, {
            status: 'ready',
            items: listing.items,
            fetchedAt: listing.fetched_at,
            error: null
          }),
        (error: unknown) =>
          this.setListing(connectionId, {
            status:
              error instanceof ApiError && error.code === 'listing_not_cached'
                ? 'missing'
                : 'error',
            items: [],
            fetchedAt: null,
            error: message(error)
          })
      )
      .finally(() => this.pending.delete(key))
    this.pending.set(key, request)
    return request
  }
  private setListing(id: string, listing: DocumentListing): void {
    this.publish({ ...this.state, documents: { ...this.state.documents, [id]: listing } })
  }
}
