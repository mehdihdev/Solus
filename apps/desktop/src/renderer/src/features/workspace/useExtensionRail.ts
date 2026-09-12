// SOLUSDEV-235 / EXT-14 — the rail's live view of the open project's installed
// page-view extensions (wireflow extensions-runtime.md §2). Polls OUR api on
// the shared workspace cadence (SOURCES_POLL_MS idiom) so an install, disable
// or team block made elsewhere reaches the rail without a click. Degrades to
// `offline` like the other workspace hooks: no project, fetch disabled or an
// unreachable API all mean an empty rail, never a thrown error.
//
// Icons: the manifest's `views.page.icon` is read through the assets route
// (extensionIconAsset) and reduced by the host's SVG reducer BEFORE it is
// cached — the rail never holds extension bytes the reducer has not passed.
// Any miss caches `null`, which the rail draws as the neutral glyph.
//
// Developer registrations (EXT-20) come from the dev store, not the API:
// merged after the installs, marked `dev`, icon never fetched (neutral glyph).
//
// Pins (SOLUSDEV-246 / STORE ST3) come from the pins store — the user's
// account state, hydrated once here and re-read on the same poll, so a pin
// made on another machine or in the Store reaches every project's rail.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useInterval } from '../../lib/useInterval'
import {
  listProjectExtensions,
  type ExtensionInstallApi,
  type ExtensionPinApi
} from '../../lib/api/resources.extensions'
import { useWorkspaceStore } from '../../store/workspaceStore'
import {
  fetchExtensionIconSvg,
  type IconAssetTransport
} from '../extensions/pageview/extensionIconAsset'
import { reduceSvg } from '../extensions/host/svgReduce'
import { useDevExtensionsStore } from '../devExtensions/devExtensionsStore'
import { usePinsStore } from '../extensions/pinsStore'
import { useWorkspaceFetchEnabled } from './workspaceOnline'
import {
  devRailEntriesFrom,
  mergeRailEntries,
  railEntriesFrom,
  type RailExtensionEntry
} from './extensionRail'

/** Same cadence as Home's connected-accounts card and the bridge pill. */
export const EXTENSION_RAIL_POLL_MS = 10_000

/** Follow the cursor chain; one project's installs are few, the cap is a guard. */
const MAX_INSTALL_PAGES = 20

export type ExtensionRailStatus = 'loading' | 'ready' | 'offline'

/** Reduced SVG text per slug; `null` ⇒ draw the neutral glyph. */
export type RailIconMap = Readonly<Record<string, string | null>>

export interface ExtensionRailData {
  readonly status: ExtensionRailStatus
  readonly entries: readonly RailExtensionEntry[]
  readonly icons: RailIconMap
}

export interface ExtensionRailDeps {
  readonly iconTransport?: IconAssetTransport
}

async function listAllInstalls(projectId: string): Promise<readonly ExtensionInstallApi[]> {
  const rows: ExtensionInstallApi[] = []
  let cursor: string | undefined
  for (let pageNo = 0; pageNo < MAX_INSTALL_PAGES; pageNo += 1) {
    const result = await listProjectExtensions(projectId, cursor)
    rows.push(...result.data)
    const next = result.meta.next_cursor
    if (!result.meta.has_next || !next) break
    cursor = next
  }
  return rows
}

interface Listing {
  readonly projectId: string
  readonly status: ExtensionRailStatus
  readonly entries: readonly RailExtensionEntry[]
}

const NO_ENTRIES: readonly RailExtensionEntry[] = []

/** One fetch, resolved to the listing it produces — never rejects. */
async function fetchListing(projectId: string, pins: readonly ExtensionPinApi[]): Promise<Listing> {
  try {
    const entries = railEntriesFrom(await listAllInstalls(projectId), pins)
    return { projectId, status: 'ready', entries }
  } catch {
    return { projectId, status: 'offline', entries: NO_ENTRIES }
  }
}

/** A blip on the timer must not blank a rail that is already drawn: an offline
 *  answer only replaces a listing that had nothing to show for this project. */
function mergeListing(prev: Listing | null, next: Listing): Listing {
  const keepPrev =
    next.status === 'offline' && prev?.projectId === next.projectId && prev.entries.length > 0
  return keepPrev ? prev : next
}

/** Entries + status for the open project; a switch shows nothing until the new project answers. */
function useRailEntries(): Pick<ExtensionRailData, 'status' | 'entries'> {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const pins = usePinsStore((s) => s.pins)
  const [listing, setListing] = useState<Listing | null>(null)
  const active = projectId !== null && fetchEnabled

  const refresh = useCallback((): void => {
    if (!active) return
    void fetchListing(projectId, usePinsStore.getState().pins).then((next) =>
      setListing((prev) => mergeListing(prev, next))
    )
  }, [active, projectId])

  // Pins are account state: hydrated once the rail can draw, re-read on the poll.
  useEffect(() => {
    if (active) void usePinsStore.getState().hydrate()
  }, [active])
  useEffect(refresh, [refresh, pins])
  useInterval(
    () => {
      void usePinsStore.getState().hydrate()
      refresh()
    },
    EXTENSION_RAIL_POLL_MS,
    active
  )

  if (!active) return { status: 'offline', entries: NO_ENTRIES }
  if (listing === null || listing.projectId !== projectId) {
    return { status: 'loading', entries: NO_ENTRIES }
  }
  return { status: listing.status, entries: listing.entries }
}

function iconKey(entry: RailExtensionEntry): string {
  return `${entry.slug}/${entry.version ?? ''}/${entry.iconPath ?? ''}`
}

/** Fetch + reduce each entry's icon once per (slug, version, path); never throws. */
function useRailIcons(
  entries: readonly RailExtensionEntry[],
  transport: IconAssetTransport | undefined
): RailIconMap {
  const [cache, setCache] = useState<Readonly<Record<string, string | null>>>({})
  // Keys ever requested — a key is fetched once for the hook's lifetime; a new
  // version or path is a new key. Results land only while mounted.
  const requested = useRef(new Set<string>())
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    for (const entry of entries) {
      if (entry.dev || entry.iconPath === null || entry.version === null) continue
      const key = iconKey(entry)
      if (requested.current.has(key)) continue
      requested.current.add(key)
      fetchExtensionIconSvg(entry.slug, entry.version, entry.iconPath, transport)
        .then((svg) => (svg ? reduceSvg(svg) : null))
        .catch(() => null)
        .then((reduced) => {
          if (mounted.current) setCache((prev) => ({ ...prev, [key]: reduced }))
        })
    }
  }, [entries, transport])

  return useMemo(
    () => Object.fromEntries(entries.map((e) => [e.slug, cache[iconKey(e)] ?? null])),
    [entries, cache]
  )
}

/** The session's page-view developer registrations, recomputed as the store changes. */
function useDevRailEntries(): readonly RailExtensionEntry[] {
  const devState = useDevExtensionsStore()
  return useMemo(() => devRailEntriesFrom(devState), [devState])
}

export function useExtensionRail(deps: ExtensionRailDeps = {}): ExtensionRailData {
  const { status, entries: installed } = useRailEntries()
  const dev = useDevRailEntries()
  const entries = useMemo(() => mergeRailEntries(installed, dev), [installed, dev])
  const icons = useRailIcons(entries, deps.iconTransport)
  return { status, entries, icons }
}
