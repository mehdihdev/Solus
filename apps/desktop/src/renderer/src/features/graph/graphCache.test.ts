import { describe, it, expect } from 'vitest'
import { GRAPH_CACHE_TTL_MS, countsOf, graphVersionOf, isGraphCacheValid } from './graphCache'
import type { ProjectDetail } from '../../lib/api/resources'

const DETAIL: ProjectDetail = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover',
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: '',
  stats: { entities: 12, relations: 30 },
  sources: [{ id: 's1', last_synced_at: '2026-09-01T00:00:00Z', updated_at: 'u1' }]
}

describe('graphVersionOf', () => {
  it('is stable for an unchanged detail and ignores unrelated fields', () => {
    expect(graphVersionOf(DETAIL)).toBe(graphVersionOf({ ...DETAIL, name: 'renamed' }))
  })

  it('changes when counts change', () => {
    const changed = { ...DETAIL, stats: { entities: 13, relations: 30 } }
    expect(graphVersionOf(changed)).not.toBe(graphVersionOf(DETAIL))
  })

  it('changes when a source syncs again', () => {
    const synced = { ...DETAIL, sources: [{ ...(DETAIL.sources[0] as object), last_synced_at: 'later' }] }
    expect(graphVersionOf(synced)).not.toBe(graphVersionOf(DETAIL))
  })

  it('tolerates sources of unknown shape', () => {
    expect(() => graphVersionOf({ ...DETAIL, sources: [null, 3, 'x'] })).not.toThrow()
  })
})

describe('isGraphCacheValid', () => {
  const entry = { version: graphVersionOf(DETAIL), entities: [], counts: countsOf(DETAIL), fetchedAtMs: 1_000 }

  it('is false without an entry', () => {
    expect(isGraphCacheValid(undefined, DETAIL, 1_000)).toBe(false)
  })

  it('is true for a matching version inside the TTL', () => {
    expect(isGraphCacheValid(entry, DETAIL, 1_000 + GRAPH_CACHE_TTL_MS - 1)).toBe(true)
  })

  it('expires at the TTL even when the version still matches', () => {
    expect(isGraphCacheValid(entry, DETAIL, 1_000 + GRAPH_CACHE_TTL_MS)).toBe(false)
  })

  it('is false when the graph changed', () => {
    const changed = { ...DETAIL, stats: { entities: 0, relations: 0 } }
    expect(isGraphCacheValid(entry, changed, 1_001)).toBe(false)
  })
})
