import { api, type ApiClient } from './client'

import type { components } from './schema'

export type HardwareTopologyNode = components['schemas']['TopologyNode']
export type HardwareTopology = components['schemas']['RobotTopology']

export async function readHardwareTopology(
  projectId: string,
  robotId: string,
  signal?: AbortSignal,
  client: ApiClient = api
): Promise<HardwareTopology> {
  const result = await client.request<unknown>(
    `/projects/${encodeURIComponent(projectId)}/hardware/robots/${encodeURIComponent(robotId)}/topology`,
    { signal }
  )
  if (!validTopology(result) || result.robot_id !== robotId) {
    throw new Error('Invalid hardware topology response')
  }
  return result
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
const optionalText = (value: unknown): boolean =>
  value === undefined || value === null || typeof value === 'string'
function validNode(value: unknown): boolean {
  return (
    record(value) &&
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    ['brain', 'bus', 'device', 'part'].includes(String(value.role)) &&
    [undefined, null, 'host', 'mcu', 'onboard'].includes(
      value.brain_kind as string | null | undefined
    ) &&
    ['category', 'channel', 'software', 'presence'].every((key) => optionalText(value[key])) &&
    (value.evidence === undefined ||
      (Array.isArray(value.evidence) &&
        value.evidence.every(
          (item: unknown) =>
            record(item) && typeof item.by === 'string' && optionalText(item.source)
        )))
  )
}
export function validTopology(value: unknown): value is HardwareTopology {
  if (
    !record(value) ||
    typeof value.robot_id !== 'string' ||
    !Array.isArray(value.nodes) ||
    !value.nodes.every(validNode) ||
    !Array.isArray(value.roots) ||
    !value.roots.every((id: unknown) => typeof id === 'string') ||
    !Array.isArray(value.edges)
  )
    return false
  const ids = new Set(value.nodes.map((node: HardwareTopologyNode) => node.id))
  return (
    ids.size === value.nodes.length &&
    value.roots.every((id: string) => ids.has(id)) &&
    value.edges.every(
      (edge: unknown) =>
        record(edge) &&
        typeof edge.id === 'string' &&
        typeof edge.source === 'string' &&
        typeof edge.target === 'string' &&
        ids.has(edge.source) &&
        ids.has(edge.target) &&
        optionalText(edge.protocol) &&
        optionalText(edge.address)
    )
  )
}
