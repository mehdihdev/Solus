// SOLUSDEV-235 / EXT-14 — the rail's view of a project's installs (wireflow
// extensions-runtime.md §2). Pure: install rows in, ordered rail entries out.
// An extension earns an entry only when it is installed, enabled, not blocked
// by team policy and declares `[views.page]`; disabled or blocked ones are
// simply absent (the Store still lists them).
import type { ExtensionInstallApi } from '../../lib/api/resources.extensions'

export interface RailExtensionEntry {
  readonly slug: string
  /** `views.page.label` — the button's title and accessible name. */
  readonly label: string
  /** `views.page.icon`, relative to the bundle; fetched through the assets route. */
  readonly iconPath: string
  /** The pinned version the icon is read from. */
  readonly version: string
  readonly installedAt: string
}

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
    installedAt: row.installed_at
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
