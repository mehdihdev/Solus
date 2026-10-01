// Fold a freshly fetched first page of a newest-first feed (activity,
// notifications) into what the user has already scrolled through, so a live
// refresh never loses "load more" progress.
// Pure. The feed is newest-first with an opaque cursor that points just past the
// OLDEST loaded item, so that cursor stays valid as newer rows arrive on top.
import type { ApiMeta } from '../../lib/api/envelope.types'

export interface Feed<T extends { id: string }> {
  items: readonly T[]
  meta: ApiMeta
}

export function mergeFirstPage<T extends { id: string }>(
  previous: Feed<T>,
  fresh: { data: readonly T[]; meta: ApiMeta }
): { items: T[]; meta: ApiMeta } {
  const replace = { items: [...fresh.data], meta: fresh.meta }
  const freshIds = new Set(fresh.data.map((item) => item.id))
  const overlaps = previous.items.some((item) => freshIds.has(item.id))
  // No overlap means a whole page of news arrived: stitching would leave a gap.
  if (!overlaps) return replace
  const older = previous.items.filter((item) => !freshIds.has(item.id))
  return {
    items: [...fresh.data, ...older],
    meta: {
      ...fresh.meta,
      has_next: previous.meta.has_next,
      next_cursor: previous.meta.next_cursor
    }
  }
}

export const mergeActivityRefresh = mergeFirstPage
