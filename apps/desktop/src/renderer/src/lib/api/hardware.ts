// Typed client over docs/api/hardware.md: what the renderer still reads and writes itself — a
// robot's hardware config, link suggestions, the plugged-in device rows, the Hardware page's
// parts list and its two writes (in graph, clearing "Not now"). Onboarding is SOL's (its tools
// call the propose / confirm / attach / library services); those routes have no caller here.
// Bodies are the generated OpenAPI shapes — aliased, never retyped.
import { api, type ApiClient } from './client'
import type { Entity } from './resources'
import type { components } from './schema'

export type HardwareConfig = components['schemas']['HardwareConfig']
export type EntityHardwareConfig = components['schemas']['EntityHardwareConfig']
export type TransportBinding = components['schemas']['TransportBinding']
export type BusMapEntry = components['schemas']['BusMapEntry']
/** The library's seven part categories, as the topology still labels a legacy category edge.
 *  No request body takes one (SOLUSDEV-326: a robot contains its parts directly). */
export const ROBOT_CATEGORY_LABELS = {
  sensors: 'Sensors',
  actuators: 'Actuators / motors',
  controllers: 'Controllers',
  end_effectors: 'End effectors',
  power: 'Power',
  structure: 'Structure',
  wiring: 'Wiring'
} as const
export type RobotCategory = keyof typeof ROBOT_CATEGORY_LABELS

export interface HardwareConfigOut {
  entry_id: string
  robot_entity_id: string
  config: HardwareConfig
}

export interface EntityHardwareConfigOut {
  entry_id: string | null
  entity_id: string
  version: number
  config: EntityHardwareConfig | null
}

export function getEntityHardwareConfig(
  projectId: string,
  entityId: string,
  client: ApiClient = api
): Promise<EntityHardwareConfigOut> {
  return client.request(`/projects/${projectId}/hardware/entities/${entityId}/config`)
}

export function putEntityHardwareConfig(
  projectId: string,
  entityId: string,
  config: EntityHardwareConfig,
  version: number,
  client: ApiClient = api
): Promise<EntityHardwareConfigOut> {
  return client.request(`/projects/${projectId}/hardware/entities/${entityId}/config`, {
    method: 'PUT',
    body: { config },
    ifMatch: version
  })
}

export type HardwareSuggestionStatus = 'pending' | 'accepted' | 'rejected' | 'superseded'

/** One link-suggestion row (hardware.md §3). `evidence` is the engine's
 *  ModalityMatch list, rendered verbatim — never rephrased. */
export interface HardwareSuggestion {
  id: string
  subject_ref: string
  subject_kind: 'device' | 'part'
  candidate_robot_id: string
  confidence: number
  tier: 'high' | 'medium' | 'low'
  evidence: unknown[]
  reason: string | null
  status: HardwareSuggestionStatus
  created_at: string
  decided_at: string | null
}

/** The device rows (hardware.md §4). `GET /detected` returns an untyped envelope in the
 *  generated schema, so these mirror the backend's `detect.py` wire models by hand. */
export type DetectedLevel = 'transport' | 'board' | 'protocol' | 'platform'

/** The fingerprint contract's `Modality` values (CTR-08 hardware kinds included). */
export type ModalityName =
  | 'part_number'
  | 'datasheet'
  | 'schematic_symbol'
  | 'cad_model'
  | 'photo'
  | 'bus_enumeration'
  | 'firmware_symbol'
  | 'telemetry_channel'

/** One fingerprint-contract observation; `evidence` is free-form and shown verbatim. */
export interface ModalityMatch {
  modality: ModalityName
  source_ref: {
    graph_entity_id?: string | null
    source_connector?: string | null
    external_ref?: string | null
  }
  confidence: number
  state: 'matched' | 'low_confidence'
  evidence: Record<string, unknown>
}

/** How the backend told this device apart from its neighbours. */
export type IdentityBasis = 'serial' | 'port_position' | 'none'

export interface DetectedDeviceOut {
  transport: string
  /** Stable `transport:binding` identity, or null when the device has none. */
  device_ref: string | null
  identity: TransportBinding | null
  level: DetectedLevel
  board: string | null
  board_class: string | null
  mcu_known: boolean
  confidence: number
  evidence: ModalityMatch[]
  /** Two+ devices share the binding — the Detected dialog picks the port explicitly. */
  ambiguous: boolean
  last_seen_path: string | null
  vid?: number | null
  pid?: number | null
  /** The backend's own one-line title (SOLUSDEV-250 P2); older servers omit it. */
  headline?: string
  identity_basis?: IdentityBasis
  /** SOLUSDEV-326 (docs/api/hardware.md "Device memory and Not now"): four annotations the API
   *  fills for its reader. Older servers omit them. The robot or part that binds the device. */
  bound_to?: string | null
  /** Whether THIS reader said "Not now" to it. */
  dismissed?: boolean
  /** When this machine last saw it — its owner only. */
  last_seen?: string | null
  /** The plug-in inspection of it — the machine's owner only; null when none was owed. */
  state?: DeviceInspectionState | null
}

