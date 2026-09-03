// SOLUSDEV-235 / EXT-13 — what the header can honestly say at each bundle
// state: the name as soon as the install row is known (before the download),
// version / publisher / DEV only once the bundle is ready.
import type { InstalledBundleState, ReadyBundle } from '../frame/installedBundle'

export interface HeaderFacts {
  readonly ready: ReadyBundle | null
  readonly name: string
  readonly isDev: boolean
  readonly version: string | null
  readonly publisher: ReadyBundle['publisher']
  /** The manifest's page icon path, when a registry install could serve one. */
  readonly iconPath: string | null
}

const NOT_READY = { isDev: false, version: null, publisher: null, iconPath: null } as const

function readyFacts(ready: ReadyBundle): Omit<HeaderFacts, 'ready' | 'name'> {
  return {
    isDev: ready.policy.mode === 'dev',
    version: ready.version,
    publisher: ready.publisher,
    iconPath: ready.manifest.views.page?.icon ?? null
  }
}

export function headerFacts(state: InstalledBundleState, slug: string): HeaderFacts {
  const ready = state.status === 'ready' ? state : null
  const name = 'name' in state ? state.name : slug
  return { ready, name, ...(ready ? readyFacts(ready) : NOT_READY) }
}
