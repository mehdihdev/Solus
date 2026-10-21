import { describe, expect, it } from 'vitest'
import type { PaletteItem } from './paletteItems'
import { buildSections, flattenSections, scoreItem } from './paletteRank'

const item = (
  key: string,
  kind: PaletteItem['kind'],
  label: string,
  extra: Partial<PaletteItem> = {}
): PaletteItem => ({
  key,
  kind,
  label,
  target: { type: 'screen', screen: 'home' },
  ...extra
})

describe('scoreItem', () => {
  it('ranks prefix over word start over substring over subsequence', () => {
    const prefix = scoreItem(item('a', 'node', 'Motor driver'), 'mot')
    const wordStart = scoreItem(item('b', 'node', 'Left motor'), 'mot')
    const inner = scoreItem(item('c', 'node', 'Locomotion'), 'mot')
    const subsequence = scoreItem(item('d', 'node', 'Main output'), 'mot')
    expect(prefix).toBeGreaterThan(wordStart!)
    expect(wordStart).toBeGreaterThan(inner!)
    expect(inner).toBeGreaterThan(subsequence!)
  })

  it('is case-insensitive and trims the query', () => {
    expect(scoreItem(item('a', 'page', 'Live Bench'), '  LIVE ')).not.toBeNull()
  })

  it('matches keywords and detail below the label', () => {
    const viaKeyword = scoreItem(
      item('a', 'page', 'Live Bench', { keywords: ['telemetry'] }),
      'telem'
    )
    const viaLabel = scoreItem(item('b', 'page', 'Telemetry'), 'telem')
    expect(viaKeyword).not.toBeNull()
    expect(viaLabel).toBeGreaterThan(viaKeyword!)
    expect(scoreItem(item('c', 'project', 'Car', { detail: 'FSAE' }), 'fsae')).not.toBeNull()
  })

  it('returns null when nothing matches', () => {
    expect(scoreItem(item('a', 'page', 'Home'), 'xyz')).toBeNull()
  })
})

describe('buildSections', () => {
  const items = [
    item('page:home', 'page', 'Home'),
    item('page:bench', 'page', 'Live Bench'),
    item('project:p1', 'project', 'Mars Rover'),
    item('team:t1', 'team', 'Rover Lab'),
    item('node:p1:e1', 'node', 'Rover chassis'),
    item('node:p1:e2', 'node', 'IMU')
  ]

  it('groups an empty query as recents, pages, projects and teams — nodes stay out', () => {
    const sections = buildSections(items, '', 'all', ['project:p1'])
    expect(sections.map((s) => s.title)).toEqual(['Recents', 'Pages', 'Projects', 'Teams'])
    expect(sections[0].items.map((i) => i.key)).toEqual(['project:p1'])
  })

  it('drops recents that no longer resolve to a live item', () => {
    const sections = buildSections(items, '', 'all', ['node:p9:gone', 'page:home'])
    expect(sections[0].items.map((i) => i.key)).toEqual(['page:home'])
  })

  it('omits the recents section when there are none', () => {
    expect(buildSections(items, '', 'all', []).map((s) => s.title)).not.toContain('Recents')
  })

  it('searches every kind for a query and orders by score within a kind', () => {
    const sections = buildSections(items, 'rover', 'all', [])
    expect(sections.map((s) => s.title)).toEqual(['Projects', 'Teams', 'Nodes'])
    expect(sections[2].items.map((i) => i.label)).toEqual(['Rover chassis'])
  })

  it('restricts to one kind under a filter and lists nodes for an empty query there', () => {
    const sections = buildSections(items, '', 'node', ['page:home'])
    expect(sections).toEqual([{ title: 'Nodes', items: [items[4], items[5]] }])
  })

  it('caps each section under "all" so one kind cannot drown the rest', () => {
    const many = Array.from({ length: 30 }, (_, i) => item(`node:p:${i}`, 'node', `Node ${i}`))
    const [nodes] = buildSections(many, 'node', 'all', [])
    expect(nodes.items).toHaveLength(8)
  })

  it('lists every main screen in an empty "All" view, Settings included', () => {
    const screens = ['home', 'workspace', 'bench', 'sol', 'store', 'billing', 'settings'].map(
      (id) => item(`page:${id}`, 'page', id)
    )
    const [pages] = buildSections(screens, '', 'all', [])
    expect(pages.items).toHaveLength(7)
  })

  it('returns no sections when nothing matches', () => {
    expect(buildSections(items, 'zzz', 'all', [])).toEqual([])
  })
})

describe('flattenSections', () => {
  it('flattens in display order so arrow keys walk the visible list', () => {
    const a = item('a', 'page', 'A')
    const b = item('b', 'team', 'B')
    expect(
      flattenSections([
        { title: 'Pages', items: [a] },
        { title: 'Teams', items: [b] }
      ])
    ).toEqual([a, b])
  })
})
