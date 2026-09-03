// SOLUSDEV-235 / EXT-13 — React wiring of resolveInstalledBundle: one
// resolution per (projectId, slug, view, attempt), cancelled on change or
// unmount so a stale answer can never land on a newer mount. `retry()` bumps
// the attempt (the "Retry is free" of §8 — the install row stays).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { listProjectExtensions, fetchExtensionBundle } from '../../../lib/api/resources.extensions'
import type { ExtensionInstallApi } from '../../../lib/api/resources.extensions'
import { getDesktopExtensionsBridge } from '../../../lib/desktopBridge'
import {
  resolveInstalledBundle,
  type BundleView,
  type InstalledBundleDeps,
  type InstalledBundleState
} from './installedBundle'

/** Follow the cursor chain; the install list of one project is small, the cap is a guard. */
const MAX_INSTALL_PAGES = 20

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

/** Production deps. Developer registrations are held by the Settings →
 *  Developer surface (a sibling task); until that store exists nothing here
 *  reports one, so an installed extension is never shadowed by accident. */
export function defaultInstalledBundleDeps(): InstalledBundleDeps {
  return {
    bridge: getDesktopExtensionsBridge(),
    listInstalls: listAllInstalls,
    fetchBundle: (slug, version) => fetchExtensionBundle(slug, version),
    devRegistration: () => null
  }
}

export interface InstalledBundle {
  readonly state: InstalledBundleState
  /** Re-run the resolution from scratch (download included). */
  retry(): void
}

const LOADING: InstalledBundleState = { status: 'loading' }

export function useInstalledBundle(
  projectId: string,
  slug: string,
  view: BundleView,
  deps?: InstalledBundleDeps
): InstalledBundle {
  const resolved = useMemo(() => deps ?? defaultInstalledBundleDeps(), [deps])
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<InstalledBundleState>(LOADING)

  useEffect(() => {
    let cancelled = false
    const apply = (next: InstalledBundleState): void => {
      if (!cancelled) setState(next)
    }
    apply(LOADING)
    void resolveInstalledBundle({ projectId, slug, view }, resolved, apply).then(apply)
    return () => {
      cancelled = true
    }
  }, [projectId, slug, view, resolved, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  return { state, retry }
}
