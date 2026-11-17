// Project detail is the version validator for retained workspace snapshots.
import type { ProjectDetail } from '../../lib/api/resources'

export const GRAPH_CACHE_TTL_MS = 5 * 60_000

export interface GraphCounts {
  readonly entityCount: number
  readonly relationCount: number
  readonly sourceCount: number
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
  return JSON.stringify([
    detail.stats.entities,
    detail.stats.relations,
    detail.graph_updated_at,
    stamps
  ])
}
