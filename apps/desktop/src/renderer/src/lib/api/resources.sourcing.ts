// SOLUSDEV-246 (STORE ST5) — the sourcing engine's typed client
// (docs/api/sourcing.md). One engine for two doors: Workspace › Add › Hardware
// › Sourced and BOM › Find compatible parts both call exactly these.
import { api, type ApiClient } from './client'
import type { Entity } from './resources'

export type SourcingDoor = 'workspace' | 'bom'
export type RequestStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type Grounding = 'cited' | 'unverified'

export interface ExcludedSupplierApi {
  name: string
  reason: string
}

export interface SourcingRulesApi {
  excluded_suppliers: ExcludedSupplierApi[]
  required_certifications: string[]
  max_voltage_v: number | null
  allowed_protocols: string[]
  preferred_suppliers: string[]
}

export interface RequirementSpecApi {
  text?: string
  protocol?: string | null
  voltage_v?: number | null
  load_kg?: number | null
  arm_m?: number | null
  part_class?: string
}

export interface TorqueLoadApi {
  name: string
  mass_kg: number
  lever_arm_m: number
}

export interface TorqueApi {
  static_torque_nm: number
  required_torque_nm: number
  safety_factor: number
  loads: TorqueLoadApi[]
  unknown: string[]
  assumptions: string[]
  /** Present when derived from an assembly. */
  assembly?: string
  assembly_entity_id?: string
  parts?: {
    entity_id: string
    name: string
    mass_kg: number | null
    position_mm: number[] | null
  }[]
}

export interface TorqueInput {
  assembly_entity_id?: string
  pivot_mm?: [number, number, number]
  masses?: Record<string, number>
  load_kg?: number
  arm_m?: number
  safety_factor?: number
}

export interface CandidateApi {
  id: string
  name: string
  manufacturer: string | null
  part_number: string | null
  supplier: string | null
  torque_nm: number | null
  cost: number | null
  currency: string | null
  weight_kg: number | null
  protocol: string | null
  voltage_v: number | null
  availability: string | null
  certifications: string[]
  source_url: string | null
  vendor_cad_url: string | null
  optimizes_for: string
  gives_up: string
  notes: string | null
  grounding: Grounding
  flags: string[]
}

export interface ExcludedCandidateApi {
  candidate: CandidateApi
  reasons: string[]
}

export interface SourcingRequestApi {
  id: string
  project_id: string
  status: RequestStatus
  door: SourcingDoor
  spec: RequirementSpecApi & { assembly_name?: string }
  torque: TorqueApi | null
  assembly_entity_id: string | null
  candidates: CandidateApi[]
  excluded: ExcludedCandidateApi[]
  rules: Partial<SourcingRulesApi>
  model: string | null
  error: { code: string; message: string } | null
  job_id: string | null
  selected_candidate_id: string | null
  selected_entity_id: string | null
  created_at: string
  finished_at: string | null
}

export interface SourcingRequestInput extends TorqueInput {
  spec: RequirementSpecApi
  door: SourcingDoor
  /** The user's `~/.solus/preferences.json` sections — ranking context only. */
  preferences?: Record<string, string>
}

export interface SelectInput {
  candidate_id: string
  category_entity_id?: string
  quantity?: number
}

const seg = encodeURIComponent
const base = (projectId: string): string => `/projects/${seg(projectId)}/sourcing`

export function getSourcingRules(
  projectId: string,
  client: ApiClient = api
): Promise<SourcingRulesApi> {
  return client.request<SourcingRulesApi>(`${base(projectId)}/rules`)
}

export function putSourcingRules(
  projectId: string,
  rules: SourcingRulesApi,
  client: ApiClient = api
): Promise<SourcingRulesApi> {
  return client.request<SourcingRulesApi>(`${base(projectId)}/rules`, {
    method: 'PUT',
    body: rules
  })
}

export function deriveTorque(
  projectId: string,
  input: TorqueInput,
  client: ApiClient = api
): Promise<TorqueApi> {
  return client.request<TorqueApi>(`${base(projectId)}/torque`, { method: 'POST', body: input })
}

export function createSourcingRequest(
  projectId: string,
  input: SourcingRequestInput,
  client: ApiClient = api
): Promise<{ request: SourcingRequestApi; job_id: string }> {
  return client.request<{ request: SourcingRequestApi; job_id: string }>(
    `${base(projectId)}/requests`,
    { method: 'POST', body: input }
  )
}

export function listSourcingRequests(
  projectId: string,
  client: ApiClient = api
): Promise<SourcingRequestApi[]> {
  return client.request<SourcingRequestApi[]>(`${base(projectId)}/requests`)
}

export function getSourcingRequest(
  projectId: string,
  requestId: string,
  client: ApiClient = api
): Promise<SourcingRequestApi> {
  return client.request<SourcingRequestApi>(`${base(projectId)}/requests/${seg(requestId)}`)
}

export function selectSourcingCandidate(
  projectId: string,
  requestId: string,
  input: SelectInput,
  client: ApiClient = api
): Promise<{ entity: Entity; request: SourcingRequestApi }> {
  return client.request<{ entity: Entity; request: SourcingRequestApi }>(
    `${base(projectId)}/requests/${seg(requestId)}/select`,
    { method: 'POST', body: input }
  )
}
