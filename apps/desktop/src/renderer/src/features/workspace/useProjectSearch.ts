// SOLUSDEV-320 — the one search seam behind ⌘K and the `@` picker.
//
// Debounce so we never search per keystroke, a `seq` ref so a slow response
// cannot overwrite a newer one, a swallowed failure (a search hiccup must never
// block the palette or the composer), and a small module-level cache so the
// same query from either surface costs one round trip. The cache for a project
// is dropped when this user changes a repository view, so a renamed entity is
// found on the next query.
import { useEffect, useRef, useState } from 'react'
import {
  searchProject,
  type EntityHit,
  type SearchResponse,
  type SearchScope,
  type SolusHit
} from '../../lib/api/search'
import { onAccountEnd } from '../sol/solSessionStore'
import { useSourceViewVersion } from '../graph/sourceViewEvents'

export const SEARCH_DEBOUNCE_MS = 120
const CACHE_MAX = 200
/** `q` is 1..255 on the route (docs/api/search.md §3). */
const QUERY_MAX = 255

export interface ProjectSearch {
  entities: readonly EntityHit[]
  solus: readonly SolusHit[]
  pending: boolean
}

export interface ProjectSearchOptions {
  scope?: SearchScope
  limit?: number
}

const EMPTY_ENTITIES: readonly EntityHit[] = Object.freeze([])
const EMPTY_SOLUS: readonly SolusHit[] = Object.freeze([])
const EMPTY: SearchResponse = { entities: [], solus: [], truncated: false }

/** Keyed `${projectId}:${scope}:${limit}:${q}`; insertion order doubles as LRU. */
const cache = new Map<string, SearchResponse>()
// ponytail: one global generation, not per project — a clear for another
// project merely drops one cache write; the request result is still shown.
let generation = 0

export function clearSearchCache(projectId?: string): void {
  generation += 1
  if (projectId === undefined) {
    cache.clear()
    return
  }
  for (const key of cache.keys()) if (key.startsWith(`${projectId}:`)) cache.delete(key)
}

// Search results are project content; they must not outlive the account.
onAccountEnd(() => clearSearchCache())

// ponytail: insert-order eviction, a real LRU would re-insert on read.
function remember(key: string, value: SearchResponse): void {
  cache.set(key, value)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}

interface SearchKeys {
  query: string
  cacheKey: string | null
  resultKey: string | null
}

/** The cache key (project, scope, limit, query) and the result identity (plus the view version). */
function searchKeys(
  projectId: string | null,
  rawQuery: string | null,
  scope: SearchScope,
  limit: number | undefined,
  viewVersion: number
): SearchKeys {
  const query = rawQuery?.trim().slice(0, QUERY_MAX) ?? ''
  if (projectId === null || !query) return { query, cacheKey: null, resultKey: null }
  const cacheKey = `${projectId}:${scope}:${limit ?? ''}:${query}`
  // The view version is part of the result identity (stale rows are masked
  // during render) but not of the cache key (the cache is cleared instead).
  return { query, cacheKey, resultKey: `${cacheKey}@${viewVersion}` }
}

interface SearchResult {
  key: string
  data: SearchResponse
}

/** One debounced request; the returned cleanup cancels it and bumps `seq` so a late reply is ignored. */
function startSearch(
  seq: { current: number },
  projectId: string,
  query: string,
  scope: SearchScope,
  limit: number | undefined,
  keys: { cacheKey: string; resultKey: string },
  onResult: (result: SearchResult) => void
): () => void {
  seq.current += 1
  const mine = seq.current
  const timer = setTimeout(() => {
    const started = generation
    searchProject(projectId, query, { scope, limit })
      .then((data) => {
        // A clear that landed mid-flight means these rows predate it.
        if (generation === started) remember(keys.cacheKey, data)
        if (seq.current === mine) onResult({ key: keys.resultKey, data })
      })
      .catch(() => {
        if (seq.current === mine) onResult({ key: keys.resultKey, data: EMPTY })
      })
  }, SEARCH_DEBOUNCE_MS)
  return () => {
    clearTimeout(timer)
    seq.current += 1
  }
}

function liveData(result: SearchResult | null, keys: SearchKeys): SearchResponse | null {
  if (result !== null && result.key === keys.resultKey) return result.data
  const cached = keys.cacheKey !== null ? cache.get(keys.cacheKey) : undefined
  return cached ?? null
}

export function useProjectSearch(
  projectId: string | null,
  rawQuery: string | null,
  opts: ProjectSearchOptions = {}
): ProjectSearch {
  const scope = opts.scope ?? 'all'
  const limit = opts.limit
  const viewVersion = useSourceViewVersion(projectId)
  const keys = searchKeys(projectId, rawQuery, scope, limit, viewVersion)
  const { query, cacheKey, resultKey } = keys
  const [result, setResult] = useState<SearchResult | null>(null)
  const [seenView, setSeenView] = useState(viewVersion)
  const seq = useRef(0)
  // Clear during render (the setState-during-render pattern), so this same
  // render already misses the cache and reports pending instead of stale rows.
  if (seenView !== viewVersion) {
    setSeenView(viewVersion)
    if (projectId !== null) clearSearchCache(projectId)
  }

  useEffect(() => {
    // Any change invalidates whatever is in flight immediately, not just when
    // the next timer fires.
    seq.current += 1
    if (projectId === null || cacheKey === null || resultKey === null) return
    if (cache.has(cacheKey)) return
    return startSearch(seq, projectId, query, scope, limit, { cacheKey, resultKey }, setResult)
  }, [projectId, query, scope, limit, cacheKey, resultKey])

  const live = liveData(result, keys)
  return {
    entities: live?.entities ?? EMPTY_ENTITIES,
    solus: live?.solus ?? EMPTY_SOLUS,
    pending: resultKey !== null && live === null
  }
}
