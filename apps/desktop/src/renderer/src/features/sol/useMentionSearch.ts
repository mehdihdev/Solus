// SOLUSDEV-168 — entity lookup for the composer's `@` typeahead.
//
// SOLUSDEV-320 repointed it at the project search index through the hook ⌘K
// shares (debounce, stale guard, cache and view invalidation all live there).
// Rows keep the Entity shape the picker and MentionList consume; a `.solus`
// hit mentions the entity it describes, so one without an entity is dropped.
import { useMemo } from 'react'
import type { Entity } from '../../lib/api/resources'
import { useProjectSearch } from '../workspace/useProjectSearch'

export { SEARCH_DEBOUNCE_MS as MENTION_DEBOUNCE_MS } from '../workspace/useProjectSearch'
/** A typeahead, not a browser — one short list the user can scan. */
export const MENTION_LIMIT = 8

export function useMentionSearch(projectId: string | null, query: string | null): Entity[] {
  const { entities, solus } = useProjectSearch(projectId, query, {
    scope: 'all',
    limit: MENTION_LIMIT
  })
  return useMemo(() => {
    // The snippet is the matched text — the stored path for a code file — so two files
    // that share a name still read apart in the list (MentionList shows it under the name).
    const rows: Entity[] = entities.map((hit) => ({
      id: hit.id,
      name: hit.name,
      type: hit.kind,
      domain: hit.domain,
      source_key: hit.snippet || null
    }))
    const seen = new Set(rows.map((row) => row.id))
    for (const hit of solus) {
      if (hit.entity_id === null || seen.has(hit.entity_id)) continue
      seen.add(hit.entity_id)
      rows.push({
        id: hit.entity_id,
        name: hit.name,
        type: 'solus_entry',
        domain: 'project',
        source_key: null
      })
    }
    return rows
  }, [entities, solus])
}
