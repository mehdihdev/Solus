// Authenticated, project-scoped invalidation hints from the existing Solus SSE
// endpoint. This typed transport never calls a provider or requests a sync.
import type {
  AccessRevoked,
  JobStatusName,
  JobUpdated,
  LayoutChanged,
  ProjectUpdated,
  SourcesChanged
} from '@solus/shared-types'
import { JOB_STATUSES } from '@solus/shared-types'
import type { DetectedDeviceOut, DetectedLevel } from './hardware'
import { streamSse } from './liveStream'
import {
  isNonNegativeInt,
  isNullableString,
  isString,
  literal,
  matchesShape,
  type Shape
} from './liveStreamGuards'
import type { SolEvent } from './solStream'

interface ProjectEventOptions {
  projectId: string
  baseUrl: string
  getToken: () => string | null | Promise<string | null>
  signal?: AbortSignal
  fetchImpl?: typeof fetch
}
export type ProjectEvent =
  | 'ready'
  | 'graph.changed'
  | { type: 'hardware.devices_changed'; devices: DetectedDeviceOut[] }
  | { type: 'layout.changed'; version: number }
  | { type: 'sources.changed' }
  | { type: 'project.updated' }
  | { type: 'job.updated'; jobId: string; status: JobStatusName }
  | { type: 'access.revoked' }

const MAX_DEVICES = 64
const LEVELS: readonly DetectedLevel[] = ['transport', 'board', 'protocol', 'platform']

type Check = (value: unknown) => boolean
const isBoolean: Check = (value) => typeof value === 'boolean'
/** One check per wire field — the shape `DetectedDeviceOut` promises, nothing narrower. */
const DEVICE_FIELDS: Record<string, Check> = {
  transport: isString,
  device_ref: isNullableString,
  board: isNullableString,
  board_class: isNullableString,
  last_seen_path: isNullableString,
  identity: (value) => value === null || typeof value === 'object',
  evidence: Array.isArray,
  level: (value) => LEVELS.includes(value as DetectedLevel),
  ambiguous: isBoolean,
  mcu_known: isBoolean,
  confidence: (value) => typeof value === 'number'
}

function isDetectedDevice(value: unknown): value is DetectedDeviceOut {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return Object.entries(DEVICE_FIELDS).every(([field, check]) => check(row[field]))
}

/** Narrow an SSE `devices` payload; anything malformed is dropped (null), never thrown. */
export function toDetectedDevices(value: unknown): DetectedDeviceOut[] | null {
  if (!Array.isArray(value) || value.length > MAX_DEVICES) return null
  return value.every(isDetectedDevice) ? value : null
}

const isJobStatus = (value: unknown): boolean => JOB_STATUSES.includes(value as JobStatusName)
const SHAPES = {
  'layout.changed': {
    type: literal('layout.changed'),
    project_id: isString,
    version: isNonNegativeInt,
    at: isString
  } satisfies Shape<LayoutChanged>,
  'sources.changed': {
    type: literal('sources.changed'),
    project_id: isString,
    source_id: isNullableString,
    at: isString
  } satisfies Shape<SourcesChanged>,
  'project.updated': {
    type: literal('project.updated'),
    project_id: isString,
    team_id: isString,
    at: isString
  } satisfies Shape<ProjectUpdated>,
  'job.updated': {
    type: literal('job.updated'),
    project_id: isString,
    job_id: isString,
    status: isJobStatus,
    at: isString
  } satisfies Shape<JobUpdated>,
  'access.revoked': {
    type: literal('access.revoked'),
    user_id: isNullableString,
    team_id: isNullableString,
    project_id: isNullableString,
    at: isString
  } satisfies Shape<AccessRevoked>
}

/** A revoke names at least one id; on a project stream it is for us unless it
 *  names a DIFFERENT project (a team-level revoke leaves project_id null). */
function isRevokeForProject(data: Record<string, unknown>, projectId: string): boolean {
  const ids = [data.user_id, data.team_id, data.project_id]
  return (
    ids.some((id) => id !== null) && (data.project_id === null || data.project_id === projectId)
  )
}

function decodeScoped(event: SolEvent, projectId: string): ProjectEvent | null {
  const { type, data } = event
  if (!(type in SHAPES) || !matchesShape(data, SHAPES[type as keyof typeof SHAPES])) return null
  if (type === 'access.revoked') return isRevokeForProject(data, projectId) ? { type } : null
  if (data.project_id !== projectId) return null
  switch (type) {
    case 'layout.changed':
      return { type, version: data.version as number }
    case 'job.updated':
      return { type, jobId: data.job_id as string, status: data.status as JobStatusName }
    default:
      return { type } as ProjectEvent
  }
}

function decodeProjectEvent(event: SolEvent, projectId: string): ProjectEvent | null {
  if (event.type === 'ready' || event.type === 'graph.changed') {
    return event.data.project_id === projectId ? event.type : null
  }
  if (event.type === 'hardware.devices_changed') {
    if (event.data.project_id !== projectId) return null
    const devices = toDetectedDevices(event.data.devices)
    return devices ? { type: event.type, devices } : null
  }
  return decodeScoped(event, projectId)
}

export function streamProjectEvents(options: ProjectEventOptions): AsyncGenerator<ProjectEvent> {
  return streamSse({
    path: `/projects/${options.projectId}/events`,
    baseUrl: options.baseUrl,
    getToken: options.getToken,
    signal: options.signal,
    fetchImpl: options.fetchImpl,
    decode: (event) => decodeProjectEvent(event, options.projectId)
  })
}
