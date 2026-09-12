// Typed client over docs/api/hardware.md §2–5 (SOLUSDEV-248 R5/R1/R2/R4): a Physical
// Robot's hardware config, authored parts, lifecycle promotion, link
// suggestions, detection (propose / confirm), attaching sourced parts and the
// curated parts / platform library (search, preview, import).
// Bodies are the generated OpenAPI shapes — aliased, never retyped.
import { api, type ApiClient, type Page } from './client'
import type { Entity } from './resources'
import type { components } from './schema'

export type HardwareConfig = components['schemas']['HardwareConfig']
export type EntityHardwareConfig = components['schemas']['EntityHardwareConfig']
export type PartIn = components['schemas']['PartIn']
export type ConfigIn = components['schemas']['ConfigIn']
export type LifecycleIn = components['schemas']['LifecycleIn']
export type PartConfig = components['schemas']['PartConfig']
export type TransportBinding = components['schemas']['TransportBinding']
export type ProtocolBinding = components['schemas']['ProtocolBinding']
export type BusMapEntry = components['schemas']['BusMapEntry']
export type LifecycleState = components['schemas']['LifecycleState']
export type RobotCategory = PartIn['category']
export type ProposeIn = components['schemas']['ProposeIn']
export type ConfirmIn = components['schemas']['ConfirmIn']
export type ConfirmTarget = ConfirmIn['target']
export type AcceptedRow = components['schemas']['AcceptedRow']

export const ROBOT_CATEGORIES = [
  'sensors',
  'actuators',
  'controllers',
  'end_effectors',
  'power',
  'structure',
  'wiring'
] as const satisfies readonly RobotCategory[]

export const ROBOT_CATEGORY_LABELS: Record<RobotCategory, string> = {
  sensors: 'Sensors',
  actuators: 'Actuators / motors',
  controllers: 'Controllers',
  end_effectors: 'End effectors',
  power: 'Power',
  structure: 'Structure',
  wiring: 'Wiring'
}

export const LIFECYCLE_STATES = [
  'planned',
  'ordered',
  'received',
  'installed',
  'live'
] as const satisfies readonly LifecycleState[]

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

export interface HardwarePartOut {
  entity: Entity
  config_entry_id: string
}

export interface HardwareLifecycleOut {
  part_id: string
  config: PartConfig
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

/** The R2 response shapes (hardware.md §4). The detection routes return
 *  untyped envelopes in the generated schema, so these mirror the backend's
 *  `detect.py` wire models by hand until `pnpm gen:api` carries them. */
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
}

export interface RepoMatchOut {
  config_id: string
  parser_id: string
  label: string
  source: string
  protocol_hint?: string | null
  port_hint?: string | null
  calibration_source?: string | null
  params?: Record<string, unknown>
}

export interface ProposalRowOut {
  id: string
  subject: string
  address: string
  model: string | null
  proposed_function: string | null
  confidence: number | null
  evidence: ModalityMatch[]
  provenance: 'bus' | 'repo'
}

export interface DisambiguationOut {
  question: string
  options: string[]
}

/** Confidence as tone, never a number: the label the heading leads with. */
export type ProposalTone = 'looks_like' | 'probably' | 'something'

/** What a passive listen saw on the wire, when the device streamed anything. */
export interface StreamOut {
  framing: string
  channel_count: number
  update_hz: number
  channel_names: string[] | null
  declared_hz: number | null
}

export interface ProposalOut {
  device_ref: string
  identity?: TransportBinding | null
  level: DetectedLevel
  summary: string
  driver_id: string | null
  params: Record<string, unknown>
  rows: ProposalRowOut[]
  repo_matches: RepoMatchOut[]
  disambiguation: DisambiguationOut | null
  confidence: number
  evidence: ModalityMatch[]
  calibration_source?: string | null
  /** SOLUSDEV-250 P2 wire fields; older servers omit them — default in code. */
  headline?: string
  tone?: ProposalTone
  stream?: StreamOut | null
  identity_basis?: IdentityBasis
  /** Pending link suggestions for this device (a library-imported robot it may BE). */
  suggestions?: HardwareSuggestion[]
}

/** 201 from confirm — the robot exists even when the session did not start. */
export interface ConfirmOut {
  robot: Entity
  part_ids: string[]
  config_entry_id: string | null
  session_id: string | null
  session_error: string | null
}

export interface AttachIn {
  entity_ids: string[]
  category: RobotCategory
}

export interface AttachOut {
  attached: string[]
  skipped: string[]
  config_entry_id: string
}

/** The R4 library shapes (hardware.md §5), mirroring the backend's `library.py`
 *  by hand until `pnpm gen:api` carries them (the routes return untyped envelopes). */
export type LibraryKind = 'part' | 'platform'
export type LibraryScalar = string | number | boolean | null
export type CalibrationMode = components['schemas']['CalibrationMode']
export type TransportKind = components['schemas']['TransportKind']

export interface LibraryHit {
  kind: LibraryKind
  id: string
  name: string
  manufacturer: string | null
  category?: string | null
  machine_class?: string | null
  summary: string
}

interface LibraryDefinitionBase {
  id: string
  name: string
  manufacturer: string | null
  keywords: string[]
  notes: string | null
}

export interface LibraryPartDefinition extends LibraryDefinitionBase {
  kind: 'part'
  category: RobotCategory
  specs: Record<string, LibraryScalar>
  driver_id: string | null
  protocol_version: number | null
  resolution: number | null
  register_map: Record<string, { address: number; size: number }>
  telemetry: { quantity: string; unit: string | null }[]
  calibration_mode: CalibrationMode | null
  datasheet_url: string | null
}

