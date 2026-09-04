// SOLUSDEV-168 — entity lookup for the composer's `@` typeahead.
//
// Same shape as useClassifyPreview, and for the same reasons: debounce so we
// never search per keystroke, a `seq` ref so a slow response cannot overwrite a
// newer one, and a swallowed failure — a search hiccup must never block the
// person from sending their message.
//
// It queries the server's `q` filter rather than paging the project client-side
// (`listAllEntities` walks every page). `q` is escaped server-side, so a `%` the
// user types is literal.
import { useEffect, useRef, useState } from 'react'
import { listEntities, type Entity } from '../../lib/api/resources'

export const MENTION_DEBOUNCE_MS = 400
/** A typeahead, not a browser — one short list the user can scan. */
export const MENTION_LIMIT = 8

export function useMentionSearch(projectId: string | null, query: string | null): Entity[] {
  const [results, setResults] = useState<Entity[]>([])
  const seq = useRef(0)

  useEffect(() => {
    // Any change invalidates whatever is in flight immediately, not just when
    // the next timer fires — otherwise a slow response repopulates a list the
    // user has already typed past.
    seq.current += 1
    if (projectId === null || query === null) {
      setResults([])
      return
    }
    const mine = seq.current
    const timer = setTimeout(() => {
      listEntities(projectId, { q: query, limit: MENTION_LIMIT })
        .then((rows) => {
          if (seq.current === mine) setResults(rows)
        })
        .catch(() => {
          if (seq.current === mine) setResults([])
        })
    }, MENTION_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [projectId, query])

  return results
}
