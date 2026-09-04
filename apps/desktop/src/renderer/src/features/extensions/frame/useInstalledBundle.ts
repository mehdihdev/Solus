// SOLUSDEV-235 / EXT-13 — React wiring of resolveInstalledBundle: one
// resolution per (projectId, slug, view, attempt), cancelled on change or
// unmount so a stale answer can never land on a newer mount. `retry()` bumps
// the attempt (the "Retry is free" of §8 — the install row stays).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { listProjectExtensions, fetchExtensionBundle } from '../../../lib/api/resources.extensions'
import type { ExtensionInstallApi } from '../../../lib/api/resources.extensions'
import { getDesktopExtensionsBridge } from '../../../lib/desktopBridge'
import {
  selectDevRegistration,
  useDevExtensionsStore
} from '../../devExtensions/devExtensionsStore'
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

/** Production deps. Developer registrations come from the Settings → Developer
 *  store (EXT-20); a dev entry shadows an install of the same slug on purpose —
 *  that is what "load unpacked" is for — and is marked DEV everywhere. */
export function defaultInstalledBundleDeps(): InstalledBundleDeps {
  return {
    bridge: getDesktopExtensionsBridge(),
    listInstalls: listAllInstalls,
    fetchBundle: (slug, version) => fetchExtensionBundle(slug, version),
    devRegistration: (slug) => selectDevRegistration(useDevExtensionsStore.getState(), slug)
  }
}

export interface InstalledBundle {
  readonly state: InstalledBundleState
  /** Re-run the resolution from scratch (download included). */
  retry(): void
}

const LOADING: InstalledBundleState = { status: 'loading' }

interface Resolution {
  readonly key: string
  readonly state: InstalledBundleState
}

export function useInstalledBundle(
  projectId: string,
  slug: string,
  view: BundleView,
  deps?: InstalledBundleDeps
): InstalledBundle {
  const resolved = useMemo(() => deps ?? defaultInstalledBundleDeps(), [deps])
  const [attempt, setAttempt] = useState(0)
  // Results are keyed by their inputs, so a change of project/slug/view/attempt
  // reads as `loading` at once without a reset write, and a late answer for an
  // old key is simply never shown.
  const key = `${projectId}\u0000${slug}\u0000${view}\u0000${attempt}`
  const [resolution, setResolution] = useState<Resolution | null>(null)

  useEffect(() => {
    let cancelled = false
    const apply = (state: InstalledBundleState): void => {
      if (!cancelled) setResolution({ key, state })
    }
    void resolveInstalledBundle({ projectId, slug, view }, resolved, apply).then(apply)
    return () => {
      cancelled = true
    }
  }, [key, projectId, slug, view, resolved])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  const state = resolution !== null && resolution.key === key ? resolution.state : LOADING
  return { state, retry }
}
