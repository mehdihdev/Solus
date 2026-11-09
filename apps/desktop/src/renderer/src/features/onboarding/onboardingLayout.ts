// SOLUSDEV-323: pure geometry for the redesigned onboarding — the Connect step's
// tool ring and the Build step's graph (docs/wireflows/onboarding.md §5, §6).
// No React, no randomness: the same input always draws the same picture.
import type { Domain } from './domainHearing'

/** The ring shows at most this many tiles; the rest go in the grid below it. */
export const RING_MAX = 8

/** Ring tile width, px (ConnectRing renders tiles this wide). */
export const RING_TILE_WIDTH = 160
const RING_RX = 250
/** Below this radius the tiles crowd the hub — use the grid instead. */
const RING_MIN_RX = 170
const RING_EDGE = 8

/**
 * The ring's horizontal radius for a stage `width` px wide (null = not measured
 * yet → the full radius), shrunk so the outermost tiles stay inside the stage;
 * null when even the smallest ring would not fit (render the grid instead).
 */
export function ringRadiusFor(width: number | null): number | null {
  if (width === null) return RING_RX
  const rx = Math.min(RING_RX, Math.floor(width / 2 - RING_TILE_WIDTH / 2 - RING_EDGE))
  return rx < RING_MIN_RX ? null : rx
}

export interface RingOptions {
  /** Ellipse radii from the hub, px. */
  rx?: number
  ry?: number
  /** The hub orb's radius, where each wire starts. */
  hubRadius?: number
}

export interface RingSlot {
  /** Tile centre relative to the hub, px. */
  x: number
  y: number
  /** The wire from the hub's edge to the tile centre. */
  wireLength: number
  wireAngle: number
}

const round = (n: number): number => Math.round(n) || 0 // never -0

/** Even slots round an ellipse, starting at 12 o'clock and going clockwise. */
export function ringSlots(count: number, opts: RingOptions = {}): RingSlot[] {
  const { rx = 250, ry = 165, hubRadius = 44 } = opts
  const n = Math.min(count, RING_MAX)
  return Array.from({ length: n }, (_, i) => {
    const a = ((-90 + (i * 360) / n) * Math.PI) / 180
    const x = round(rx * Math.cos(a))
    const y = round(ry * Math.sin(a))
    return {
      x,
      y,
      wireLength: Math.max(0, round(Math.hypot(x, y) - hubRadius)),
      wireAngle: round((Math.atan2(y, x) * 180) / Math.PI)
    }
  })
}

export interface GraphSource {
  domain: Domain
  /** Entities the source's latest sync created (0 = nothing synced yet). */
  entities: number
}

export interface GraphNode {
  /** Percent of the panel. */
  x: number
  y: number
  domain: Domain
}

export interface GraphEdge {
  from: number
  to: number
}

export interface GraphPicture {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

const MAX_NODES_PER_SOURCE = 7
const MIN_NODES_PER_SOURCE = 2
const CLUSTER_RING = 24
const NODE_RING = 11
const EDGE_PAD = 8

/** Nodes for one source: grows with the log of its entities, capped for legibility. */
function nodesFor(entities: number): number {
  const n = Math.ceil(Math.log2(entities + 1))
  return Math.min(MAX_NODES_PER_SOURCE, Math.max(MIN_NODES_PER_SOURCE, n))
}

const clamp = (v: number): number => Math.min(100 - EDGE_PAD, Math.max(EDGE_PAD, v))

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180
  return [clamp(round(cx + r * Math.cos(a))), clamp(round(cy + r * Math.sin(a)))]
}

/**
 * A legible picture of the real graph: one cluster per synced source in its
 * domain colour, a hub-and-spoke inside each, and hub-to-hub links between
 * clusters (the cross-domain edges the product is about).
 */
export function graphFor(sources: readonly GraphSource[]): GraphPicture {
  const synced = sources.filter((s) => s.entities > 0)
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []
  const hubs: number[] = []
  synced.forEach((source, ci) => {
    const [cx, cy] =
      synced.length === 1 ? [50, 50] : polar(50, 50, CLUSTER_RING, -90 + (ci * 360) / synced.length)
    const hub = nodes.length
    hubs.push(hub)
    nodes.push({ x: cx, y: cy, domain: source.domain })
    const spokes = nodesFor(source.entities) - 1
    for (let j = 0; j < spokes; j += 1) {
      const [x, y] = polar(cx, cy, NODE_RING, ci * 37 + (j * 360) / spokes)
      edges.push({ from: hub, to: nodes.length })
      nodes.push({ x, y, domain: source.domain })
    }
  })
  hubs.forEach((hub, i) => {
    const next = hubs[(i + 1) % hubs.length]
    if (hubs.length > 1 && (hubs.length > 2 || i === 0)) edges.push({ from: hub, to: next })
  })
  return { nodes, edges }
}
