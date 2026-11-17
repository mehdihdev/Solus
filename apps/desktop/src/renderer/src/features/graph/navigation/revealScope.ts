import type { GraphNavigatorProps } from './GraphNavigator'
import { buildNavigationIndex, inGraph, type NavigationIndex } from './graphIndex'

/** Resolve hidden targets through project-scoped projections, never a fabricated entity.
 * Hardware not yet added to the graph has no card, so it is never revealed (the Hardware page
 * shows it). */
export function revealScope(
  props: GraphNavigatorProps,
  current: NavigationIndex,
  entityId: string
): { index: NavigationIndex; rootId?: string } | null {
  const known = current.entities.get(entityId)
  if (known) return inGraph(known) ? { index: current } : null
  if (!props.scopeGraph) return null
  for (const rootId of props.scopeRootIds ?? []) {
    const graph = props.scopeGraph(rootId)
    const entities = graph.entities.filter(
      (entity) => entity.project_id === undefined || entity.project_id === props.projectId
    )
    const target = entities.find((entity) => entity.id === entityId)
    if (!target) continue
    if (!inGraph(target)) return null
    const index = buildNavigationIndex(entities, graph.relations)
    return { index, rootId }
  }
  return null
}
