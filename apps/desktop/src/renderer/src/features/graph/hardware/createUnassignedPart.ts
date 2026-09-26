import { api } from '../../../lib/api/client'
import type { RobotCategory } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'

/** The existing per-entity creation route; an absent parent never creates a robot. */
export async function createUnassignedPart(
  projectId: string,
  name: string,
  category: RobotCategory,
  operationId: string
): Promise<Entity> {
  const result = await api.request<{ entity: Entity }>(
    `/projects/${encodeURIComponent(projectId)}/hardware/entities`,
    {
      method: 'POST',
      idempotencyKey: operationId,
      body: { kind: 'part', name, category }
    }
  )
  return result.entity
}
