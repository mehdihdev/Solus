// SOLUSDEV-320 P4-T3 — registry cases: a finding is a leaf, a member contains its
// machines, a local folder/clone also shows every requirement it requires.
import { describe, expect, it } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { buildNavigationIndex } from './graphIndex'
import { NODE_TYPES } from './nodeTypes'

const node = (id: string, type: string): Entity => ({
  id,
  type,
  name: id,
  domain: 'code',
  source_key: id
})
const edge = (from: string, to: string, type: string): Relation => ({
  id: `${from}-${to}-${type}`,
  type,
  from_entity_id: from,
  to_entity_id: to
})

describe('NODE_TYPES', () => {
  it('a finding never has children even when it contains or observes something', () => {
    const index = buildNavigationIndex(
      [node('f', 'finding'), node('p', 'part')],
      [edge('f', 'p', 'contains'), edge('f', 'p', 'observed')]
    )
    expect(index.children.get('f') ?? []).toEqual([])
    expect(index.roots.map((entity) => entity.id)).toEqual(['p'])
  })

  it('a member contains its machines', () => {
    const index = buildNavigationIndex(
      [node('m', 'member'), node('h', 'machine')],
      [edge('m', 'h', 'contains')]
    )
    expect(index.children.get('m')?.map((entity) => entity.id)).toEqual(['h'])
  })

  it.each(['local_folder', 'local_clone'])(
    '%s shows python and package requirements it requires, nothing else',
    (type) => {
      const index = buildNavigationIndex(
        [
          node('dir', type),
          node('py', 'python_requirement'),
          node('npm', 'package_requirement'),
          node('other', 'part')
        ],
        [
          edge('dir', 'py', 'requires'),
          edge('dir', 'npm', 'requires'),
          edge('dir', 'other', 'requires')
        ]
      )
      expect(index.children.get('dir')?.map((entity) => entity.id)).toEqual(['npm', 'py'])
      expect(NODE_TYPES.children(node('dir', type), index)).toHaveLength(2)
    }
  )
})
