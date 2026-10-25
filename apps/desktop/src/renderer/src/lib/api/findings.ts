// Findings client (SOLUSDEV-320). Hand-written to docs/api/findings.md §3, the way
// `resources.ts` hand-writes Entity: the generated schema lags the route plan.
import type { Severity } from '@solus/shared-types'
import { api, type ApiClient } from './client'

export type FindingStatus = 'open' | 'acknowledged' | 'dismissed' | 'resolved'

/** Wire shape of `serialize_finding`. */
export interface Finding {
  id: string
  rule_id: string
  severity: Severity
  source: string
  status: FindingStatus
  headline: string
  explanation: string
  detail: string | null
  /** Entity ids the finding observes. */
  subjects: string[]
  evidence: Record<string, unknown>
  count: number
  first_seen: string
  last_seen: string
  matrix_cell: string | null
  domain: string | null
  dismissed_until: string | null
  created_at: string
  updated_at: string
}

export interface FindingFilters {
  status?: FindingStatus
  severity?: Severity
  subject?: string
  robot?: string
}

const PAGE_LIMIT = '500'

function findingsQuery(filters: FindingFilters, cursor: string | null): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
  params.set('limit', PAGE_LIMIT)
  if (cursor) params.set('cursor', cursor)
  return params.toString()
}

/** The next page's cursor, or null at the end; a missing or repeated cursor is refused. */
function nextCursor(
  meta: { has_next?: boolean; next_cursor?: string | null },
  seen: Set<string>
): string | null {
  if (!meta.has_next) return null
  const cursor = meta.next_cursor ?? null
  if (!cursor || seen.has(cursor)) throw new Error('Invalid finding pagination cursor')
  seen.add(cursor)
  return cursor
}

/** Every finding matching the filters; walks the cursor like `listAllRelations`. */
export async function listFindings(
  projectId: string,
  filters: FindingFilters = {},
  client: ApiClient = api
): Promise<Finding[]> {
  const all: Finding[] = []
  const seen = new Set<string>()
  let cursor: string | null = null
  do {
    const query = findingsQuery(filters, cursor)
    const page = await client.requestPage<Finding[]>(`/projects/${projectId}/findings?${query}`)
    all.push(...page.data)
    cursor = nextCursor(page.meta, seen)
  } while (cursor)
  return all
}

export function resolveFinding(
  projectId: string,
  findingId: string,
  body: { note: string; fix_ref?: string },
  client: ApiClient = api
): Promise<Finding> {
  return client.request<Finding>(`/projects/${projectId}/findings/${findingId}/resolve`, {
    method: 'POST',
    body
  })
}

export function dismissFinding(
  projectId: string,
  findingId: string,
  body: { cooldown_hours?: number } = {},
  client: ApiClient = api
): Promise<Finding> {
  return client.request<Finding>(`/projects/${projectId}/findings/${findingId}/dismiss`, {
    method: 'POST',
    body
  })
}

export function acknowledgeFinding(
  projectId: string,
  findingId: string,
  client: ApiClient = api
): Promise<Finding> {
  return client.request<Finding>(`/projects/${projectId}/findings/${findingId}/acknowledge`, {
    method: 'POST'
  })
}
