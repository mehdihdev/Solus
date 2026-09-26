import { api } from './client'
export type PresenceProfileId = 'uno_avr' | 'nano_avr'
export interface PresenceProfile {
  id: PresenceProfileId
  label: string
  available: boolean
  reason: string | null
}
export interface PresenceInput {
  profile_id: PresenceProfileId
  kind: 'heartbeat' | 'probe' | 'topology'
  wiring_proposal_id?: string
  channel: string
}
export interface PresencePlan {
  plan_id: string
  source: string
  source_sha256: string
  binary_sha256: string
  profile: PresenceProfileId
  status: 'prepared'
  target: {
    binding: string
    path: string
    vid: number
    pid: number
    serial: string | null
    location: string | null
    manual_confirmation_required: true
  }
}
function record(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function text(v: unknown, max = 512): v is string {
  return typeof v === 'string' && v.length > 0 && v.length <= max
}
function nullable(v: unknown): boolean {
  return v === null || text(v)
}
function profile(v: unknown): v is PresenceProfileId {
  return v === 'uno_avr' || v === 'nano_avr'
}
function usb(v: unknown): boolean {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 65535
}
const base = (id: string): string => `/projects/${encodeURIComponent(id)}/hardware`
export async function listPresenceProfiles(projectId: string): Promise<PresenceProfile[]> {
  const value = await api.request<unknown>(`${base(projectId)}/presence/profiles`)
  if (
    !Array.isArray(value) ||
    value.length > 2 ||
    !value.every(
      (v: unknown) =>
        record(v) &&
        profile(v.id) &&
        text(v.label, 120) &&
        typeof v.available === 'boolean' &&
        nullable(v.reason)
    ) ||
    new Set(value.map((v) => (v as PresenceProfile).id)).size !== value.length
  )
    throw new Error('Firmware profiles could not be verified.')
  return value as PresenceProfile[]
}
export async function preparePresence(
  projectId: string,
  robotId: string,
  brainId: string,
  input: PresenceInput
): Promise<PresencePlan> {
  if (input.kind === 'topology' && !input.wiring_proposal_id)
    throw new Error('Accept wiring before preparing topology firmware.')
  const v = await api.request<unknown>(
    `${base(projectId)}/robots/${encodeURIComponent(robotId)}/brains/${encodeURIComponent(brainId)}/presence/prepare`,
    { method: 'POST', body: input }
  )
  if (!validPlan(v, input))
    throw new Error('Prepared firmware could not be verified. Prepare again.')
  return v as unknown as PresencePlan
}

function validTarget(v: unknown): boolean {
  if (!record(v)) return false
  return [
    text(v.binding),
    text(v.path),
    usb(v.vid),
    usb(v.pid),
    nullable(v.serial),
    nullable(v.location),
    v.manual_confirmation_required === true
  ].every(Boolean)
}
function validPlan(v: unknown, input: PresenceInput): boolean {
  if (!record(v)) return false
  const uuid =
    typeof v.plan_id === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v.plan_id)
  const sha = (value: unknown): boolean => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
  return [
    uuid,
    text(v.source, 100000),
    sha(v.source_sha256),
    sha(v.binary_sha256),
    v.profile === input.profile_id,
    v.status === 'prepared',
    validTarget(v.target)
  ].every(Boolean)
}
