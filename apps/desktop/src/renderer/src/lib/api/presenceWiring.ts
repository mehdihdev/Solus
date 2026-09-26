import { api } from './client'
import type { PresenceProfileId } from './presence'
export interface WiringRow {
  channel: string
  pin: string
  kind: 'analog_input' | 'digital_input'
}
export interface WiringInput {
  profile_id: PresenceProfileId
  mode: 'typed' | 'schematic' | 'probe'
  wiring: readonly WiringRow[]
  source_id?: string
  run_id?: string
}
export interface WiringProposal {
  proposal_id: string
  digest: string
  profile_id: PresenceProfileId
  mode: WiringInput['mode']
  wiring: WiringRow[]
  observations: { detail: string; confidence: number | null }[]
  unresolved: string[]
  status: 'proposed'
}
export interface WiringAcceptance {
  proposal_id: string
  digest: string
  status: 'accepted'
}
const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const text = (v: unknown, max: number): v is string =>
  typeof v === 'string' && v.length > 0 && v.length <= max
const uuid = (v: unknown): v is string =>
  typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v)
const digest = (v: unknown): boolean => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v)
const base = (p: string, r: string, b: string): string =>
  `/projects/${encodeURIComponent(p)}/hardware/robots/${encodeURIComponent(r)}/brains/${encodeURIComponent(b)}/presence/wiring`
function validRow(v: unknown): boolean {
  return (
    record(v) &&
    text(v.channel, 64) &&
    text(v.pin, 16) &&
    (v.kind === 'analog_input' || v.kind === 'digital_input')
  )
}
function boundedRows(
  value: unknown,
  maximum: number,
  validate: (row: unknown) => boolean
): boolean {
  return Array.isArray(value) && value.length <= maximum && value.every(validate)
}
function validObservation(value: unknown): boolean {
  if (!record(value) || !text(value.detail, 2048)) return false
  const confidence = value.confidence
  return (
    confidence === null ||
    (typeof confidence === 'number' &&
      Number.isFinite(confidence) &&
      confidence >= 0 &&
      confidence <= 1)
  )
}
function validProposal(v: unknown, input: WiringInput): v is WiringProposal {
  if (!record(v)) return false
  return (
    uuid(v.proposal_id) &&
    digest(v.digest) &&
    v.profile_id === input.profile_id &&
    v.mode === input.mode &&
    v.status === 'proposed' &&
    boundedRows(v.wiring, 16, validRow) &&
    boundedRows(v.observations, 256, validObservation) &&
    boundedRows(v.unresolved, 256, (value) => text(value, 2048))
  )
}
export async function proposeWiring(
  p: string,
  r: string,
  b: string,
  input: WiringInput
): Promise<WiringProposal> {
  const value = await api.request<unknown>(`${base(p, r, b)}/propose`, {
    method: 'POST',
    body: input
  })
  if (!validProposal(value, input)) throw new Error('Wiring evidence could not be verified.')
  return value
}
export async function acceptWiring(
  p: string,
  r: string,
  b: string,
  proposal: Pick<WiringProposal, 'proposal_id' | 'digest'>
): Promise<WiringAcceptance> {
  const value = await api.request<unknown>(
    `${base(p, r, b)}/${encodeURIComponent(proposal.proposal_id)}/accept`,
    { method: 'POST', body: { digest: proposal.digest } }
  )
  if (
    !record(value) ||
    value.proposal_id !== proposal.proposal_id ||
    value.digest !== proposal.digest ||
    value.status !== 'accepted'
  )
    throw new Error('Wiring acceptance could not be verified.')
  return value as unknown as WiringAcceptance
}
