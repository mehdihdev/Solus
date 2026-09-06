// SOLUSDEV-235 / EXT-14 — the rail's view of a project's installs (wireflow
// extensions-runtime.md §2). Pure: install rows in, ordered rail entries out.
// An extension earns an entry only when it is installed, enabled, not blocked
// by team policy and declares `[views.page]`; disabled or blocked ones are
// simply absent (the Store still lists them).
//
// SOLUSDEV-246 / STORE ST3: entries sit AFTER the Store behind a separator, and
// the user's PINS ("Pin for all projects", docs/api/extensions.md §6.5) come
// first in every project. A pinned extension that is not installed in the open
// project still gets a tab (`installed: false`) — opening it says so honestly
// and offers the Store; it never pretends the bundle is here.
//
// Developer registrations (EXT-20, wireflow §4) join the rail the same way —
// `[views.page]` earns an entry — but are marked `dev`, drawn after the
// installs and never fetch an icon (the bundle lives in a local folder, not
// behind the assets route). A dev entry shadows an install of the same slug,
// matching the frame resolver, which prefers the dev registration.
import type { ExtensionInstallApi, ExtensionPinApi } from '../../lib/api/resources.extensions'
import { selectDevRegistration } from '../devExtensions/devExtensionsStore'
import { DEV_VERSION } from '../extensions/frame/extUrl'

export interface RailExtensionEntry {
  readonly slug: string
  /** `views.page.label` — the button's title and accessible name. */
  readonly label: string
  /** `views.page.icon`, relative to the bundle; fetched through the assets route.
   *  Null for a pinned extension whose latest manifest declares no page. */
  readonly iconPath: string | null
  /** The pinned version the icon is read from (`dev` for a developer registration);
   *  null when the catalog has no approved version to read one from. */
  readonly version: string | null
  /** Install time, the pin time for a pin-only entry, or the developer registration's load time. */
  readonly installedAt: string
  /** A Settings → Developer registration: DEV corner mark, no icon fetch. */
  readonly dev: boolean
  /** This user pinned it for all projects (STORE ST3). */
  readonly pinned: boolean
  /** An enabled, unblocked install exists in the open project. False for a pin-only entry. */
  readonly installed: boolean
}

/** The dev store's shape as `selectDevRegistration` reads it — the gate that
 *  decides whether a registration is live stays in the store, not here. */
type DevStoreState = Parameters<typeof selectDevRegistration>[0]

/** The rail is finite; installs beyond this stay reachable from the Store. */
export const RAIL_EXTENSION_CAP = 8

function toEntry(row: ExtensionInstallApi, pinned: ReadonlySet<string>): RailExtensionEntry | null {
  const page = row.version.manifest.views.page
  if (!page || !row.enabled || row.policy.blocked) return null
  return {
    slug: row.extension.slug,
    label: page.label,
    iconPath: page.icon,
    version: row.version.version,
    installedAt: row.installed_at,
    dev: false,
    pinned: pinned.has(row.extension.slug),
    installed: true
  }
}

/** A pin with no install here: label and icon from the latest approved manifest's
 *  page view, or the extension's name and the neutral glyph when it has none. */
function toPinEntry(pin: ExtensionPinApi): RailExtensionEntry {
  return {
    slug: pin.slug,
    label: pin.page?.label ?? pin.name,
    iconPath: pin.page?.icon ?? null,
    version: pin.version,
    installedAt: pin.pinned_at,
    dev: false,
    pinned: true,
    installed: false
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
    dev: true,
    pinned: false,
    installed: false
  }
}

function byInstallThenLabel(a: RailExtensionEntry, b: RailExtensionEntry): number {
  return a.installedAt.localeCompare(b.installedAt) || a.label.localeCompare(b.label)
}

/** Pinned entries first (by pin time), then this project's other installs (by
 *  install time), capped. A pin whose slug is installed here is ONE entry: the
 *  install's facts, marked pinned. */
export function railEntriesFrom(
  installs: readonly ExtensionInstallApi[],
  pins: readonly ExtensionPinApi[] = []
): readonly RailExtensionEntry[] {
  const pinnedSlugs = new Set(pins.map((p) => p.slug))
  const installed = installs.flatMap((row) => {
    const entry = toEntry(row, pinnedSlugs)
    return entry ? [entry] : []
  })
  const installedSlugs = new Set(installed.map((e) => e.slug))
  const pinOnly = pins.filter((p) => !installedSlugs.has(p.slug)).map(toPinEntry)
  const pinnedAt = new Map(pins.map((p) => [p.slug, p.pinned_at]))
  const byPinTime = (a: RailExtensionEntry, b: RailExtensionEntry): number =>
    (pinnedAt.get(a.slug) ?? '').localeCompare(pinnedAt.get(b.slug) ?? '') ||
    a.label.localeCompare(b.label)
  const pinned = [...installed.filter((e) => e.pinned), ...pinOnly].sort(byPinTime)
  const rest = installed.filter((e) => !e.pinned).sort(byInstallThenLabel)
  return [...pinned, ...rest].slice(0, RAIL_EXTENSION_CAP)
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
