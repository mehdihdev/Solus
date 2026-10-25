// Search client (SOLUSDEV-320). Hand-written to docs/api/search.md §3, the way
// `findings.ts` and `resources.ts` hand-write their rows: the generated schema
// lags the route plan until the API lands.
import { api, type ApiClient } from './client'

export type SearchWhy = 'name_match' | 'text_match' | 'ref_match'
export type SearchScope = 'entities' | 'solus' | 'all'

/** A `graph_entity` row ranked by `services/search.py:search_entities`. */
export interface EntityHit {
  id: string
  kind: string
  domain: string
  name: string
  snippet: string
  score: number
  why: SearchWhy
}

/** A `solus_entries` row; `entity_id` is the graph node the entry describes, if any. */
export interface SolusHit {
  id: string
  entity_id: string | null
  section: string
  subsection: string | null
  kind: string
  name: string
  snippet: string
  score: number
  why: SearchWhy
}

export interface SearchResponse {
  entities: EntityHit[]
  solus: SolusHit[]
  truncated: boolean
}

export interface SearchOptions {
  scope?: SearchScope
  kinds?: string[]
  domains?: string[]
  sections?: string[]
  /** 1..50 per group; the server defaults to 20. */
  limit?: number
  signal?: AbortSignal
}

const LIST_PARAMS = ['kinds', 'domains', 'sections'] as const

/** `GET /projects/{id}/search` — empty params are omitted, lists are comma-joined. */
export function searchProject(
  projectId: string,
  q: string,
  opts: SearchOptions = {},
  client: ApiClient = api
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q })
  if (opts.scope) params.set('scope', opts.scope)
  for (const key of LIST_PARAMS) {
    const values = opts[key]
    if (values?.length) params.set(key, values.join(','))
  }
  if (opts.limit !== undefined) params.set('limit', String(opts.limit))
  return client.request<SearchResponse>(
    `/projects/${projectId}/search?${params.toString()}`,
    opts.signal ? { signal: opts.signal } : undefined
  )
}
