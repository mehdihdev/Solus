// SOLUSDEV-235 / EXT-15 — the widgets this project can place.
//
// Built-ins come from CTR-01 discovery (in-repo, trusted, synchronous).
// Extension widgets come from the §6.1 install+policy snapshot: every install
// whose manifest declares `[views.widget]`, WITH its enabled/blocked flags —
// the picker disables those rows and the slot shows the frame's own card, but
// neither is "unknown", so neither is pruned. `available.ext` stays null until
// the snapshot has loaded once: the pruner must never drop an extension slot
// on a guess (wireflow "Unknown refs are dropped, not crashed").
import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  Domain,
  SourceKind,
  Widget,
  WidgetManifest,
  WidgetSizeHint
} from '@solus/shared-types'
import { listProjectExtensions, type ExtensionInstallApi } from '../../lib/api/resources.extensions'
import { useInterval } from '../../lib/useInterval'
import { discoverWidgets } from '../../widgets/discover'
import { builtinRef, extRef, type AvailableRefs } from './layout'

/** Matches SOURCES_POLL_MS / BRIDGE_POLL_MS: our API only, never a provider. */
export const WIDGETS_POLL_MS = 10_000
/** The install list of one project is small; the cap is a guard. */
const MAX_INSTALL_PAGES = 20

export type AvailableWidgetsStatus = 'loading' | 'ready' | 'offline'

export interface BuiltinWidgetEntry {
  readonly ref: string
  readonly id: string
  readonly title: string
  readonly domains: readonly Domain[]
  readonly size: WidgetSizeHint
  readonly component: Widget
}

export interface ExtensionWidgetEntry {
  readonly ref: string
  readonly slug: string
  readonly name: string
  readonly summary: string
  readonly version: string
  readonly verified: boolean
  readonly publisher: string
  readonly size: WidgetSizeHint
  readonly requires: readonly (readonly SourceKind[])[]
  readonly enabled: boolean
  readonly blocked: boolean
  /** The manifest's page icon, reused as the slot's monochrome mark; null when none. */
  readonly iconPath: string | null
  readonly hasWindow: boolean
}

export interface AvailableWidgets {
  readonly builtins: readonly BuiltinWidgetEntry[]
  readonly extensions: readonly ExtensionWidgetEntry[]
  readonly status: AvailableWidgetsStatus
  /** What the pruner may trust. `ext: null` until the snapshot loaded once. */
  readonly available: AvailableRefs
}

export interface AvailableWidgetsDeps {
  readonly discover: () => WidgetManifest[]
  readonly listInstalls: (projectId: string) => Promise<readonly ExtensionInstallApi[]>
}

async function listAllInstalls(projectId: string): Promise<readonly ExtensionInstallApi[]> {
  const rows: ExtensionInstallApi[] = []
  let cursor: string | undefined
  for (let page = 0; page < MAX_INSTALL_PAGES; page += 1) {
    const result = await listProjectExtensions(projectId, cursor)
    rows.push(...result.data)
    const next = result.meta.next_cursor
    if (!result.meta.has_next || !next) break
    cursor = next
  }
  return rows
}

export const defaultAvailableWidgetsDeps: AvailableWidgetsDeps = {
  discover: discoverWidgets,
  listInstalls: listAllInstalls
}

export function builtinWidgetEntries(manifests: readonly WidgetManifest[]): BuiltinWidgetEntry[] {
  return manifests.map((m) => ({
    ref: builtinRef(m.id),
    id: m.id,
    title: m.title,
    domains: m.domains,
    size: m.size,
    component: m.component
  }))
}

/** Installs with a widget view → picker/slot facts. Pure, exported for tests. */
export function extensionWidgetEntries(
  installs: readonly ExtensionInstallApi[]
): ExtensionWidgetEntry[] {
  const entries: ExtensionWidgetEntry[] = []
  for (const install of installs) {
    const { manifest } = install.version
    const widget = manifest.views.widget
    if (widget === undefined) continue
    entries.push({
      ref: extRef(install.extension.slug),
      slug: install.extension.slug,
      name: install.extension.name,
      summary: manifest.extension.summary,
      version: install.version.version,
      verified: install.extension.verified,
      publisher: install.extension.publisher.display_name,
      size: { preferred: widget.preferred, minimum: widget.minimum },
      requires: manifest.extension.requires,
      enabled: install.enabled,
      blocked: install.policy.blocked,
      iconPath: manifest.views.page?.icon ?? null,
      hasWindow: manifest.views.window !== undefined
    })
  }
  return entries
}

interface Snapshot {
  readonly projectId: string
  readonly extensions: readonly ExtensionWidgetEntry[]
}

export function useAvailableWidgets(
  projectId: string,
  deps: AvailableWidgetsDeps = defaultAvailableWidgetsDeps
): AvailableWidgets {
  const { discover, listInstalls } = deps
  const builtins = useMemo(() => builtinWidgetEntries(discover()), [discover])
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  // A stale answer (project switched mid-flight) is dropped by the key check
  // below, and a failed refresh keeps the snapshot already on screen; only a
  // project with nothing loaded yet reads as offline.
  const load = useCallback(
    (): Promise<void> =>
      listInstalls(projectId).then(
        (installs) => setSnapshot({ projectId, extensions: extensionWidgetEntries(installs) }),
        () => setFailed(projectId)
      ),
    [listInstalls, projectId]
  )

  useEffect(() => {
    void load()
  }, [load])
  useInterval(() => void load(), WIDGETS_POLL_MS)

  const current = snapshot?.projectId === projectId ? snapshot : null
  const status: AvailableWidgetsStatus =
    current !== null ? 'ready' : failed === projectId ? 'offline' : 'loading'
  const extensions = current?.extensions ?? []
  const available = useMemo<AvailableRefs>(
    () => ({
      builtin: new Set(builtins.map((b) => b.id)),
      ext: current === null ? null : new Set(current.extensions.map((e) => e.slug))
    }),
    [builtins, current]
  )
  return { builtins, extensions, status, available }
}
