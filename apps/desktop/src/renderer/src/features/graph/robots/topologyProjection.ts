import type { Entity, Relation } from '../../../lib/api/resources'
import type { HardwareTopology } from '../../../lib/api/hardwareTopology'

function matchingAncestors(topology: HardwareTopology, category: string | null): Set<string> {
  const kept = new Set(
    topology.nodes.filter((node) => !category || node.category === category).map((node) => node.id)
  )
  let changed = Boolean(category)
  while (changed) {
    changed = false
    for (const edge of topology.edges) {
      if (kept.has(edge.target) && !kept.has(edge.source)) {
        kept.add(edge.source)
        changed = true
      }
    }
  }
  return kept
}

class TopologyProjection {
  private readonly hidden = new Set<string>()
  private readonly replaced = new Set<string>()
  private readonly projected: Relation[] = []
  private readonly byId: Map<string, Entity>

  constructor(
    private readonly entities: Entity[],
    private readonly relations: Relation[]
  ) {
    this.byId = new Map(entities.map((entity) => [entity.id, entity]))
  }

  add(topology: HardwareTopology, category: string | null): void {
    if (!this.byId.has(topology.robot_id)) return
    const ids = new Set(topology.nodes.map((node) => node.id).filter((id) => this.byId.has(id)))
    const kept = matchingAncestors(topology, category)
    for (const id of ids) {
      this.replaced.add(id)
      if (!kept.has(id)) this.hidden.add(id)
    }
    this.flattenCategories(topology.robot_id, ids)
    const visible = (id: string): boolean => ids.has(id) && kept.has(id)
    for (const edge of topology.edges) {
      if (visible(edge.source) && visible(edge.target))
        this.projected.push({
          id: edge.id,
          from_entity_id: edge.source,
          to_entity_id: edge.target,
          type: 'contains'
        })
    }
    for (const id of topology.roots) {
      if (visible(id))
        this.projected.push({
          id: `topology-root:${topology.robot_id}:${id}`,
          from_entity_id: topology.robot_id,
          to_entity_id: id,
          type: 'contains'
        })
    }
  }

  private flattenCategories(robotId: string, ids: Set<string>): void {
    const categories = this.relations.filter(
      (edge) =>
        edge.type === 'contains' &&
        edge.from_entity_id === robotId &&
        this.byId.get(edge.to_entity_id)?.type === 'robot_category'
    )
    for (const edge of categories) {
      this.hidden.add(edge.to_entity_id)
      for (const child of this.relations.filter(
        (candidate) =>
          candidate.type === 'contains' && candidate.from_entity_id === edge.to_entity_id
      )) {
        if (!ids.has(child.to_entity_id)) this.projected.push({ ...child, from_entity_id: robotId })
      }
    }
  }

  scope(topologies: HardwareTopology[], rootId: string): void {
    const visible = new Set(
      topologies
        .filter((topology) => topology.robot_id === rootId)
        .flatMap((topology) => topology.nodes.map((node) => node.id))
    )
    for (const topology of topologies) {
      if (topology.robot_id === rootId) continue
      for (const node of topology.nodes) if (!visible.has(node.id)) this.hidden.add(node.id)
    }
  }

  snapshot(): { entities: Entity[]; relations: Relation[] } {
    const projectedIds = new Set(this.projected.map((edge) => edge.id))
    return {
      entities: this.entities.filter((entity) => !this.hidden.has(entity.id)),
      relations: [
        ...this.relations.filter(
          (edge) =>
            !this.hidden.has(edge.from_entity_id) &&
            !this.hidden.has(edge.to_entity_id) &&
            !this.isReplaced(edge) &&
            !projectedIds.has(edge.id)
        ),
        ...new Map(this.projected.map((edge) => [edge.id, edge])).values()
      ]
    }
  }

  private isReplaced(edge: Relation): boolean {
    return (
      (edge.type === 'contains' && this.replaced.has(edge.to_entity_id)) ||
      (edge.type === 'part_of' && this.replaced.has(edge.from_entity_id))
    )
  }
}

/** Presentation edges never enter graph storage or confer hardware operation authority. */
export function topologyProjection(
  entities: Entity[],
  relations: Relation[],
  topologies: HardwareTopology[],
  category: string | null,
  rootId: string | null = null
): { entities: Entity[]; relations: Relation[] } {
  const projection = new TopologyProjection(entities, relations)
  if (rootId) projection.scope(topologies, rootId)
  for (const topology of topologies) {
    if (!rootId || topology.robot_id === rootId) projection.add(topology, category)
  }
  return projection.snapshot()
}
