// How the shared view arranges signal cards (docs/api/bench-view.md §2; wireflow
// live-bench-view.md "Layout"): pinned cards move to the pinned strip, hidden cards to
// "Hidden signals", the rest sort by `order` then natural order, and members of a plot
// group collapse into one chart at the position of the first member. Pure.
import {
  BENCH_VIEW_LIMITS,
  type BenchView,
  type BenchViewDisplayEntry,
  type BenchViewTarget,
  type SetDisplayOp
} from '@solus/shared-types'
import { displayFor, type DisplaySettings } from './viewOps'

export interface SignalRowLike {
  deviceId: string
  signal: string
}

export type ArrangedItem<T> =
  | { kind: 'card'; row: T; settings: DisplaySettings }
  | { kind: 'group'; group: string; rows: T[] }

export interface Arranged<T> {
  items: ArrangedItem<T>[]
  hiddenCount: number
}

export const signalTarget = (row: SignalRowLike): BenchViewTarget => ({
  kind: 'signal',
  device_id: row.deviceId,
  signal: row.signal
})

const sortKey = (order: number | null): number => order ?? Number.MAX_SAFE_INTEGER

export function arrangeSignals<T extends SignalRowLike>(
  rows: readonly T[],
  view: BenchView | null
): Arranged<T> {
  const settled = rows.map((row, index) => ({
    row,
    index,
    settings: displayFor(view, signalTarget(row))
  }))
  const shown = settled
    .filter(({ settings }) => !settings.hidden && !settings.pinned)
    .sort((a, b) => sortKey(a.settings.order) - sortKey(b.settings.order) || a.index - b.index)
  const groups = new Map<string, T[]>()
  const items: ArrangedItem<T>[] = []
  for (const { row, settings } of shown) {
    const group = settings.plot_group
    if (group === null) {
      items.push({ kind: 'card', row, settings })
      continue
    }
    const members = groups.get(group)
    if (members) members.push(row)
    else {
      const created = [row]
      groups.set(group, created)
      items.push({ kind: 'group', group, rows: created })
    }
  }
  return { items, hiddenCount: settled.filter(({ settings }) => settings.hidden).length }
}

export function pinnedEntries(view: BenchView | null): BenchViewDisplayEntry[] {
  return (view?.display ?? [])
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => entry.pinned && !entry.hidden)
    .sort((a, b) => sortKey(a.entry.order) - sortKey(b.entry.order) || a.index - b.index)
    .map(({ entry }) => entry)
}

export function hiddenEntries(view: BenchView | null): BenchViewDisplayEntry[] {
  return (view?.display ?? []).filter((entry) => entry.hidden)
}

/** Distinct plot group names in the view, for the "Plot group ▸" menu. */
export function plotGroups(view: BenchView | null): string[] {
  const names = (view?.display ?? []).flatMap((entry) =>
    entry.plot_group ? [entry.plot_group] : []
  )
  return [...new Set(names)].sort((a, b) => a.localeCompare(b))
}

export interface OrderedMember {
  target: BenchViewTarget
  order: number | null
}

/** One drop (or Move earlier/later): the new `order` of each moved card, one PATCH (§1).
 *  Unordered cards sort after ordered ones, so every item up to the moved position gets an
 *  explicit order; only changed values are sent, capped at one request's op limit. */
export function reorderOps(
  items: readonly (readonly OrderedMember[])[],
  from: number,
  to: number
): SetDisplayOp[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return []
  const next = [...items]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  const last = Math.min(Math.max(from, to), BENCH_VIEW_LIMITS.maxOrder)
  return next
    .slice(0, last + 1)
    .flatMap((members, index) =>
      members
        .filter((member) => member.order !== index)
        .map(
          (member): SetDisplayOp => ({
            kind: 'set_display',
            target: member.target,
            patch: { order: index }
          })
        )
    )
    .slice(0, BENCH_VIEW_LIMITS.maxOps)
}
