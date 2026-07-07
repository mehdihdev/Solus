import { describe, it, expect } from 'vitest'
import { GRAPH, ALERTS } from '../workspace/workspaceData.constants'
import type { GraphEdge, GraphNode } from '../workspace/workspaceData.constants'
import {
  buildNodeIndex,
  buildNeighbors,
  isEdgeVisible,
  findOpenAlert,
  clampScale,
  hotSetFor,
  nodeWidth,
  GRAPH_MIN_SCALE,
  GRAPH_MAX_SCALE,
  type DomainFilter
} from './graphModel'

const byId = buildNodeIndex(GRAPH)
const neighbors = buildNeighbors(GRAPH)
const ALL_ON: DomainFilter = { sw: true, ee: true, me: true, rt: true }

function edgeBetween(a: string, b: string): GraphEdge {
  const edge = GRAPH.edges.find(([from, to]) => from === a && to === b)
  if (!edge) throw new Error(`fixture edge ${a}->${b} missing`)
  return edge
}

function nodeById(id: string): GraphNode {
  const node = byId[id]
  if (!node) throw new Error(`fixture node ${id} missing`)
  return node
}

describe('buildNodeIndex', () => {
  it('indexes every graph node by its id', () => {
    expect(Object.keys(byId)).toHaveLength(GRAPH.nodes.length)
    expect(byId['drv']?.l).toBe('DRV8316C · U4')
  })
})

describe('buildNeighbors', () => {
  it('links both endpoints of an edge, carrying the edge label', () => {
    expect(neighbors['md']).toContainEqual({ id: 'pin', label: 'writes PWM duty' })
    expect(neighbors['pin']).toContainEqual({ id: 'md', label: 'writes PWM duty' })
  })

  it('leaves the label undefined for unlabeled edges', () => {
    expect(neighbors['drv']).toContainEqual({ id: 'vbat', label: undefined })
  })
})

describe('isEdgeVisible', () => {
  it('shows an edge when both endpoint domains are on', () => {
    expect(isEdgeVisible(edgeBetween('legik', 'md'), byId, ALL_ON, false)).toBe(true)
  })

  it('hides an edge when either endpoint domain is off', () => {
    const swOff: DomainFilter = { ...ALL_ON, sw: false }
    expect(isEdgeVisible(edgeBetween('legik', 'md'), byId, swOff, false)).toBe(false)
    expect(isEdgeVisible(edgeBetween('pin', 'm3pwm'), byId, swOff, false)).toBe(false)
  })

  it('hides same-domain edges in cross-domain-only mode', () => {
    expect(isEdgeVisible(edgeBetween('legik', 'md'), byId, ALL_ON, true)).toBe(false)
  })

  it('keeps cross-domain edges in cross-domain-only mode', () => {
    expect(isEdgeVisible(edgeBetween('pin', 'm3pwm'), byId, ALL_ON, true)).toBe(true)
  })
})

describe('findOpenAlert', () => {
  it('returns the open alert a node references', () => {
    expect(findOpenAlert(nodeById('md'), ALERTS)?.id).toBe('a1')
  })

  it('returns undefined when the referenced alert is resolved', () => {
    const resolved = ALERTS.map((a) => ({ ...a, state: 'resolved' as const }))
    expect(findOpenAlert(nodeById('md'), resolved)).toBeUndefined()
  })

  it('returns undefined for nodes without an alert reference', () => {
    expect(findOpenAlert(nodeById('legik'), ALERTS)).toBeUndefined()
  })
})

describe('clampScale', () => {
  it('clamps to the prototype zoom bounds', () => {
    expect(clampScale(0.1)).toBe(GRAPH_MIN_SCALE)
    expect(clampScale(5)).toBe(GRAPH_MAX_SCALE)
    expect(clampScale(1)).toBe(1)
  })
})

describe('hotSetFor', () => {
  it('is null when nothing is hovered', () => {
    expect(hotSetFor(null, neighbors)).toBeNull()
  })

  it('contains the hovered node and its direct neighbors', () => {
    const hot = hotSetFor('pin', neighbors)
    expect(hot?.has('pin')).toBe(true)
    expect(hot?.has('md')).toBe(true)
    expect(hot?.has('m3pwm')).toBe(true)
    expect(hot?.has('vbat')).toBe(false)
  })
})

describe('nodeWidth', () => {
  it("derives the label pill width from the prototype's formula", () => {
    const node = nodeById('md')
    expect(nodeWidth(node)).toBeCloseTo(node.l.length * 6.7 + 30)
  })
})
