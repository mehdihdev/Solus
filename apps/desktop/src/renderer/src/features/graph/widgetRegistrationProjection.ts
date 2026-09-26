import type { Entity, Relation } from '../../lib/api/resources'

function systemWorkspace(entity: Entity, projectId: string): boolean {
  return (
    entity.project_id === projectId && entity.domain === 'workspace' && entity.origin === 'system'
  )
}

export function isWidgetRegistration(entity: Entity, projectId: string): boolean {
  return (
    systemWorkspace(entity, projectId) && ['solus:live_bench', 'solus:widget'].includes(entity.type)
  )
}

/** Lift only persisted ST2 registrations. This never modifies graph storage. */
export function widgetRegistrationProjection(
  projectId: string,
  entities: readonly Entity[],
  relations: readonly Relation[]
): { entities: Entity[]; relations: Relation[] } {
  const containers = new Set(
    entities
      .filter((entity) => systemWorkspace(entity, projectId) && entity.type === 'solus:workspace')
      .map((entity) => entity.id)
  )
  const registrations = new Set(
    entities.filter((entity) => isWidgetRegistration(entity, projectId)).map((entity) => entity.id)
  )
  const retained = relations.filter(
    (edge) =>
      !(
        edge.type === 'contains' &&
        containers.has(edge.from_entity_id) &&
        registrations.has(edge.to_entity_id)
      )
  )
  const referenced = new Set(retained.flatMap((edge) => [edge.from_entity_id, edge.to_entity_id]))
  return {
    entities: entities.filter((entity) => !containers.has(entity.id) || referenced.has(entity.id)),
    relations: retained
  }
}
