import { api } from '../../../lib/api/client'
import { verifiedModel } from './sceneApi'
import type { SceneModel } from './types'
export interface CadSource {
  id: string
  name: string
  observed_microversion: string | null
}
export interface CadBinding {
  mesh_key: string
  source_entity_id: string
}
const path = (project: string): string => `/projects/${encodeURIComponent(project)}/bench/scene`
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= 256
export async function cadSources(
  project: string,
  signal?: AbortSignal,
  includeAssemblies = false
): Promise<CadSource[]> {
  const result = await api.request<unknown>(
    `${path(project)}/cad-sources${includeAssemblies ? '?include_assemblies=true' : ''}`,
    { signal }
  )
  if (!object(result) || !Array.isArray(result.sources) || result.sources.length > 256)
    throw new Error('Invalid CAD sources')
  return result.sources.map((value: unknown) => {
    if (
      !object(value) ||
      !text(value.id) ||
      !text(value.name) ||
      (value.observed_microversion !== null && !text(value.observed_microversion))
    )
      throw new Error('Invalid CAD source')
    return {
      id: value.id,
      name: value.name,
      observed_microversion: value.observed_microversion as string | null
    }
  })
}

export interface CadImportStatus {
  import_id: string
  status: 'pending' | 'complete' | 'error'
  reason: string | null
  job_id: string | null
  model_id: string | null
}
function verifiedImport(value: unknown): CadImportStatus {
  if (
    !object(value) ||
    !text(value.import_id) ||
    typeof value.status !== 'string' ||
    !['pending', 'complete', 'error'].includes(value.status) ||
    ![value.reason, value.job_id, value.model_id].every((field) => field === null || text(field)) ||
    (value.status === 'complete' && !text(value.model_id))
  )
    throw new Error('Invalid CAD import response')
  return value as unknown as CadImportStatus
}
export async function startCadImport(
  project: string,
  input: {
    robot_id: string
    source_entity_id: string
    expected_revision: string
  },
  signal?: AbortSignal
): Promise<CadImportStatus> {
  if (![input.robot_id, input.source_entity_id, input.expected_revision].every(text))
    throw new Error('Select a robot and a synced CAD revision')
  return verifiedImport(
    await api.request<unknown>(`${path(project)}/cad-imports`, {
      method: 'POST',
      body: {
        robot_id: input.robot_id,
        source_entity_id: input.source_entity_id,
        expected_revision: input.expected_revision
      },
      signal
    })
  )
}
export async function cadImportStatus(
  project: string,
  id: string,
  signal?: AbortSignal
): Promise<CadImportStatus> {
  const result = verifiedImport(
    await api.request<unknown>(`${path(project)}/cad-imports/${encodeURIComponent(id)}`, { signal })
  )
  if (result.import_id !== id) throw new Error('Invalid CAD import identity')
  return result
}
export async function bindCad(
  project: string,
  model: string,
  version: number,
  bindings: CadBinding[]
): Promise<{
  model: SceneModel
  refresh_status: NonNullable<SceneModel['refresh_status']>
  job_id: string | null
}> {
  const result = await api.request<unknown>(
    `${path(project)}/models/${encodeURIComponent(model)}/cad-bindings`,
    { method: 'PUT', body: { expected_version: version, bindings } }
  )
  if (
    !object(result) ||
    typeof result.refresh_status !== 'string' ||
    !['queued', 'current', 'stale', 'error'].includes(result.refresh_status) ||
    (result.job_id !== null && !text(result.job_id))
  )
    throw new Error('Invalid CAD refresh response')
  return {
    model: verifiedModel(result.model),
    refresh_status: result.refresh_status as NonNullable<SceneModel['refresh_status']>,
    job_id: result.job_id as string | null
  }
}
