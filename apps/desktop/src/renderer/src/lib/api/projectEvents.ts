// Authenticated, project-scoped invalidation hints from the existing Solus SSE
// endpoint. This typed transport never calls a provider or requests a sync.
import { joinUrl } from './client'
import { ApiError } from './envelope.types'
import type { DetectedDeviceOut, DetectedLevel } from './hardware'
import { parseSseBuffer } from './solStream'

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

const MAX_DEVICES = 64
const LEVELS: readonly DetectedLevel[] = ['transport', 'board', 'protocol', 'platform']

type Check = (value: unknown) => boolean
const isString: Check = (value) => typeof value === 'string'
const isNullableString: Check = (value) => value === null || typeof value === 'string'
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
async function openProjectStream(
  options: ProjectEventOptions
): Promise<ReadableStream<Uint8Array>> {
  const token = await options.getToken()
  options.signal?.throwIfAborted()
  const response = await (options.fetchImpl ?? fetch)(
    joinUrl(options.baseUrl, `/projects/${options.projectId}/events`),
    {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      signal: options.signal
    }
  )
  if (!response.ok || !response.body)
    throw new ApiError(response.status, 'project_stream_failed', 'Live updates disconnected.')
  return response.body
}

export async function* streamProjectEvents(
  options: ProjectEventOptions
): AsyncGenerator<ProjectEvent> {
  const body = await openProjectStream(options)
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseBuffer(buffer)
      buffer = parsed.rest
      if (buffer.length > 65_536) throw new Error('Project event frame is too large.')
      for (const event of parsed.events) {
        if (event.data.project_id !== options.projectId) continue
        if (event.type === 'ready' || event.type === 'graph.changed') yield event.type
        else if (event.type === 'hardware.devices_changed') {
          const devices = toDetectedDevices(event.data.devices)
          if (devices) yield { type: event.type, devices }
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