export type DeviceInspectionState = 'inspecting' | 'inspected' | 'busy' | 'unknown'

function robotPath(projectId: string, robotId: string): string {
  return `/projects/${projectId}/hardware/robots/${robotId}`
}

export function getHardwareConfig(
  projectId: string,
  robotId: string,
  client: ApiClient = api
): Promise<HardwareConfigOut> {
  return client.request<HardwareConfigOut>(`${robotPath(projectId, robotId)}/config`)
}

export function listHardwareSuggestions(
  projectId: string,
  status: HardwareSuggestionStatus = 'pending',
  client: ApiClient = api
): Promise<HardwareSuggestion[]> {
  const query = new URLSearchParams({ status })
  return client.request<HardwareSuggestion[]>(
    `/projects/${projectId}/hardware/suggestions?${query}`
  )
}

export function acceptHardwareSuggestion(
  projectId: string,
  suggestionId: string,
  client: ApiClient = api
): Promise<HardwareSuggestion> {
  return client.request<HardwareSuggestion>(
    `/projects/${projectId}/hardware/suggestions/${suggestionId}/accept`,
    { method: 'POST' }
  )
}

export function rejectHardwareSuggestion(
  projectId: string,
  suggestionId: string,
  reason?: string,
  client: ApiClient = api
): Promise<HardwareSuggestion> {
  return client.request<HardwareSuggestion>(
    `/projects/${projectId}/hardware/suggestions/${suggestionId}/reject`,
    { method: 'POST', body: { reason: reason ?? null } }
  )
}

export function listDetectedDevices(
  projectId: string,
  client: ApiClient = api
): Promise<DetectedDeviceOut[]> {
  return client.request<DetectedDeviceOut[]>(`/projects/${projectId}/hardware/detected`)
}

/** A part-like entity the caller may see and the robot that holds it (`GET /parts`). */
export interface HardwarePartRow extends Entity {
  parent_id: string | null
}

const PARTS_PAGE_CAP = 10

/** Every part-like entity the caller may see, each with its robot (docs/api/hardware.md §1). */
// ponytail: walks at most 10 pages of 100; a project past 1000 part-like entities needs a
// hardware-only filter on the route.
export async function listHardwareParts(
  projectId: string,
  client: ApiClient = api
): Promise<HardwarePartRow[]> {
  const all: HardwarePartRow[] = []
  let cursor: string | null = null
  for (let page = 0; page < PARTS_PAGE_CAP; page += 1) {
    const query = new URLSearchParams({ ownership: 'all', limit: '100' })
    if (cursor) query.set('cursor', cursor)
    const { data, meta } = await client.requestPage<HardwarePartRow[]>(
      `/projects/${projectId}/hardware/parts?${query}`
    )
    all.push(...data)
    cursor = meta.has_next ? (meta.next_cursor ?? null) : null
    if (!cursor) break
  }
  return all
}

export type ExpectedParts = components['schemas']['ExpectedParts']

/** What the workspace describes and nothing has answered yet (docs/api/hardware.md §4). */
export function listExpectedParts(
  projectId: string,
  client: ApiClient = api
): Promise<ExpectedParts> {
  return client.request<ExpectedParts>(`/projects/${projectId}/hardware/expected`)
}

/** "+ Add hardware": forget the caller's "Not now" list, so those devices are offered again. */
export function clearDeviceDismissals(
  projectId: string,
  client: ApiClient = api
): Promise<unknown> {
  return client.request(`/projects/${projectId}/hardware/devices/dismissals`, { method: 'DELETE' })
}

/** The person's own "Add robot" / "Add": hardware joins the workspace graph (§1a). */
export function setInGraph(
  projectId: string,
  entityId: string,
  inGraph: boolean,
  client: ApiClient = api
): Promise<{ entity: Entity; in_graph: boolean; updated: number }> {
  return client.request(`/projects/${projectId}/hardware/entities/${entityId}/graph`, {
    method: 'PUT',
    body: { in_graph: inGraph }
  })
}
