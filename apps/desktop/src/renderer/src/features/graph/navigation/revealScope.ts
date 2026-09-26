import type { GraphNavigatorProps } from './GraphNavigator'
import { buildNavigationIndex, type NavigationIndex } from './graphIndex'

/** Resolve hidden targets through project-scoped projections, never a fabricated entity. */
export function revealScope(
  props: GraphNavigatorProps,
  current: NavigationIndex,
  entityId: string
): { index: NavigationIndex; rootId?: string } | null {
  if (current.entities.has(entityId)) return { index: current }
  if (!props.scopeGraph) return null
  for (const rootId of props.scopeRootIds ?? []) {
    const graph = props.scopeGraph(rootId)
    const entities = graph.entities.filter(
      (entity) => entity.project_id === undefined || entity.project_id === props.projectId
    )
    if (!entities.some((entity) => entity.id === entityId)) continue
    const index = buildNavigationIndex(entities, graph.relations)
    return { index, rootId }
  }
  return null
}