/** One platform slot: which part sits at which address playing which role. */
export interface LibraryPlatformPart {
  part: string
  address: string
  role: string
  category: RobotCategory | null
  gear_ratio: string | null
  calibration_mode: CalibrationMode | null
  calibration: Record<string, number>
}

export interface LibraryPlatformDefinition extends LibraryDefinitionBase {
  kind: 'platform'
  machine_class: string
  transport: TransportKind
  driver_id: string | null
  params: Record<string, LibraryScalar>
  parts: LibraryPlatformPart[]
  urdf: string | null
  mjcf: string | null
}

export type LibraryDefinition = LibraryPartDefinition | LibraryPlatformDefinition

/** 201 from a platform import — the robot, its parts, its LIBRARY config layer and any
 *  pending link suggestions the reconciliation pass raised against detected devices. */
export interface PlatformImportOut {
  robot: Entity
  part_ids: string[]
  config_entry_id: string
  suggestion_ids: string[]
}

export interface PartImportIn {
  robot_id: string
  /** Defaults server-side to the definition's category. */
  category?: RobotCategory | null
}

export interface PartImportOut {
  entity: Entity
  config_entry_id: string
}

function robotPath(projectId: string, robotId: string): string {
  return `/projects/${projectId}/hardware/robots/${robotId}`
}

function detectedPath(projectId: string, deviceRef: string): string {
  return `/projects/${projectId}/hardware/detected/${encodeURIComponent(deviceRef)}`
}

function libraryPath(projectId: string): string {
  return `/projects/${projectId}/hardware/library`
}

export function getHardwareConfig(
  projectId: string,
  robotId: string,
  client: ApiClient = api
): Promise<HardwareConfigOut> {
  return client.request<HardwareConfigOut>(`${robotPath(projectId, robotId)}/config`)
}

export function putHardwareConfig(
  projectId: string,
  robotId: string,
  config: HardwareConfig,
  client: ApiClient = api
): Promise<HardwareConfigOut> {
  const body: ConfigIn = { config }
  return client.request<HardwareConfigOut>(`${robotPath(projectId, robotId)}/config`, {
    method: 'PUT',
    body
  })
}

export function createHardwarePart(
  projectId: string,
  robotId: string,
  input: PartIn,
  client: ApiClient = api
): Promise<HardwarePartOut> {
  return client.request<HardwarePartOut>(`${robotPath(projectId, robotId)}/parts`, {
    method: 'POST',
    body: input
  })
}

export function promotePartLifecycle(
  projectId: string,
  robotId: string,
  partId: string,
  state: LifecycleState,
  client: ApiClient = api
): Promise<HardwareLifecycleOut> {
  const body: LifecycleIn = { state }
  return client.request<HardwareLifecycleOut>(
    `${robotPath(projectId, robotId)}/parts/${partId}/lifecycle`,
    { method: 'POST', body }
  )
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

/** Interrogate safely (ping/listen only) and build a proposal. No body → server defaults. */
export function proposeDetected(
  projectId: string,
  deviceRef: string,
  body?: Partial<ProposeIn>,
  client: ApiClient = api
): Promise<ProposalOut> {
  return client.request<ProposalOut>(`${detectedPath(projectId, deviceRef)}/propose`, {
    method: 'POST',
    body
  })
}

export function confirmDetected(
  projectId: string,
  deviceRef: string,
  body: ConfirmIn,
  client: ApiClient = api
): Promise<ConfirmOut> {
  return client.request<ConfirmOut>(`${detectedPath(projectId, deviceRef)}/confirm`, {
    method: 'POST',
    body
  })
}

/** Connector-sourced parts no robot category owns yet (From a file), paged. */
export function listUnassignedParts(
  projectId: string,
  cursor: string | null = null,
  client: ApiClient = api
): Promise<Page<Entity[]>> {
  const query = new URLSearchParams({ limit: '24' })
  if (cursor) query.set('cursor', cursor)
  return client.requestPage<Entity[]>(`/projects/${projectId}/hardware/unassigned?${query}`)
}

export function attachParts(
  projectId: string,
  robotId: string,
  input: AttachIn,
  client: ApiClient = api
): Promise<AttachOut> {
  return client.request<AttachOut>(`${robotPath(projectId, robotId)}/parts/attach`, {
    method: 'POST',
    body: input
  })
}

/** Lexical search over the curated definitions; an empty query lists the seed. */
export function searchLibrary(
  projectId: string,
  q = '',
  client: ApiClient = api
): Promise<LibraryHit[]> {
  const query = new URLSearchParams({ q })
  return client.request<LibraryHit[]>(`${libraryPath(projectId)}?${query}`)
}

export function getLibraryDefinition(
  projectId: string,
  kind: LibraryKind,
  definitionId: string,
  client: ApiClient = api
): Promise<LibraryDefinition> {
  return client.request<LibraryDefinition>(
    `${libraryPath(projectId)}/${kind}/${encodeURIComponent(definitionId)}`
  )
}

/** Import a platform as a new robot; no name → the definition's. */
export function importLibraryPlatform(
  projectId: string,
  definitionId: string,
  name?: string,
  client: ApiClient = api
): Promise<PlatformImportOut> {
  return client.request<PlatformImportOut>(
    `${libraryPath(projectId)}/platforms/${encodeURIComponent(definitionId)}/import`,
    { method: 'POST', body: { name: name ?? null } }
  )
}

export function importLibraryPart(
  projectId: string,
  definitionId: string,
  input: PartImportIn,
  client: ApiClient = api
): Promise<PartImportOut> {
  return client.request<PartImportOut>(
    `${libraryPath(projectId)}/parts/${encodeURIComponent(definitionId)}/import`,
    { method: 'POST', body: input }
  )
}
