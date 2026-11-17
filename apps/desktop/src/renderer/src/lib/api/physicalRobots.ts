import { api, type ApiClient } from './client'
import type { Entity } from './resources'

export interface RobotRemoval {
  deleted_entity_id: string
  retained_part_ids: string[]
}

/** A name is enough for a robot to exist (ADR-012); none → the server's default.
 *  `name` trails `client` so existing positional callers keep working. */
export function createPhysicalRobot(
  projectId: string,
  client: ApiClient = api,
  name?: string
): Promise<Entity> {
  return client.request<Entity>(`/projects/${projectId}/entities`, {
    method: 'POST',
    body: name ? { type: 'physical_robot', name } : { type: 'physical_robot' }
  })
}

function versionOf(entity: Entity): number {
  const version = entity.version
  if (version === undefined || !Number.isSafeInteger(version) || version < 0)
    throw new Error('Reload the robot to get its current version.')
  return version
}

export async function renamePhysicalRobot(
  projectId: string,
  entity: Entity,
  name: string,
  client: ApiClient = api
): Promise<Entity> {
  return client.request<Entity>(`/projects/${projectId}/entities/${entity.id}`, {
    method: 'PATCH',
    body: { name },
    ifMatch: versionOf(entity)
  })
}

export async function deletePhysicalRobot(
  projectId: string,
  entity: Entity,
  client: ApiClient = api
): Promise<RobotRemoval> {
  return client.request<RobotRemoval>(`/projects/${projectId}/entities/${entity.id}`, {
    method: 'DELETE',
    ifMatch: versionOf(entity)
  })
}
