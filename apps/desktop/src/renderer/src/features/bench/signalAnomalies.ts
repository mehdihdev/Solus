import { api } from '../../lib/api/client'
import type { ObserverEventOut, RecentSampleOut } from '../../widgets/livebench/telemetry'

function boundedText(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= max
}
function validTime(value: unknown): value is string {
  return (
    boundedText(value, 40) &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}
function validValue(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value))
}
const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
/** A marker the window evaluator raised carries its finding (docs/api/findings.md §5). */
export interface SignalAnomaly extends ObserverEventOut {
  readonly finding_id?: string
}
/** The server attaches the id to the ring's own record; one present but not a UUID makes the
 *  response malformed, like any other bad field. */
function findingField(value: unknown): { finding_id?: string } {
  if (value === undefined || value === null) return {}
  if (typeof value !== 'string' || !UUID.test(value)) throw new Error('Invalid observer event')
  return { finding_id: value }
}
/** Observer values have no unit; markers communicate time only, never guessed magnitudes. */
export function decodeAnomalies(raw: unknown): SignalAnomaly[] {
  if (!Array.isArray(raw) || raw.length > 100) throw new Error('Invalid observer events')
  return raw.map((row: unknown) => {
    if (typeof row !== 'object' || row === null) throw new Error('Invalid observer event')
    const r = row as Record<string, unknown>
    if (
      !boundedText(r.kind, 32) ||
      !['threshold_breach', 'change_point', 'stream_gap'].includes(r.kind) ||
      !boundedText(r.device_id, 512) ||
      !boundedText(r.signal, 128) ||
      !validTime(r.at) ||
      !validValue(r.value)
    )
      throw new Error('Invalid observer event')
    return {
      kind: r.kind,
      device_id: r.device_id,
      signal: r.signal,
      at: r.at,
      value: r.value as number | null,
      ...findingField(r.finding_id)
    }
  })
}
export async function getSignalAnomalies(projectId: string): Promise<SignalAnomaly[]> {
  return decodeAnomalies(
    await api.request<unknown>(`/projects/${encodeURIComponent(projectId)}/bench/events?limit=100`)
  )
}
export function anomalyMarkers(
  events: readonly SignalAnomaly[],
  deviceId: string,
  signal: string,
  points: readonly RecentSampleOut[],
  window?: { start: number; end: number }
): { kind: string; at: string; x: number; finding_id?: string }[] {
  const times = points.map((p) => Date.parse(p.timestamp)).filter(Number.isFinite)
  if (!times.length) return []
  const min = window?.start ?? Math.min(...times),
    max = window?.end ?? Math.max(...times)
  const seen = new Set<string>()
  return events.flatMap((event) => {
    const time = Date.parse(event.at),
      key = `${event.kind}:${time}:${event.finding_id ?? ''}`
    if (
      event.device_id !== deviceId ||
      event.signal !== signal ||
      !Number.isFinite(time) ||
      time < min ||
      time > max ||
      seen.has(key)
    )
      return []
    seen.add(key)
    const x = ((time - min) / Math.max(max - min, 1)) * 240
    return [{ kind: event.kind, at: event.at, x, ...findingField(event.finding_id) }]
  })
}
