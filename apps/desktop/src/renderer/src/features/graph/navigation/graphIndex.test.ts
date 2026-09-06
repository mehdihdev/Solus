import { describe, expect, it } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { buildNavigationIndex, projectCrossLinks } from './graphIndex'
import { layoutLevel, levelBounds, CARD_HEIGHT, CARD_WIDTH } from './layout'
import { NodeTypeRegistry } from './nodeTypes'

const node = (id: string, type = 'part'): Entity => ({
  id,
  type,
  name: id,
  domain: 'mechanical',
  source_key: id
})
const edge = (id: string, from: string, to: string, type = 'contains'): Relation => ({
  id,
  type,
  from_entity_id: from,
  to_entity_id: to
})

describe('graph navigation index', () => {
  it('preserves real identity and one-level paths for mixed containment directions', () => {
    const entities = ['document', 'assembly', 'part', 'leaf'].map((id) => node(id))
    const index = buildNavigationIndex(entities, [
      edge('1', 'document', 'assembly'),
      edge('2', 'part', 'assembly', 'part_of'),
      edge('3', 'part', 'leaf')
    ])
    expect(index.roots.map((e) => e.id)).toEqual(['document'])
    expect(index.children.get('assembly')?.map((e) => e.id)).toEqual(['part'])
    expect(index.pathTo('leaf').map((step) => [step.entity.id, step.relation])).toEqual([
      ['document', 'contains'],
      ['assembly', 'part_of'],
      ['part', 'contains']
    ])
    expect(index.entities.get('leaf')).toBe(entities[3])
  })

  it('breaks cycles and chooses one parent deterministically while retaining extra links', () => {
    const entities = ['a', 'b', 'c'].map((id) => node(id))
    const relations = [edge('ab', 'a', 'b'), edge('ba', 'b', 'a'), edge('cb', 'c', 'b')]
    const index = buildNavigationIndex(entities, relations)
    const reversed = buildNavigationIndex([...entities].reverse(), [...relations].reverse())
    expect(index.roots.map((e) => e.id)).toEqual(reversed.roots.map((e) => e.id))
    expect(index.pathTo('b')).toEqual(reversed.pathTo('b'))
    expect(index.crossLinks.length).toBe(2)
    for (const entity of entities) {
      expect(new Set(index.pathTo(entity.id).map((p) => p.entity.id)).size).toBe(
        index.pathTo(entity.id).length
      )
    }
    expect(relations).toHaveLength(3)
  })

  it('projects cross-domain links to visible ancestors while preserving external endpoints', () => {
    const index = buildNavigationIndex(
      ['root', 'part', 'controller'].map((id) => node(id)),
      [edge('inside', 'root', 'part'), edge('wire', 'part', 'controller', 'connected_to')]
    )
    expect(projectCrossLinks(index, ['root', 'controller'])).toEqual([
      { relation: index.crossLinks[0], from: 'root', to: 'controller' }
    ])
    expect(projectCrossLinks(index, ['part'])).toEqual([
      { relation: index.crossLinks[0], from: 'part', to: null }
    ])
  })

  it('ignores dangling edges and supports a type declaring its children', () => {
    const registry = new NodeTypeRegistry({
      custom: { children: (entity, graph) => graph.outgoing.get(entity.id) ?? [] }
    })
    const index = buildNavigationIndex(
      [node('root', 'custom'), node('child')],
      [edge('child', 'root', 'child', 'owns'), edge('dangling', 'root', 'missing')],
      registry
    )
    expect(index.children.get('root')?.map((e) => e.id)).toEqual(['child'])
    expect(index.crossLinks).toEqual([])
  })
})

describe('bounded readable layout', () => {
  it('centers the first card within its frame in both axes', () => {
    const bounds = levelBounds(layoutLevel([node('solus', 'solus_config')], {}))
    expect(bounds.left + bounds.width / 2).toBe(0)
    expect(bounds.top + bounds.height / 2).toBe(0)
  })
  it('keeps the origin centered when two roots are added around the first node', () => {
    const positions = layoutLevel([node('solus', 'solus_config'), node('a'), node('b')], {})
    const bounds = levelBounds(positions)
    expect(positions.solus).toEqual({ x: 0, y: 0 })
    expect(bounds.left + bounds.width / 2).toBe(0)
    expect(bounds.top + bounds.height / 2).toBe(0)
  })
  it('centers .solus first, preserves saved coordinates and never overlaps default cards', () => {
    const entities = [
      node('z', 'solus_config'),
      ...Array.from({ length: 23 }, (_, i) => node(`n${i}`))
    ]
    const points = layoutLevel(entities, {})
    expect(points.z).toEqual({ x: 0, y: 0 })
    for (let i = 0; i < entities.length; i++) {
      for (let j = i + 1; j < entities.length; j++) {
        const a = points[entities[i].id]
        const b = points[entities[j].id]
        expect(Math.abs(a.x - b.x) >= CARD_WIDTH || Math.abs(a.y - b.y) >= CARD_HEIGHT).toBe(true)
      }
    }
    expect(layoutLevel(entities, { z: { x: 820, y: -500 } }).z).toEqual({ x: 820, y: -500 })
  })

  it('places new defaults around saved nodes without collisions and rejects nonfinite saved points', () => {
    const points = layoutLevel([node('a'), node('b'), node('c')], {
      a: { x: 0, y: 0 },
      b: { x: Infinity, y: 0 }
    })
    expect(points.a).toEqual({ x: 0, y: 0 })
    expect(points.b).not.toEqual(points.a)
    expect(Number.isFinite(points.b.x)).toBe(true)
    expect(points.c).not.toEqual(points.b)
  })
})
