// Pure view-model helpers for the Context Model graph screen, extracted from
// the inline logic in TestDesign/app/graph.jsx so they stay unit-testable.
// Graph in, derived structures out — no hidden state (root coding standards).
import type { DomainId } from '../../theme/tokens.constants'
import type { Alert, GraphData, GraphEdge, GraphNode } from '../workspace/workspaceData.constants'

export type NodeIndex = Readonly<Record<string, GraphNode>>

export interface NeighborLink {
  readonly id: string
  readonly label?: string
}

export type NeighborMap = Readonly<Record<string, readonly NeighborLink[]>>

export type DomainFilter = Readonly<Record<DomainId, boolean>>

/** Zoom bounds from the prototype: zoom() clamps to [0.55, 1.6]. */
export const GRAPH_MIN_SCALE = 0.55
export const GRAPH_MAX_SCALE = 1.6

export function buildNodeIndex(graph: GraphData): NodeIndex {
  const index: Record<string, GraphNode> = {}
  for (const node of graph.nodes) {
    index[node.id] = node
  }
  return index
}

export function buildNeighbors(graph: GraphData): NeighborMap {
  const map: Record<string, NeighborLink[]> = {}
  for (const [from, to, label] of graph.edges) {
    map[from] = [...(map[from] ?? []), { id: to, label }]
    map[to] = [...(map[to] ?? []), { id: from, label }]
  }
  return map
}

export function isEdgeVisible(
  edge: GraphEdge,
  byId: NodeIndex,
  domains: DomainFilter,
  xOnly: boolean
): boolean {
  const [from, to] = edge
  const a = byId[from]
  const b = byId[to]
  if (!a || !b) return false
  if (!domains[a.d] || !domains[b.d]) return false
  if (xOnly && a.d === b.d) return false
  return true
}

export function findOpenAlert(node: GraphNode, alerts: readonly Alert[]): Alert | undefined {
  if (!node.alert) return undefined
  return alerts.find((alert) => alert.id === node.alert && alert.state === 'open')
}

export function clampScale(scale: number): number {
  return Math.min(GRAPH_MAX_SCALE, Math.max(GRAPH_MIN_SCALE, scale))
}

/** Hovered node plus its direct neighbors; null when nothing is hovered. */
export function hotSetFor(
  hover: string | null,
  neighbors: NeighborMap
): ReadonlySet<string> | null {
  if (!hover) return null
  return new Set([hover, ...(neighbors[hover] ?? []).map((n) => n.id)])
}

/** Label pill width in viewBox units — the prototype's sizing formula. */
export function nodeWidth(node: GraphNode): number {
  return node.l.length * 6.7 + 30
}
