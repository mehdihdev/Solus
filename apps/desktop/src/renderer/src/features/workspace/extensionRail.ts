// SOLUSDEV-235 / EXT-14 — the rail's view of a project's installs (wireflow
// extensions-runtime.md §2). Pure: install rows in, ordered rail entries out.
// An extension earns an entry only when it is installed, enabled, not blocked
// by team policy and declares `[views.page]`; disabled or blocked ones are
// simply absent (the Store still lists them).
//
// Developer registrations (EXT-20, wireflow §4) join the rail the same way —
// `[views.page]` earns an entry — but are marked `dev`, drawn after the
// installs and never fetch an icon (the bundle lives in a local folder, not
// behind the assets route). A dev entry shadows an install of the same slug,
// matching the frame resolver, which prefers the dev registration.
import type { ExtensionInstallApi } from '../../lib/api/resources.extensions'
import { selectDevRegistration } from '../devExtensions/devExtensionsStore'
import { DEV_VERSION } from '../extensions/frame/extUrl'

export interface RailExtensionEntry {
  readonly slug: string
  /** `views.page.label` — the button's title and accessible name. */
  readonly label: string
  /** `views.page.icon`, relative to the bundle; fetched through the assets route. */
  readonly iconPath: string
  /** The pinned version the icon is read from (`dev` for a developer registration). */
  readonly version: string
  /** Install time, or the developer registration's load time. */
  readonly installedAt: string
  /** A Settings → Developer registration: DEV corner mark, no icon fetch. */
  readonly dev: boolean
}

/** The dev store's shape as `selectDevRegistration` reads it — the gate that
 *  decides whether a registration is live stays in the store, not here. */
type DevStoreState = Parameters<typeof selectDevRegistration>[0]

/** The rail is finite; installs beyond this stay reachable from the Store. */
export const RAIL_EXTENSION_CAP = 8

function toEntry(row: ExtensionInstallApi): RailExtensionEntry | null {
  const page = row.version.manifest.views.page
  if (!page || !row.enabled || row.policy.blocked) return null
  return {
    slug: row.extension.slug,
    label: page.label,
    iconPath: page.icon,
    version: row.version.version,
    installedAt: row.installed_at,
    dev: false
  }
}

function toDevEntry(state: DevStoreState, slug: string): RailExtensionEntry | null {
  const page = selectDevRegistration(state, slug)?.manifest.views.page
  if (page === undefined) return null
  return {
    slug,
    label: page.label,
    iconPath: page.icon,
    version: DEV_VERSION,
    installedAt: state.entries[slug]?.loadedAt ?? '',
    dev: true
  }
}

function byInstallThenLabel(a: RailExtensionEntry, b: RailExtensionEntry): number {
  return a.installedAt.localeCompare(b.installedAt) || a.label.localeCompare(b.label)
}

export function railEntriesFrom(
  installs: readonly ExtensionInstallApi[]
): readonly RailExtensionEntry[] {
  return installs
    .flatMap((row) => {
      const entry = toEntry(row)
      return entry ? [entry] : []
    })
    .sort(byInstallThenLabel)
    .slice(0, RAIL_EXTENSION_CAP)
}

/** Live developer registrations with a page view, by load time then label. */
export function devRailEntriesFrom(state: DevStoreState): readonly RailExtensionEntry[] {
  return Object.keys(state.entries)
    .flatMap((slug) => {
      const entry = toDevEntry(state, slug)
      return entry ? [entry] : []
    })
    .sort(byInstallThenLabel)
}

/** Installs first, then dev entries; a dev entry replaces the install of its
 *  slug. The cap applies to installs only — a registration the developer
 *  loaded by hand is never hidden behind the Store. */
export function mergeRailEntries(
  registry: readonly RailExtensionEntry[],
  dev: readonly RailExtensionEntry[]
): readonly RailExtensionEntry[] {
  if (dev.length === 0) return registry
  const shadowed = new Set(dev.map((entry) => entry.slug))
  return [...registry.filter((entry) => !shadowed.has(entry.slug)), ...dev]
}
