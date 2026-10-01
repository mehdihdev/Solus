import { describe, expect, it } from 'vitest'
import type { ApiMeta } from '../../lib/api/envelope.types'
import type { ActivityApi } from '../../lib/api/resources'
import { mergeActivityRefresh } from './mergeActivity'

const row = (id: string): ActivityApi => ({
  id,
  type: 't',
  domain: null,
  actor_id: null,
  project_id: null,
  payload: {},
  created_at: ''
})
const page = (ids: string[], meta: ApiMeta = {}): { data: ActivityApi[]; meta: ApiMeta } => ({
  data: ids.map(row),
  meta
})

describe('mergeActivityRefresh', () => {
  it('stitches new rows on top of what is loaded, keeping the old cursor', () => {
    const merged = mergeActivityRefresh(
      { items: [row('b'), row('c')], meta: { has_next: true, next_cursor: 'c1', total: 4 } },
      page(['a', 'b'], { has_next: true, next_cursor: 'c2', total: 5 })
    )
    expect(merged.items.map((i) => i.id)).toEqual(['a', 'b', 'c'])
    expect(merged.meta).toEqual({ has_next: true, next_cursor: 'c1', total: 5 })
  })

  it('keeps already loaded older pages and their cursor when the fresh page overlaps', () => {
    const merged = mergeActivityRefresh(
      {
        items: ['c', 'd', 'e', 'f'].map(row),
        meta: { has_next: true, next_cursor: 'after-f', total: 9 }
      },
      page(['x', 'c', 'd'], { has_next: true, next_cursor: 'after-d', total: 10 })
    )
    expect(merged.items.map((i) => i.id)).toEqual(['x', 'c', 'd', 'e', 'f'])
    expect(merged.meta).toEqual({ has_next: true, next_cursor: 'after-f', total: 10 })
  })

  it('never duplicates an id', () => {
    const merged = mergeActivityRefresh(
      { items: ['a', 'b', 'c', 'd'].map(row), meta: { has_next: false } },
      page(['a', 'b'], { has_next: true, next_cursor: 'k' })
    )
    expect(new Set(merged.items.map((i) => i.id)).size).toBe(merged.items.length)
  })

  it('falls back to the fresh page when it does not overlap what was loaded (possible gap)', () => {
    const merged = mergeActivityRefresh(
      { items: ['y', 'z', 'w'].map(row), meta: { has_next: true, next_cursor: 'old' } },
      page(['a', 'b'], { has_next: true, next_cursor: 'new' })
    )
    expect(merged.items.map((i) => i.id)).toEqual(['a', 'b'])
    expect(merged.meta.next_cursor).toBe('new')
  })

  it('handles an empty previous feed and an empty fresh page', () => {
    expect(mergeActivityRefresh({ items: [], meta: {} }, page(['a'])).items).toHaveLength(1)
    expect(mergeActivityRefresh({ items: [row('a')], meta: {} }, page([])).items).toHaveLength(0)
  })

  it('does not mutate its inputs', () => {
    const previous = { items: ['a', 'b', 'c'].map(row), meta: { next_cursor: 'k', has_next: true } }
    const snapshot = JSON.stringify(previous)
    mergeActivityRefresh(previous, page(['z', 'a']))
    expect(JSON.stringify(previous)).toBe(snapshot)
  })
})
