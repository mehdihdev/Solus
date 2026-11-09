// SOLUSDEV-323: pure geometry for the Connect ring and the Build graph.
import { describe, it, expect } from 'vitest'
import { RING_MAX, graphFor, ringRadiusFor, ringSlots } from './onboardingLayout'

describe('ringSlots', () => {
  it('places nothing for an empty catalog', () => {
    expect(ringSlots(0)).toEqual([])
  })

  it('starts at 12 o’clock and spreads evenly round the ellipse', () => {
    const slots = ringSlots(4, { rx: 200, ry: 100 })
    expect(slots.map((s) => [s.x, s.y])).toEqual([
      [0, -100],
      [200, 0],
      [0, 100],
      [-200, 0]
    ])
  })

  it('gives each slot the wire from the hub: length and angle', () => {
    const [top] = ringSlots(1, { rx: 200, ry: 100, hubRadius: 30 })
    expect(top.wireLength).toBe(70)
    expect(top.wireAngle).toBe(-90)
  })

  it('never places more than RING_MAX tiles', () => {
    expect(ringSlots(12)).toHaveLength(RING_MAX)
  })
})

describe('graphFor', () => {
  it('draws nothing until a source has synced', () => {
    expect(graphFor([])).toEqual({ nodes: [], edges: [] })
    expect(graphFor([{ domain: 'sw', entities: 0 }])).toEqual({ nodes: [], edges: [] })
  })

  it('gives each synced source a cluster in its own domain', () => {
    const g = graphFor([
      { domain: 'sw', entities: 40 },
      { domain: 'ee', entities: 3 }
    ])
    const domains = new Set(g.nodes.map((n) => n.domain))
    expect(domains).toEqual(new Set(['sw', 'ee']))
    // More entities → more nodes, within the cap.
    const sw = g.nodes.filter((n) => n.domain === 'sw').length
    const ee = g.nodes.filter((n) => n.domain === 'ee').length
    expect(sw).toBeGreaterThan(ee)
    expect(sw).toBeLessThanOrEqual(7)
  })

  it('keeps every node inside the panel (percent coordinates)', () => {
    const g = graphFor([
      { domain: 'sw', entities: 900 },
      { domain: 'ee', entities: 900 },
      { domain: 'me', entities: 900 },
      { domain: 'rt', entities: 900 }
    ])
    for (const n of g.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(8)
      expect(n.x).toBeLessThanOrEqual(92)
      expect(n.y).toBeGreaterThanOrEqual(8)
      expect(n.y).toBeLessThanOrEqual(92)
    }
  })

  it('links clusters to each other so cross-domain edges exist', () => {
    const g = graphFor([
      { domain: 'sw', entities: 10 },
      { domain: 'ee', entities: 10 }
    ])
    const cross = g.edges.filter((e) => g.nodes[e.from].domain !== g.nodes[e.to].domain)
    expect(cross.length).toBeGreaterThan(0)
  })

  it('is deterministic for the same input', () => {
    const input = [{ domain: 'me' as const, entities: 12 }]
    expect(graphFor(input)).toEqual(graphFor(input))
  })
})

describe('ringRadiusFor (fits the stage — SOLUSDEV-323 review)', () => {
  it('uses the full radius when the stage is wide or not yet measured', () => {
    expect(ringRadiusFor(null)).toBe(250)
    expect(ringRadiusFor(1200)).toBe(250)
  })

  it('shrinks so the outermost tiles stay inside the stage', () => {
    const rx = ringRadiusFor(560)
    expect(rx).not.toBeNull()
    // Tile centre ± half a tile width must stay within ±width/2.
    expect((rx as number) + 80).toBeLessThanOrEqual(280)
  })

  it('gives up on the ring (grid instead) when the stage is too narrow', () => {
    expect(ringRadiusFor(380)).toBeNull()
  })
})
