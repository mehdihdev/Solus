// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2 "Main: summon
// snapshot and relay"; ADR-041 2026-10-31): the front-app snapshot main keeps
// from the helper's `identify.front`, and the exact shape the SOL renderer may
// receive. Pure — shared by main (producer), preload (validator) and renderer.
// Never bounds or documentDir; for an app that cannot be driven never a pid,
// window id or title (the helper already withholds them; main re-checks).

export type FrontBinding = 'project' | 'window'

/** A drivable app in front: bound by project (KiCad) or by this window. */
export interface SolFrontDrivable {
  drivable: true
  binding: FrontBinding
  bundleId: string
  /** The app's localized name, ≤ 64 scalars, visible text only. Untrusted. */
  name: string
  pid: number
  /** Null when the app has no ordinary window in front (nothing to bind). */
  windowId: number | null
  /** The window title, ≤ 256 scalars, visible text only. Untrusted. */
  title: string | null
}

/** Denied (`binding: null`) or project-bound without a usable workspace. */
export interface SolFrontNotDrivable {
  drivable: false
  binding: 'project' | null
  bundleId: string
  name: string
}

/** The payload of SOL_WINDOW_CHANNELS.frontApp (main → SOL window), or null. */
export type SolFrontApp = SolFrontDrivable | SolFrontNotDrivable

export const FRONT_NAME_MAX = 64
export const FRONT_TITLE_MAX = 256
const PID_MAX = 2 ** 31 - 1
const WINDOW_ID_MAX = 2 ** 32 - 1
const BUNDLE_ID = /^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$/
/** Control, format, private-use, surrogate and line/paragraph separators. */
const INVISIBLE = /[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}]/gu

/** ProjectBoundApps (compiled into solus-input): byte-exact. */
const PROJECT_BOUND: ReadonlySet<string> = new Set(['org.kicad.kicad', 'org.kicad.eeschema'])
/** The denylist's "Solus itself" family entries (§2.2): the app and the dev shell. */
const SOLUS_FAMILIES = ['com.solusforge.solus', 'com.github.Electron'] as const

export const isProjectBoundBundle = (bundleId: string): boolean => PROJECT_BOUND.has(bundleId)

const inFamily = (id: string, family: string): boolean =>
  id === family || id.startsWith(`${family}.`)

/** A denied front that is Solus itself — summoning over Solus keeps the
 *  previous snapshot. */
export function isSolusFront(front: SolFrontApp | null): boolean {
  if (front === null || front.drivable) return false
  return SOLUS_FAMILIES.some((family) => inFamily(front.bundleId, family))
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const isPid = (v: unknown): v is number =>
  typeof v === 'number' && Number.isSafeInteger(v) && v >= 1 && v <= PID_MAX

const isWindowId = (v: unknown): v is number =>
  typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= WINDOW_ID_MAX

const isBundleId = (v: unknown): v is string => typeof v === 'string' && BUNDLE_ID.test(v)

/** Drop invisible characters, then cut to `max` Unicode scalars. */
function clean(raw: string, max: number): string {
  return [...raw.replace(INVISIBLE, '')].slice(0, max).join('')
}

const isBinding = (v: unknown): v is FrontBinding => v === 'project' || v === 'window'

/** A drivable front's fields, or undefined when any is malformed. */
function drivableFrom(
  front: Record<string, unknown>,
  bundleId: string,
  name: string
): SolFrontDrivable | undefined {
  const { binding, pid, windowId, title } = front
  if (!isBinding(binding) || !isPid(pid)) return undefined
  if (windowId !== null && !isWindowId(windowId)) return undefined
  if (title !== null && typeof title !== 'string') return undefined
  const cleanTitle = title === null ? null : clean(title, FRONT_TITLE_MAX)
  return { drivable: true, binding, bundleId, name, pid, windowId, title: cleanTitle }
}

/** The helper's `identify.front` → the snapshot; `null` when nothing is in
 *  front, `undefined` when the reply is malformed (treated as "unknown"). */
export function frontFromIdentify(front: unknown): SolFrontApp | null | undefined {
  if (front === null) return null
  if (!isRecord(front) || !isBundleId(front.bundleId) || typeof front.name !== 'string') {
    return undefined
  }
  const bundleId = front.bundleId
  const name = clean(front.name, FRONT_NAME_MAX) || bundleId
  if (front.drivable === true) return drivableFrom(front, bundleId, name)
  if (front.drivable !== false) return undefined
  if (front.binding !== null && front.binding !== 'project') return undefined
  return { drivable: false, binding: front.binding, bundleId, name }
}

const isCleanText = (v: unknown, max: number): v is string =>
  typeof v === 'string' && [...v].length <= max && v.replace(INVISIBLE, '') === v

const hasOnlyKeys = (r: Record<string, unknown>, keys: readonly string[]): boolean =>
  Object.keys(r).every((k) => keys.includes(k))

const DRIVABLE_KEYS = ['drivable', 'binding', 'bundleId', 'name', 'pid', 'windowId', 'title']
const NOT_DRIVABLE_KEYS = ['drivable', 'binding', 'bundleId', 'name']

const isDrivablePayload = (raw: Record<string, unknown>): boolean =>
  hasOnlyKeys(raw, DRIVABLE_KEYS) &&
  isBinding(raw.binding) &&
  isPid(raw.pid) &&
  (raw.windowId === null || isWindowId(raw.windowId)) &&
  (raw.title === null || isCleanText(raw.title, FRONT_TITLE_MAX))

const isNotDrivablePayload = (raw: Record<string, unknown>): boolean =>
  (raw.binding === null || raw.binding === 'project') && hasOnlyKeys(raw, NOT_DRIVABLE_KEYS)

/** Preload: a SolFrontApp exactly as main produces it, nothing more. */
export function isSolFrontApp(raw: unknown): raw is SolFrontApp {
  if (!isRecord(raw) || !isBundleId(raw.bundleId) || !isCleanText(raw.name, FRONT_NAME_MAX)) {
    return false
  }
  if (raw.drivable === true) return isDrivablePayload(raw)
  return raw.drivable === false && isNotDrivablePayload(raw)
}
