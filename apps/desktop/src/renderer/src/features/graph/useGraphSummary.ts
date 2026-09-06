// Live summary for the Context Model screen: counts from getProject (whose
// payload already carries the sources array — no second sources request) plus
// the full entity list for the list view. Degrades honestly: `offline` when
// the workspace isn't linked, no project is selected, or the API can't answer;
// `error` when the API answers with a refusal (saying "can't reach the API"
// there would be a lie); and a failed LIST call keeps status `ready` with
// `entities: null` — the counts and the list are independent truths.
//
// The entity list is retained across mounts (SOLUSDEV-234, see graphCache):
// a remount renders the retained list immediately, re-fetches only the detail,
// and re-walks the pages only when the detail says the graph changed or the
// entry aged past the TTL.
import { useEffect, useState } from 'react'
import {
  getProject,
  listAllEntities,
  type Entity,
  type ProjectDetail
} from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import {
  countsOf,
  graphCache,
  graphVersionOf,
  isGraphCacheValid,
  type GraphCacheEntry
} from './graphCache'

export type GraphSummaryStatus = 'loading' | 'ready' | 'offline' | 'error'

export interface GraphSummary {
  status: GraphSummaryStatus
  entityCount: number
  relationCount: number
  sourceCount: number
  /** The project's entities, or null when the list call failed (counts may still be honest). */
  entities: Entity[] | null
}

const ZERO_COUNTS = {
  entityCount: 0,
  relationCount: 0,
  sourceCount: 0,
  entities: null
} as const

const OFFLINE: GraphSummary = { status: 'offline', ...ZERO_COUNTS }
const LOADING: GraphSummary = { status: 'loading', ...ZERO_COUNTS }

function fromRetained(entry: GraphCacheEntry): GraphSummary {
  return { status: 'ready', ...entry.counts, entities: [...entry.entities] }
}

function retain(projectId: string, detail: ProjectDetail, entities: Entity[]): void {
  graphCache.set(projectId, {
    version: graphVersionOf(detail),
    entities,
    counts: countsOf(detail),
    fetchedAtMs: Date.now()
  })
}

/** The entity list for `detail`: the retained one when still valid, else a fresh walk
 *  (`null` when the walk fails — a failed list is never retained). */
async function resolveEntities(
  projectId: string,
  detail: ProjectDetail,
  walk: Promise<Entity[]> | null
): Promise<Entity[] | null> {
  const entry = graphCache.get(projectId)
  if (isGraphCacheValid(entry, detail, Date.now())) return [...entry.entities]
  try {
    const entities = await (walk ?? listAllEntities(projectId))
    retain(projectId, detail, entities)
    return entities
  } catch {
    return null
  }
}

async function loadSummary(projectId: string): Promise<GraphSummary> {
  // Cold start: the detail and the walk go out together, as before. With a
  // retained entry the detail alone decides whether the walk is needed.
  const walk = graphCache.has(projectId) ? null : listAllEntities(projectId)
  walk?.catch(() => undefined) // observed again in resolveEntities; never unhandled
  let detail: ProjectDetail
  try {
    detail = await getProject(projectId)
  } catch (reason) {
    const status = classifyFetchError(reason) === 'unauthorized' ? 'error' : 'offline'
    return { status, ...ZERO_COUNTS }
  }
  const entities = await resolveEntities(projectId, detail, walk)
  return { status: 'ready', ...countsOf(detail), entities }
}

/** `revision` > 0 forces a fresh walk (the caller knows the graph changed —
 *  e.g. a `.solus` import just created a document node the cache predates). */
export function useGraphSummary(revision = 0): GraphSummary {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const [summary, setSummary] = useState<GraphSummary>(() => {
    if (!fetchEnabled || !projectId) return OFFLINE
    const retained = graphCache.get(projectId)
    return retained ? fromRetained(retained) : LOADING
  })

  useEffect(() => {
    if (!fetchEnabled || !projectId) {
      setSummary(OFFLINE)
      return
    }
    let cancelled = false
    if (revision > 0) graphCache.delete(projectId)
    const retained = graphCache.get(projectId)
    setSummary(retained ? fromRetained(retained) : LOADING)
    void loadSummary(projectId).then((next) => {
      if (!cancelled) setSummary(next)
    })
    return () => {
      cancelled = true
    }
  }, [fetchEnabled, projectId, revision])

  return summary
}
