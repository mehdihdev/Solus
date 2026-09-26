import { api } from './client'

export interface IsaacConnectionStatus {
  bridge: 'connected' | 'unavailable'
  installation: 'installed' | 'unknown'
  owned_session: 'running' | 'not_running' | 'unknown'
  streaming: 'none'
  reason:
    | 'bridge_unavailable'
    | 'capability_unavailable'
    | 'observation_failed'
    | 'runtime_unverified'
    | null
}

function member(value: unknown, choices: readonly unknown[]): boolean {
  return choices.includes(value)
}

function isStatus(value: unknown): value is IsaacConnectionStatus {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const row = value as Record<string, unknown>
  return (
    Object.keys(row).sort().join(',') === 'bridge,installation,owned_session,reason,streaming' &&
    member(row.bridge, ['connected', 'unavailable']) &&
    member(row.installation, ['installed', 'unknown']) &&
    member(row.owned_session, ['running', 'not_running', 'unknown']) &&
    row.streaming === 'none' &&
    member(row.reason, [
      null,
      'bridge_unavailable',
      'capability_unavailable',
      'observation_failed',
      'runtime_unverified'
    ])
  )
}

export async function getIsaacConnectionStatus(
  projectId: string,
  signal?: AbortSignal
): Promise<IsaacConnectionStatus> {
  const value = await api.request<unknown>(
    `/projects/${encodeURIComponent(projectId)}/isaac/connection-status`,
    { signal }
  )
  if (!isStatus(value)) throw new Error('Application status could not be verified.')
  return value
}
