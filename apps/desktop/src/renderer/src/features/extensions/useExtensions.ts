// SOLUSDEV-235 — the Store's data hook: the server catalog (docs/api/
// extensions.md §4.1) × this project's install rows (§6.1) × the project's
// connected sources → one `ExtensionView` per extension, plus the write
// actions. THIS IS THE BACKEND SEAM: every Store surface renders
// `ExtensionView` and calls `ExtensionActions`; what feeds them is here.
//
// Degrades like the other workspace hooks (SOLUSDEV-152): `offline` when the
// session cannot fetch or the API is unreachable with nothing yet on screen —
// the catalog is then empty and the Store says so, rather than rendering a
// stale or invented one.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ExtensionManifest } from '@solus/shared-types'
import { useInterval } from '../../lib/useInterval'
import { getDesktopExtensionsBridge } from '../../lib/desktopBridge'
import {
  listExtensions,
  listProjectExtensions,
  type ExtensionCatalogItemApi,
  type ExtensionInstallApi
} from '../../lib/api/resources.extensions'
import type { Page } from '../../lib/api/client'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useProjectSources, type ProjectSourcesStatus } from '../project/useProjectSources'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import type { ExtensionView } from './extension.types'
import { createExtensionActions, type ExtensionActions } from './extensionActions'
import { buildViews, connectedKinds } from './extensionLogic'

export type { ExtensionActionResult, ExtensionActions } from './extensionActions'

/** Install rows re-read on this cadence (matches SOURCES_POLL_MS): another
 *  member's install, a team block, or a newly approved version show up
 *  without a click. The catalog itself is re-read on `refresh()`. */
export const EXTENSIONS_POLL_MS = 10_000
/** Upper bound on catalog rows walked across pages — a guard, not a target. */
export const CATALOG_CAP = 500
const CATALOG_PAGE = 100

export type ExtensionsStatus = 'loading' | 'ready' | 'offline'

export interface ExtensionsData {
  projectId: string
  /** The Store API: `offline` means the catalog could not be read. */
  status: ExtensionsStatus
  views: ExtensionView[]
  /** `offline` means requirements were evaluated against no sources — say so. */
  sourcesStatus: ProjectSourcesStatus
  /** Installs whose pinned version is behind the latest approved one. */
  updatesAvailable: number
  actions: ExtensionActions
}

/** Walk a cursor-paginated list until `has_next` is false or `cap` rows. */
async function fetchAll<T>(
  fetchPage: (cursor?: string) => Promise<Page<T[]>>,
  cap: number
): Promise<T[]> {
  const rows: T[] = []
  let cursor: string | undefined
  do {
    const page = await fetchPage(cursor)
    rows.push(...page.data)
    cursor = page.meta.has_next && page.meta.next_cursor ? page.meta.next_cursor : undefined
  } while (cursor && rows.length < cap)
  return rows.slice(0, cap)
}

const loadCatalog = (): Promise<ExtensionCatalogItemApi[]> =>
  fetchAll((cursor) => listExtensions({ cursor, limit: CATALOG_PAGE }), CATALOG_CAP)

const loadInstalls = (projectId: string): Promise<ExtensionInstallApi[]> =>
  fetchAll((cursor) => listProjectExtensions(projectId, cursor), CATALOG_CAP)

function upsertInstall(
  rows: ExtensionInstallApi[],
  row: ExtensionInstallApi
): ExtensionInstallApi[] {
  const rest = rows.filter((r) => r.extension.slug !== row.extension.slug)
  return [...rest, row]
}

const NO_SLUGS: ReadonlySet<string> = new Set()

export function useExtensions(projectId: string): ExtensionsData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const sources = useProjectSources()
  // `useProjectSources` reads the OPEN project; if a caller scopes this hook to
  // another project, its requirements must not be judged against foreign sources.
  const openProjectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const scoped = openProjectId === projectId
  const sourcesStatus: ProjectSourcesStatus = scoped ? sources.status : 'offline'
  const sourceList = sources.sources

  const [status, setStatus] = useState<ExtensionsStatus>(fetchEnabled ? 'loading' : 'offline')
  const [catalog, setCatalog] = useState<ExtensionCatalogItemApi[]>([])
  const [installs, setInstalls] = useState<ExtensionInstallApi[]>([])
  const [details, setDetails] = useState<Readonly<Record<string, ExtensionManifest>>>({})
  const [blocked, setBlocked] = useState<ReadonlySet<string>>(NO_SLUGS)
  const latest = useRef({ catalog, installs })
  latest.current = { catalog, installs }

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      setCatalog([])
      setInstalls([])
      return
    }
    try {
      const [items, rows] = await Promise.all([loadCatalog(), loadInstalls(projectId)])
      setCatalog(items)
      setInstalls(rows)
      setStatus('ready')
    } catch {
      // A failed refresh must not blank a catalog already on screen; only
      // report offline when there was nothing to show in the first place.
      setStatus(latest.current.catalog.length > 0 ? 'ready' : 'offline')
    }
  }, [fetchEnabled, projectId])

  const pollInstalls = useCallback(async (): Promise<void> => {
    try {
      setInstalls(await loadInstalls(projectId))
    } catch {
      // Keep the rows on screen; the next tick retries.
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  useInterval(() => void pollInstalls(), EXTENSIONS_POLL_MS, fetchEnabled && status === 'ready')

  const views = useMemo(
    () =>
      buildViews({
        catalog,
        installs,
        details,
        connected: connectedKinds(scoped ? sourceList.map((s) => s.type) : []),
        blocked
      }),
    [blocked, catalog, details, installs, scoped, sourceList]
  )

  const actions = useMemo<ExtensionActions>(
    () =>
      createExtensionActions({
        projectId,
        bridge: getDesktopExtensionsBridge,
        latestVersionOf: (slug) =>
          latest.current.catalog.find((i) => i.slug === slug)?.latest_version.version,
        installOf: (slug) => latest.current.installs.find((r) => r.extension.slug === slug),
        applyInstall: (row) => setInstalls((rows) => upsertInstall(rows, row)),
        removeInstall: (slug) =>
          setInstalls((rows) => rows.filter((r) => r.extension.slug !== slug)),
        markBlocked: (slug) => setBlocked((prev) => new Set([...prev, slug])),
        applyDetail: (slug, manifest) => setDetails((prev) => ({ ...prev, [slug]: manifest })),
        refresh: load
      }),
    [projectId, load]
  )

  const updatesAvailable = useMemo(
    () => views.filter((v) => v.state.installed && v.state.updateAvailable !== null).length,
    [views]
  )

  return { projectId, status, views, sourcesStatus, updatesAvailable, actions }
}
