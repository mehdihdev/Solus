import { api, type ApiClient } from './client'

export interface DocumentTreeItem {
  id: string
  name: string
  kind: 'folder' | 'document'
  node: string | null
}
export interface DocumentTreePage {
  items: DocumentTreeItem[]
  next_offset: number | null
}
export async function listDocumentTree(
  connectionId: string,
  options: { node?: string; offset?: number; refresh?: boolean; cacheOnly?: boolean },
  client: ApiClient = api
): Promise<DocumentTreePage> {
  const query = new URLSearchParams()
  if (options.node !== undefined) query.set('node', options.node)
  if (options.offset !== undefined) query.set('offset', String(options.offset))
  if (options.refresh) query.set('refresh', 'true')
  if (options.cacheOnly) query.set('cache_only', 'true')
  const page = await client.request<unknown>(
    `/users/me/connections/${encodeURIComponent(connectionId)}/document-tree?${query.toString()}`
  )
  if (!validPage(page, options.offset ?? 0))
    throw new Error('Invalid document listing. Try refreshing documents.')
  return page
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function validItem(value: unknown): value is DocumentTreeItem {
  if (!record(value) || typeof value.id !== 'string' || typeof value.name !== 'string') return false
  if (value.kind === 'document') return value.node === null
  return value.kind === 'folder' && typeof value.node === 'string' && value.node.length > 0
}
function validPage(value: unknown, offset: number): value is DocumentTreePage {
  if (!record(value) || !Array.isArray(value.items) || !value.items.every(validItem)) return false
  const next = value.next_offset
  return (
    next === null ||
    (typeof next === 'number' && Number.isInteger(next) && next > offset && next <= 100000)
  )
}
