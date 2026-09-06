import { api, type ApiClient, type Page } from './client'
import type { Entity } from './resources'

export interface RobotRemoval {
  deleted_entity_id: string
  retained_part_ids: string[]
}

export function createPhysicalRobot(projectId: string, client: ApiClient = api): Promise<Entity> {
  return client.request<Entity>(`/projects/${projectId}/entities`, {
    method: 'POST',
    body: { type: 'physical_robot' }
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

/** Persistent, bounded discovery; a retained service parent does not hide a part. */
export function listRobotOrphans(
  projectId: string,
  cursor: string | null = null,
  client: ApiClient = api
): Promise<Page<Entity[]>> {
  const query = new URLSearchParams({ orphaned_from_robot: 'true', limit: '24' })
  if (cursor) query.set('cursor', cursor)
  return client.requestPage<Entity[]>(`/projects/${projectId}/entities?${query}`)
}
