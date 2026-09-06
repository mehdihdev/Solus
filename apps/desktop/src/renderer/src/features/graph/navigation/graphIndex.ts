import type { Entity, Relation } from '../../../lib/api/resources'
import { NODE_TYPES, type NodeTypeRegistry, type GraphIndex } from './nodeTypes'

export interface NavigationStep {
  readonly entity: Entity
  readonly relation: string
}

export interface NavigationIndex extends GraphIndex {
  readonly roots: readonly Entity[]
  readonly children: ReadonlyMap<string, readonly Entity[]>
  readonly parent: ReadonlyMap<string, { id: string; relation: Relation }>
  readonly crossLinks: readonly Relation[]
  pathTo(entityId: string): readonly NavigationStep[]
}

/** UUIDv7 order keeps newly created nodes after existing ones; .solus is always first. */
export function compareNodes(a: Entity, b: Entity): number {
  return (
    Number(b.type === 'solus_config') - Number(a.type === 'solus_config') ||
    a.id.localeCompare(b.id)
  )
}

function rawIndex(entities: readonly Entity[], relations: readonly Relation[]) {
  const byId = new Map(entities.map((entity) => [entity.id, entity]))
  const outgoing = new Map<string, Relation[]>()
  const incoming = new Map<string, Relation[]>()
  const valid = relations.filter(
    (edge) => byId.has(edge.from_entity_id) && byId.has(edge.to_entity_id)
  )
  for (const edge of valid) {
    outgoing.set(edge.from_entity_id, [...(outgoing.get(edge.from_entity_id) ?? []), edge])
    incoming.set(edge.to_entity_id, [...(incoming.get(edge.to_entity_id) ?? []), edge])
  }
  return { raw: { entities: byId, outgoing, incoming }, valid }
}

class ContainmentForest {
  readonly parent = new Map<string, { id: string; relation: Relation }>()
  readonly children = new Map<string, Entity[]>()
  readonly treeEdges = new Set<string>()

  constructor(private readonly graph: GraphIndex) {}

  private wouldCycle(parentId: string, childId: string): boolean {
    let ancestor: string | undefined = parentId
    while (ancestor !== undefined && ancestor !== childId) ancestor = this.parent.get(ancestor)?.id
    return ancestor === childId
  }

  add(entity: Entity, relation: Relation): void {
    const childId =
      relation.from_entity_id === entity.id ? relation.to_entity_id : relation.from_entity_id
    const child = this.graph.entities.get(childId)
    if (!child || this.parent.has(childId) || this.wouldCycle(entity.id, childId)) return
    this.parent.set(childId, { id: entity.id, relation })
    this.children.set(entity.id, [...(this.children.get(entity.id) ?? []), child])
    this.treeEdges.add(relation.id)
  }

  pathTo(entityId: string): readonly NavigationStep[] {
    const path: NavigationStep[] = []
    let step = this.parent.get(entityId)
    while (step) {
      const entity = this.graph.entities.get(step.id)
      if (!entity) break
      path.push({ entity, relation: step.relation.type })
      step = this.parent.get(step.id)
    }
    return path.reverse()
  }
}

export function buildNavigationIndex(
  entities: readonly Entity[],
  relations: readonly Relation[],
  registry: NodeTypeRegistry = NODE_TYPES
): NavigationIndex {
  const { raw, valid } = rawIndex(entities, relations)
  const forest = new ContainmentForest(raw)
  const sorted = [...raw.entities.values()].sort(compareNodes)

  for (const entity of sorted) {
    const candidates = [...registry.children(entity, raw)].sort((a, b) => a.id.localeCompare(b.id))
    for (const relation of candidates) forest.add(entity, relation)
  }
  for (const list of forest.children.values()) list.sort(compareNodes)

  return {
    ...raw,
    parent: forest.parent,
    children: forest.children,
    roots: sorted.filter((entity) => !forest.parent.has(entity.id)),
    crossLinks: valid
      .filter((edge) => !forest.treeEdges.has(edge.id))
      .sort((a, b) => a.id.localeCompare(b.id)),
    pathTo: (entityId) => forest.pathTo(entityId)
  }
}

export interface ProjectedLink {
  readonly relation: Relation
  /** Null is an endpoint outside the displayed page/branch, never a fabricated node. */
  readonly from: string | null
  readonly to: string | null
}

export function projectCrossLinks(
  index: NavigationIndex,
  visibleIds: readonly string[]
): ProjectedLink[] {
  const visible = new Set(visibleIds)
  const cached = new Map<string, string | null>()
  const representative = (id: string): string | null => {
    const traversed: string[] = []
    let current: string | undefined = id
    while (current !== undefined && !visible.has(current) && !cached.has(current)) {
      traversed.push(current)
      current = index.parent.get(current)?.id
    }
    const result =
      current === undefined ? null : visible.has(current) ? current : (cached.get(current) ?? null)
    for (const key of traversed) cached.set(key, result)
    return result
  }
  return index.crossLinks.flatMap((relation) => {
    const from = representative(relation.from_entity_id)
    const to = representative(relation.to_entity_id)
    return from === null && to === null ? [] : [{ relation, from, to }]
  })
}
