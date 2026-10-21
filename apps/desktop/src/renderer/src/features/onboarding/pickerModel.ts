// Pure rules behind the multi-select picker: search, row order, toggling and the
// edit diff. Kept out of the component so each rule is tested on its own.
import type { SelectableItem } from '../../lib/api/resources'
import { plural } from './selectionConfigureStep'

/** Items whose name contains the query, ignoring case. A blank query keeps all. */
export function matches(items: readonly SelectableItem[], query: string): SelectableItem[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return [...items]
  return items.filter((item) => item.name.toLowerCase().includes(needle))
}

function editedAt(item: SelectableItem): number {
  const t = item.modified_at ? Date.parse(item.modified_at) : Number.NaN
  return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t
}

/** Most recently edited first; undated items keep their listing order at the end.
 *  Similar names ("Assembly 21", "Assembly 22") are told apart by recency. */
export function orderItems(items: readonly SelectableItem[]): SelectableItem[] {
  return items
    .map((item, index) => ({ item, index, t: editedAt(item) }))
    .sort((x, y) => (y.t === x.t ? x.index - y.index : y.t > x.t ? 1 : -1))
    .map(({ item }) => item)
}

export function toggled(chosen: readonly string[], id: string): string[] {
  return chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]
}

/** "Select all shown": add every shown id, or clear them when all are chosen.
 *  Choices outside the current view are never touched. */
export function toggledAll(chosen: readonly string[], shown: readonly string[]): string[] {
  const allChosen = shown.length > 0 && shown.every((id) => chosen.includes(id))
  if (allChosen) return chosen.filter((id) => !shown.includes(id))
  return [...chosen, ...shown.filter((id) => !chosen.includes(id))]
}

export interface SelectionDiff {
  added: string[]
  removed: string[]
}

export function selectionDiff(
  initial: readonly string[],
  chosen: readonly string[]
): SelectionDiff {
  return {
    added: chosen.filter((id) => !initial.includes(id)),
    removed: initial.filter((id) => !chosen.includes(id))
  }
}

export function countOf(n: number, label: string): string {
  return `${n} ${n === 1 ? label : plural(label)}`
}

/** The connect footer's primary action. */
export function confirmLabel(n: number, label: string): string {
  return n === 0 ? `Track ${plural(label)}` : `Track ${countOf(n, label)}`
}
