// SOLUSDEV-317 — ranking and grouping for the ⌘K palette. Pure: items + query +
// filter + recent keys in, titled sections out. Scoring is deliberately simple
// and predictable (prefix > word start > substring > in-order letters), labels
// before keywords before detail; ties keep the source order.
import type { PaletteItem, PaletteKind } from './paletteItems'

export type PaletteFilter = 'all' | PaletteKind

export interface PaletteSection {
  title: string
  items: PaletteItem[]
}

export const SECTION_TITLES: Readonly<Record<PaletteKind, string>> = {
  page: 'Pages',
  project: 'Projects',
  team: 'Teams',
  node: 'Nodes'
}

const KIND_ORDER: readonly PaletteKind[] = ['page', 'project', 'team', 'node']
/** Per-kind cap under "All" so a big graph cannot push pages off the list. */
const ALL_CAP: Readonly<Record<PaletteKind, number>> = { page: 8, project: 6, team: 4, node: 8 }
const FILTERED_CAP = 50
const RECENTS_CAP = 6

/** Score one text against a lowercased, trimmed query; null when it does not match. */
function scoreText(text: string, q: string): number | null {
  const t = text.toLowerCase()
  if (t.startsWith(q)) return 100
  if (t.split(/[\s_\-./·]+/).some((word) => word.startsWith(q))) return 80
  if (t.includes(q)) return 60
  let at = 0
  for (const ch of q) {
    at = t.indexOf(ch, at)
    if (at === -1) return null
    at += 1
  }
  return 30
}

export function scoreItem(item: PaletteItem, query: string): number | null {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const label = scoreText(item.label, q)
  if (label !== null) return label + 1
  const keyword = Math.max(
    -1,
    ...(item.keywords ?? []).map((k) => (k.toLowerCase().startsWith(q) ? 20 : -1))
  )
  if (keyword > 0) return keyword
  return item.detail?.toLowerCase().includes(q) ? 10 : null
}

function ranked(items: readonly PaletteItem[], query: string): PaletteItem[] {
  return items
    .map((item, index) => ({ item, index, score: scoreItem(item, query) }))
    .filter((r): r is typeof r & { score: number } => r.score !== null)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((r) => r.item)
}

function recentSection(
  items: readonly PaletteItem[],
  recentKeys: readonly string[]
): PaletteSection[] {
  const byKey = new Map(items.map((item) => [item.key, item]))
  const recents = recentKeys
    .map((key) => byKey.get(key))
    .filter((item): item is PaletteItem => item !== undefined)
    .slice(0, RECENTS_CAP)
  return recents.length ? [{ title: 'Recents', items: recents }] : []
}

export function buildSections(
  items: readonly PaletteItem[],
  query: string,
  filter: PaletteFilter,
  recentKeys: readonly string[]
): PaletteSection[] {
  const empty = query.trim() === ''
  if (filter !== 'all') {
    const matches = ranked(
      items.filter((item) => item.kind === filter),
      query
    ).slice(0, FILTERED_CAP)
    return matches.length ? [{ title: SECTION_TITLES[filter], items: matches }] : []
  }
  // An empty "All" is a jump list, not a dump of the whole graph: nodes need a query.
  const kinds = empty ? KIND_ORDER.filter((kind) => kind !== 'node') : KIND_ORDER
  const sections = kinds
    .map((kind) => ({
      title: SECTION_TITLES[kind],
      items: ranked(
        items.filter((item) => item.kind === kind),
        query
      ).slice(0, ALL_CAP[kind])
    }))
    .filter((section) => section.items.length > 0)
  return empty ? [...recentSection(items, recentKeys), ...sections] : sections
}

export function flattenSections(sections: readonly PaletteSection[]): PaletteItem[] {
  return sections.flatMap((section) => section.items)
}
