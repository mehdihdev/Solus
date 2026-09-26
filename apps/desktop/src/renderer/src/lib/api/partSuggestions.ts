import { api } from './client'
export interface PartLink {
  id: string
  robotId: string
  confidence: number
  reason: string | null
}
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const text = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= 256
const confidence = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
const reason = (value: unknown): value is string | null =>
  value === null || (typeof value === 'string' && value.length <= 4000)
export async function proposePartLinks(projectId: string, partId: string): Promise<PartLink[]> {
  const value = await api.request<unknown>(
    `/projects/${encodeURIComponent(projectId)}/hardware/parts/${encodeURIComponent(partId)}/suggestions`,
    { method: 'POST' }
  )
  if (!Array.isArray(value) || value.length > 100) throw new Error('Invalid suggestions')
  return value.map((row: unknown) => {
    if (
      !record(row) ||
      !text(row.id) ||
      !text(row.candidate_robot_id) ||
      row.subject_kind !== 'part' ||
      row.subject_ref !== partId ||
      row.status !== 'pending' ||
      !confidence(row.confidence) ||
      !reason(row.reason)
    )
      throw new Error('Invalid suggestion')
    return {
      id: row.id,
      robotId: row.candidate_robot_id,
      confidence: row.confidence,
      reason: row.reason
    }
  })
}
export async function decidePartLink(
  projectId: string,
  id: string,
  accept: boolean
): Promise<void> {
  const value = await api.request<unknown>(
    `/projects/${encodeURIComponent(projectId)}/hardware/suggestions/${encodeURIComponent(id)}/${accept ? 'accept' : 'reject'}`,
    { method: 'POST' }
  )
  if (
    !record(value) ||
    value.id !== id ||
    value.status !== (accept ? 'accepted' : 'rejected') ||
    (accept && value.bound !== true)
  )
    throw new Error('Unverified decision')
}
