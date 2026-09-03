// SOLUSDEV-235 / EXT-15 — the widget canvas's pure layout rules.
//
// Layout in, layout out; no store, no fetch, no React. This is the ONLY place
// the coarse CTR-01 slot sizes become grid columns (docs/wireflows/widget-canvas.md
// "Grid and slots"): the contract forbids widgets guessing at column counts, so
// the mapping lives here and nowhere else. Every edit returns a new array or the
// SAME array when nothing changed, so callers can compare by identity.
import type { WidgetSizeHint, WidgetSlotSize } from '@solus/shared-types'

export type WidgetRef =
  | { readonly kind: 'builtin'; readonly id: string }
  | { readonly kind: 'ext'; readonly slug: string }

export interface LayoutSlot {
  /** `builtin:<widgetId>` or `ext:<extensionId>` — the wire form (API §8). */
  readonly ref: string
  readonly size: WidgetSlotSize
}

export type WidgetLayout = readonly LayoutSlot[]

/** Which refs resolve right now. `ext: null` = the install snapshot is not
 *  known yet, so extension refs are KEPT (never pruned on a guess). */
export interface AvailableRefs {
  readonly builtin: ReadonlySet<string>
  readonly ext: ReadonlySet<string> | null
}

export interface PruneResult {
  readonly layout: WidgetLayout
  /** Every ref dropped, in layout order — the wire form, for the note and the event. */
  readonly dropped: readonly string[]
}

/** The server's cap (API §8): `422` beyond. */
export const MAX_SLOTS = 24
export const GRID_COLUMNS = 4
export const SLOT_SIZES: readonly WidgetSlotSize[] = ['compact', 'standard', 'wide', 'full']
export const DEFAULT_WIDGET_REF = 'builtin:livebench'

// API §8's ref rules verbatim; the ext half is the manifest slug rule.
const BUILTIN_ID_RE = /^[a-z][a-z0-9-]{0,63}$/
const EXT_ID_RE = /^[a-z][a-z0-9-]{1,63}$/
const SPAN: Readonly<Record<WidgetSlotSize, number>> = { compact: 1, standard: 2, wide: 3, full: 4 }

export function parseWidgetRef(text: string): WidgetRef | null {
  const colon = text.indexOf(':')
  if (colon < 0) return null
  const prefix = text.slice(0, colon)
  const rest = text.slice(colon + 1)
  if (prefix === 'builtin' && BUILTIN_ID_RE.test(rest)) return { kind: 'builtin', id: rest }
  if (prefix === 'ext' && EXT_ID_RE.test(rest)) return { kind: 'ext', slug: rest }
  return null
}

export function formatWidgetRef(ref: WidgetRef): string {
  return ref.kind === 'builtin' ? builtinRef(ref.id) : extRef(ref.slug)
}

export const builtinRef = (id: string): string => `builtin:${id}`
export const extRef = (slug: string): string => `ext:${slug}`

/** A project nobody has arranged: the Live Bench it already has, at its preferred size. */
export function defaultLayout(): WidgetLayout {
  return [{ ref: DEFAULT_WIDGET_REF, size: 'wide' }]
}

/** Grid columns on the 4-column canvas. */
export function slotSpan(size: WidgetSlotSize): number {
  return SPAN[size]
}

function isAvailable(ref: WidgetRef, available: AvailableRefs): boolean {
  if (ref.kind === 'builtin') return available.builtin.has(ref.id)
  return available.ext === null || available.ext.has(ref.slug)
}

/**
 * Drop what cannot render: malformed refs, duplicates (first wins), built-ins
 * missing from this build, extensions missing from the install snapshot.
 * Nothing is fabricated in a dropped slot's place.
 */
export function pruneLayout(layout: WidgetLayout, available: AvailableRefs): PruneResult {
  const seen = new Set<string>()
  const kept: LayoutSlot[] = []
  const dropped: string[] = []
  for (const slot of layout) {
    const parsed = parseWidgetRef(slot.ref)
    if (parsed === null || seen.has(slot.ref) || !isAvailable(parsed, available)) {
      dropped.push(slot.ref)
      continue
    }
    seen.add(slot.ref)
    kept.push(slot)
  }
  return { layout: dropped.length === 0 ? layout : kept, dropped }
}

/** Append one slot. One slot per ref, at most MAX_SLOTS; otherwise the input is returned. */
export function addSlot(layout: WidgetLayout, ref: string, size: WidgetSlotSize): WidgetLayout {
  if (parseWidgetRef(ref) === null || layout.length >= MAX_SLOTS) return layout
  if (layout.some((slot) => slot.ref === ref)) return layout
  return [...layout, { ref, size }]
}

export function removeSlot(layout: WidgetLayout, ref: string): WidgetLayout {
  const next = layout.filter((slot) => slot.ref !== ref)
  return next.length === layout.length ? layout : next
}

export function resizeSlot(layout: WidgetLayout, ref: string, size: WidgetSlotSize): WidgetLayout {
  const index = layout.findIndex((slot) => slot.ref === ref)
  if (index < 0 || layout[index].size === size) return layout
  return layout.map((slot, i) => (i === index ? { ref: slot.ref, size } : slot))
}

/** Swap with the neighbour in `direction` (-1 earlier, +1 later); clamped at the ends. */
export function moveSlot(layout: WidgetLayout, ref: string, direction: -1 | 1): WidgetLayout {
  const index = layout.findIndex((slot) => slot.ref === ref)
  const target = index + direction
  if (index < 0 || target < 0 || target >= layout.length) return layout
  const next = [...layout]
  next[index] = layout[target]
  next[target] = layout[index]
  return next
}

/** The sizes the size menu may offer: at or above `minimum`; only `preferred`
 *  when the widget is not resizable; everything for an unknown widget. */
export function allowedSizes(hint: WidgetSizeHint | undefined): readonly WidgetSlotSize[] {
  if (hint === undefined) return SLOT_SIZES
  if (hint.resizable === false) return [hint.preferred]
  const floor = hint.minimum === undefined ? 0 : SLOT_SIZES.indexOf(hint.minimum)
  return SLOT_SIZES.slice(floor)
}

export function isSizeAllowed(size: WidgetSlotSize, hint: WidgetSizeHint | undefined): boolean {
  return allowedSizes(hint).includes(size)
}
