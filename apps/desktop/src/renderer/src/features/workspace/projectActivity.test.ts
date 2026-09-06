import { describe, it, expect } from 'vitest'
import { groupActivityByProject } from './projectActivity'
import type { ActivityApi } from '../../lib/api/resources'

const row = (id: string, project_id: string | null): ActivityApi => ({
  id,
  type: 'project.updated',
  domain: null,
  actor_id: null,
  project_id,
  payload: {},
  created_at: ''
})

describe('groupActivityByProject', () => {
  it('splits rows by project, preserving feed order within each project', () => {
    const grouped = groupActivityByProject([row('a', 'p1'), row('b', 'p2'), row('c', 'p1')])
    expect(Object.keys(grouped)).toEqual(['p1', 'p2'])
    expect(grouped.p1.map((r) => r.id)).toEqual(['a', 'c'])
    expect(grouped.p2.map((r) => r.id)).toEqual(['b'])
  })
  it('drops team-level rows that name no project', () => {
    expect(groupActivityByProject([row('a', null)])).toEqual({})
  })
  it('is empty for an empty feed', () => {
    expect(groupActivityByProject([])).toEqual({})
  })
})
