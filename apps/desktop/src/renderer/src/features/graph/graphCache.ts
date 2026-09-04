// The Context Model's entity list, retained across screen switches (SOLUSDEV-234).
//
// `useGraphSummary` used to re-walk every 500-row page of the project on each
// mount, and the Graph screen mounts on every visit — six or seven requests
// per click on a modest project, the single biggest burst in the desktop's
// API traffic. The list only changes when the graph does, and the project
// detail (one request) already says whether it did: entity/relation counts
// plus each source's sync/update stamps. So the detail is always re-fetched
// and acts as the validator; the page walk repeats only when that version
// string differs or the entry is older than the TTL (a backstop for edits the
// counts cannot see, e.g. a rename).
//
// Pure functions over an explicit Map so the policy is testable without
// React; the module-level instance is what the hook uses.
import type { Entity, ProjectDetail } from '../../lib/api/resources'

export const GRAPH_CACHE_TTL_MS = 5 * 60_000

export interface GraphCounts {
  readonly entityCount: number
  readonly relationCount: number
  readonly sourceCount: number
}

export interface GraphCacheEntry {
  readonly version: string
  readonly entities: readonly Entity[]
  /** Counts as of the walk, so a remount can render the retained list with honest numbers. */
  readonly counts: GraphCounts
  readonly fetchedAtMs: number
}

export function countsOf(detail: ProjectDetail): GraphCounts {
  return {
    entityCount: detail.stats.entities,
    relationCount: detail.stats.relations,
    sourceCount: detail.sources.length
  }
}

interface SourceStamp {
  id?: unknown
  last_synced_at?: unknown
  updated_at?: unknown
}

/** What the entity list depends on, from the detail payload alone. */
export function graphVersionOf(detail: ProjectDetail): string {
  const stamps = detail.sources.map((s) => {
    const { id, last_synced_at, updated_at } = (s ?? {}) as SourceStamp
    return [id, last_synced_at, updated_at]
  })
  return JSON.stringify([detail.stats.entities, detail.stats.relations, stamps])
}

export function isGraphCacheValid(
  entry: GraphCacheEntry | undefined,
  detail: ProjectDetail,
  nowMs: number
): entry is GraphCacheEntry {
  if (!entry) return false
  return entry.version === graphVersionOf(detail) && nowMs - entry.fetchedAtMs < GRAPH_CACHE_TTL_MS
}

export type GraphCache = Map<string, GraphCacheEntry>

export const graphCache: GraphCache = new Map()
