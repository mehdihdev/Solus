// Local reading and optimistic application of the shared bench view's display ops
// (docs/api/bench-view.md §3.1). Pure and immutable: the server's response replaces
// whatever this predicts, so only set_display is applied locally.
import {
  benchTargetKey,
  type BenchView,
  type BenchViewDisplayEntry,
  type BenchViewDisplayPatch,
  type BenchViewOp,
  type BenchViewTarget
} from '@solus/shared-types'

export type DisplaySettings = Omit<BenchViewDisplayEntry, 'target'>

export const DEFAULT_DISPLAY: DisplaySettings = Object.freeze({
  pinned: false,
  hidden: false,
  order: null,
  unit: null,
  limits: null,
  plot_group: null
})

export function displayFor(view: BenchView | null, target: BenchViewTarget): DisplaySettings {
  if (!view) return DEFAULT_DISPLAY
  const key = benchTargetKey(target)
  const entry = view.display.find((row) => benchTargetKey(row.target) === key)
  if (!entry) return DEFAULT_DISPLAY
  return {
    pinned: entry.pinned,
    hidden: entry.hidden,
    order: entry.order,
    unit: entry.unit,
    limits: entry.limits,
    plot_group: entry.plot_group
  }
}

const FIELDS = Object.keys(DEFAULT_DISPLAY) as (keyof DisplaySettings)[]

/** `null` (or an explicit undefined) resets a field to its default. */
function merge(settings: DisplaySettings, patch: BenchViewDisplayPatch): DisplaySettings {
  const changes = Object.fromEntries(
    FIELDS.filter((field) => field in patch).map((field) => [
      field,
      patch[field] ?? DEFAULT_DISPLAY[field]
    ])
  )
  return { ...settings, ...changes }
}

const isDefault = (settings: DisplaySettings): boolean =>
  FIELDS.every((field) => settings[field] === DEFAULT_DISPLAY[field])

export function applyDisplayOps(view: BenchView, ops: readonly BenchViewOp[]): BenchView {
  return ops.reduce<BenchView>((current, op) => {
    if (op.kind !== 'set_display') return current
    const key = benchTargetKey(op.target)
    const settings = merge(displayFor(current, op.target), op.patch)
    const rest = current.display.filter((row) => benchTargetKey(row.target) !== key)
    const display = isDefault(settings) ? rest : [...rest, { target: op.target, ...settings }]
    return { ...current, display }
  }, view)
}
