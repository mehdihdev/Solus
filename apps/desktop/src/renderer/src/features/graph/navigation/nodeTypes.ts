import type { Entity, Relation } from '../../../lib/api/resources'

/** Node types describe containment; navigation has no provider or store knowledge. */
export interface GraphIndex {
  readonly entities: ReadonlyMap<string, Entity>
  readonly outgoing: ReadonlyMap<string, readonly Relation[]>
  readonly incoming: ReadonlyMap<string, readonly Relation[]>
}

export interface NodeTypeDefinition {
  children(entity: Entity, graph: GraphIndex): readonly Relation[]
}

const CONTAINMENT: NodeTypeDefinition = {
  children: (entity, graph) => [
    ...(graph.outgoing.get(entity.id) ?? []).filter((edge) => edge.type === 'contains'),
    ...(graph.incoming.get(entity.id) ?? []).filter((edge) => edge.type === 'part_of')
  ]
}

/** Real graph-backed types share containment unless they explicitly declare another relation. */
export class NodeTypeRegistry {
  private readonly types: ReadonlyMap<string, NodeTypeDefinition>

  constructor(types: Readonly<Record<string, NodeTypeDefinition>> = {}) {
    this.types = new Map(Object.entries(types))
  }

  children(entity: Entity, graph: GraphIndex): readonly Relation[] {
    return (this.types.get(entity.type) ?? CONTAINMENT).children(entity, graph)
  }
}

/** Requirement kinds a folder shows under itself through `requires` (SOLUSDEV-320). */
const REQUIREMENT_TYPES = new Set(['python_requirement', 'package_requirement'])

const LOCAL_FOLDER: NodeTypeDefinition = {
  children: (entity, graph) => [
    ...CONTAINMENT.children(entity, graph),
    ...(graph.outgoing.get(entity.id) ?? []).filter(
      (edge) =>
        edge.type === 'requires' &&
        REQUIREMENT_TYPES.has(graph.entities.get(edge.to_entity_id)?.type ?? '')
    )
  ]
}

/** A finding observes its subjects; it never owns anything on the canvas. */
const LEAF: NodeTypeDefinition = { children: () => [] }

export const NODE_TYPES = new NodeTypeRegistry({
  local_clone: LOCAL_FOLDER,
  local_folder: LOCAL_FOLDER,
  finding: LEAF,
  // Explicit so the vocabulary reads here: member --contains--> machine (default containment).
  member: CONTAINMENT
})
