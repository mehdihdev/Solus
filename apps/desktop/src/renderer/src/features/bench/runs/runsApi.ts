import {
  decodeRunSummary,
  decodeRunDetail,
  decodeRunFindings,
  decodeRunComparison,
  decodeRunList,
  decodeRunNarration
} from './runDecoders'
import { api } from '../../../lib/api/client'
export interface RunSummary {
  id: string
  robot_id: string
  session_id: string | null
  name: string
  origin: 'live' | 'recorded' | 'synthetic'
  status: 'running' | 'completed' | 'truncated' | 'interrupted'
  started_at: string
  ended_at: string | null
  packet_count: number
  drop_count: number
  artifact_id: string | null
}
export interface RunPacket {
  device_id: string
  timestamp: string
  values: Record<string, number>
  units: Record<string, string>
  seq?: number | null
  schema_version?: number
}
export interface SensorReference {
  artifact_id: string
  timestamp: string
  kind: 'camera' | 'lidar'
  device_id: string
}
export interface RunManifest {
  schema_version: 1
  robot_id: string
  started_at: string
  packets: RunPacket[]
  sensors: SensorReference[]
  parts: Array<{
    entity_id: string
    name: string
    device_id: string
    code_site?: string | null
    cad_revision?: string | null
  }>
  snapshots: Array<{
    entity_id: string
    kind: string
    name: string
    source_id?: string | null
    revision?: string | null
    data?: string | null
  }>
}
export interface RunDetail {
  summary: RunSummary
  manifest: RunManifest
}
export interface RunFindings {
  evidence_origin?: 'live' | 'recorded' | 'synthetic'
  findings: Array<{
    entity_id: string
    headline: string
    explanation: string
    detail: string
    code_site: string | null
    cad_revision: string | null
    evidence: Record<string, number | string | null>
  }>
  insufficient: Array<{ entity_id: string | null; reason: string }>
}
export interface RunComparison {
  config_changes: Array<{
    entity_id: string
    field: string
    before: string | number | null
    after: string | number | null
  }>
  source_snapshots_changed: boolean
  divergences: Array<{
    device_id: string
    signal: string
    aligned_samples: number
    max_difference: number
    unit: string | null
  }>
  clamp_attributions: Array<{
    entity_id: string
    explanation: string
    before_limit: number
    after_limit: number
  }>
  insufficient: Array<{ device_id: string; signal: string; reason: string }>
}
const path = (project: string): string => `/projects/${encodeURIComponent(project)}/bench/runs`
export async function listRuns(
  project: string,
  cursor?: string,
  signal?: AbortSignal
): Promise<{ runs: RunSummary[]; next_cursor: string | null }> {
  const query = new URLSearchParams({ limit: '50', ...(cursor ? { cursor } : {}) })
  return decodeRunList(await api.request<unknown>(`${path(project)}?${query}`, { signal }))
}
export async function startRun(
  project: string,
  body: { robot_id: string; session_id: string; name: string }
): Promise<RunSummary> {
  return decodeRunSummary(await api.request<unknown>(path(project), { method: 'POST', body }))
}
export async function stopRun(project: string, id: string): Promise<RunSummary> {
  return decodeRunSummary(
    await api.request<unknown>(`${path(project)}/${encodeURIComponent(id)}/stop`, {
      method: 'POST'
    })
  )
}
export async function importRun(
  project: string,
  body: { robot_id: string; artifact_id: string; name: string; origin: 'recorded' | 'synthetic' }
): Promise<RunSummary> {
  return decodeRunSummary(
    await api.request<unknown>(`${path(project)}/import`, { method: 'POST', body })
  )
}
export async function getRun(
  project: string,
  id: string,
  signal?: AbortSignal
): Promise<RunDetail> {
  return decodeRunDetail(
    await api.request<unknown>(`${path(project)}/${encodeURIComponent(id)}`, { signal })
  )
}
export async function runFindings(
  project: string,
  id: string,
  signal?: AbortSignal
): Promise<RunFindings> {
  return decodeRunFindings(
    await api.request<unknown>(`${path(project)}/${encodeURIComponent(id)}/findings`, { signal })
  )
}
export async function compareRuns(
  project: string,
  baseline: string,
  candidate: string
): Promise<RunComparison> {
  return decodeRunComparison(
    await api.request<unknown>(`${path(project)}/compare`, {
      method: 'POST',
      body: { baseline_id: baseline, candidate_id: candidate }
    })
  )
}

export interface RunNarration extends RunFindings {
  mode: 'model' | 'deterministic'
  reason: string
  narration: string[]
}
export async function narrateRun(
  project: string,
  id: string,
  signal?: AbortSignal
): Promise<RunNarration> {
  return decodeRunNarration(
    await api.request<unknown>(`${path(project)}/${encodeURIComponent(id)}/narrate`, {
      method: 'POST',
      signal
    })
  )
}
