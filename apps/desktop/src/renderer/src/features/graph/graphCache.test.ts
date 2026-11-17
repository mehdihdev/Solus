import { describe, it, expect } from 'vitest'
import { graphVersionOf } from './graphCache'
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
  it('invalidates a manual rename even when source stamps and graph counts are unchanged', () => {
    const before = { ...DETAIL, graph_updated_at: '2026-09-06T01:00:00Z' }
    const after = { ...before, graph_updated_at: '2026-09-06T01:00:01Z' }
    expect(graphVersionOf(after)).not.toBe(graphVersionOf(before))
  })

  it('is stable for an unchanged detail and ignores unrelated fields', () => {
    expect(graphVersionOf(DETAIL)).toBe(graphVersionOf({ ...DETAIL, name: 'renamed' }))
  })

  it('changes when counts change', () => {
    const changed = { ...DETAIL, stats: { entities: 13, relations: 30 } }
    expect(graphVersionOf(changed)).not.toBe(graphVersionOf(DETAIL))
  })

  it('changes when a source syncs again', () => {
    const synced = {
      ...DETAIL,
      sources: [{ ...(DETAIL.sources[0] as object), last_synced_at: 'later' }]
    }
    expect(graphVersionOf(synced)).not.toBe(graphVersionOf(DETAIL))
  })

  it('tolerates sources of unknown shape', () => {
    expect(() => graphVersionOf({ ...DETAIL, sources: [null, 3, 'x'] })).not.toThrow()
  })
})
