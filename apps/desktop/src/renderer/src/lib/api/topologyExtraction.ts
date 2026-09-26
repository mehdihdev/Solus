import { api } from './client'
import type { components } from './schema'

export type ExtractionProposal = components['schemas']['ExtractionProposal']
export type ExtractionRequest = components['schemas']['ExtractionRequest']

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function text(value: unknown, limit = 512): boolean {
  return typeof value === 'string' && value.length > 0 && value.length <= limit
}
function optionalText(value: unknown, limit = 512): boolean {
  return value == null || text(value, limit)
}
function validRow(value: unknown): boolean {
  if (!record(value) || !text(value.source_namespace, 128) || !text(value.source_ref)) return false
  if (
    !['bus', 'device', 'protocol', 'address', 'part_candidate'].every((key) =>
      optionalText(value[key])
    )
  )
    return false
  if (!validConfidence(value.confidence)) return false
  return (
    Array.isArray(value.provenance) &&
    value.provenance.length <= 32 &&
    value.provenance.every(
      (item: unknown) =>
        record(item) &&
        text(item.source_ref) &&
        optionalText(item.entity_ref) &&
        optionalText(item.pin_ref) &&
        optionalText(item.detail, 2048)
    )
  )
}

export async function proposeExtraction(
  projectId: string,
  robotId: string,
  input: ExtractionRequest
): Promise<ExtractionProposal> {
  const result = await api.request<ExtractionProposal>(
    `/projects/${encodeURIComponent(projectId)}/hardware/robots/${encodeURIComponent(robotId)}/topology/extraction/propose`,
    { method: 'POST', body: input }
  )
  if (
    !result ||
    result.robot_id !== robotId ||
    result.brain_id !== input.brain_id ||
    result.source_ref !== input.source_ref ||
    typeof result.proposal_digest !== 'string' ||
    !/^[0-9a-f]{64}$/.test(result.proposal_digest) ||
    !validExtraction(result.extraction, input.source_kind)
  ) {
    throw new Error('The evidence response could not be verified. Review the file again.')
  }
  return result
}

export interface ExtractionConfirmation extends ExtractionRequest {
  proposal_digest: string
  operation_id: string
  selections: { row_index: number; name: string; entity_id?: string }[]
}
export interface ExtractionAcceptance {
  robot_id: string
  brain_id: string
  proposal_digest: string
  entity_ids: string[]
  created: number
}
export async function confirmExtraction(
  projectId: string,
  robotId: string,
  input: ExtractionConfirmation
): Promise<ExtractionAcceptance> {
  const result = await api.request<unknown>(
    `/projects/${encodeURIComponent(projectId)}/hardware/robots/${encodeURIComponent(robotId)}/topology/extraction/confirm`,
    { method: 'POST', body: input }
  )
  if (
    !record(result) ||
    result.robot_id !== robotId ||
    result.brain_id !== input.brain_id ||
    result.proposal_digest !== input.proposal_digest ||
    !validAcceptanceCounts(result, input.selections.length)
  ) {
    throw new Error('The evidence acceptance could not be verified.')
  }
  return result as unknown as ExtractionAcceptance
}

function validConfidence(value: unknown): boolean {
  return (
    value == null ||
    (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)
  )
}

function validExtraction(
  value: ExtractionProposal['extraction'],
  kind: ExtractionRequest['source_kind']
): boolean {
  return !(
    !value ||
    value.source_kind !== kind ||
    value.status !== 'success' ||
    !Array.isArray(value.rows) ||
    value.rows.length > 256 ||
    !value.rows.every(validRow) ||
    !Array.isArray(value.notes) ||
    value.notes.length > 32 ||
    !value.notes.every((note: unknown) => text(note, 2048))
  )
}

function validAcceptanceCounts(result: Record<string, unknown>, count: number): boolean {
  return !(
    !Array.isArray(result.entity_ids) ||
    result.entity_ids.length !== count ||
    result.entity_ids.length > 256 ||
    !result.entity_ids.every(
      (id: unknown) =>
        typeof id === 'string' &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
    ) ||
    typeof result.created !== 'number' ||
    !Number.isInteger(result.created) ||
    result.created < 0 ||
    result.created > result.entity_ids.length
  )
}
