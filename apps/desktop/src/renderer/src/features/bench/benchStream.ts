import type { BenchDeviceRecent, BenchSignalSeries } from '../../lib/api/resources'

export function benchSocketUrl(base: string, session: string): string {
  const url = new URL(base)
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Unsupported API URL')
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `${url.pathname.replace(/\/+$/, '').replace(/\/api\/v1$/, '')}/ws/v1/bench/sessions/${encodeURIComponent(session)}`
  url.search = ''
  url.hash = ''
  return url.toString()
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Invalid telemetry')
  return value as Record<string, unknown>
}
function text(value: unknown, max: number): string {
  if (typeof value !== 'string' || !value.length || value.length > max)
    throw new Error('Invalid telemetry text')
  return value
}
function list(value: unknown, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) throw new Error('Invalid telemetry list')
  return value
}
function series(value: unknown): BenchSignalSeries {
  const row = record(value)
  const role = row.display_role
  if (role !== undefined && role !== null && role !== 'primary' && role !== 'diagnostic')
    throw new Error('Invalid role')
  return {
    signal: text(row.signal, 128),
    display_role: role,
    points: list(row.points, 128).map((item) => {
      const point = record(item)
      const timestamp = text(point.timestamp, 64)
      if (
        !Number.isFinite(Date.parse(timestamp)) ||
        typeof point.value !== 'number' ||
        !Number.isFinite(point.value)
      )
        throw new Error('Invalid sample')
      return {
        timestamp,
        value: point.value,
        unit: point.unit == null ? null : text(point.unit, 64)
      }
    })
  }
}
export function decodeBenchFrame(
  raw: unknown,
  project: string,
  session: string
): BenchDeviceRecent[] {
  if (typeof raw !== 'string' || raw.length > 4_194_304) throw new Error('Oversized telemetry')
  const frame = record(JSON.parse(raw))
  if (frame.type !== 'telemetry' || frame.project_id !== project || frame.session_id !== session)
    throw new Error('Wrong telemetry scope')
  const devices = list(frame.devices, 64).map((item) => {
    const row = record(item)
    const signals = list(row.signals, 256).map(series)
    if (new Set(signals.map((s) => s.signal)).size !== signals.length)
      throw new Error('Duplicate channel')
    return {
      device_id: text(row.device_id, 512),
      resolved_entity_id: row.resolved_entity_id === null ? null : text(row.resolved_entity_id, 64),
      signals
    }
  })
  if (new Set(devices.map((d) => d.device_id)).size !== devices.length)
    throw new Error('Duplicate device')
  return devices
}

export function isBenchHeartbeat(raw: unknown, project: string, session: string): boolean {
  if (typeof raw !== 'string' || raw.length > 4_194_304) throw new Error('Invalid frame')
  const frame = record(JSON.parse(raw))
  if (frame.type !== 'heartbeat') return false
  if (frame.project_id !== project || frame.session_id !== session)
    throw new Error('Wrong heartbeat scope')
  return true
}

/** A single authenticated read-only connection. Reconnect is bounded; REST is
 * available immediately on loss. No motion/control frames or URL credentials. */
export function connectBenchStream(options: {
  baseUrl: string
  project: string
  session: string
  token: string
  receive: (devices: BenchDeviceRecent[]) => void
  unavailable: (blocked?: boolean) => void
}): () => void {
  let disposed = false
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let deadline: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  const open = (): void => {
    if (disposed) return
    const current = new WebSocket(benchSocketUrl(options.baseUrl, options.session))
    socket = current
    const active = (): boolean => !disposed && socket === current
    const watch = (): void => {
      clearTimeout(deadline)
      deadline = setTimeout(() => {
        if (active()) {
          options.unavailable()
          current.close()
        }
      }, 10_000)
    }
    watch()
    current.onopen = () => {
      if (active())
        current.send(
          JSON.stringify({
            type: 'authenticate',
            token: options.token,
            project_id: options.project
          })
        )
    }
    current.onmessage = (event) => {
      if (!active()) return
      try {
        if (!isBenchHeartbeat(event.data, options.project, options.session)) {
          options.receive(decodeBenchFrame(event.data, options.project, options.session))
        }
        watch()
      } catch {
        options.unavailable()
        current.close(1008, 'Invalid telemetry frame')
      }
    }
    current.onerror = () => {
      if (active()) {
        options.unavailable()
        current.close()
      }
    }
    current.onclose = (event) => {
      if (!active()) return
      clearTimeout(deadline)
      options.unavailable([4401, 4403, 4404].includes(event.code))
      if ([4400, 4401, 4403, 4404, 1000, 1008].includes(event.code) || attempts >= 5) return
      retry = setTimeout(open, Math.min(1000 * 2 ** attempts++, 16_000))
    }
  }
  open()
  return () => {
    disposed = true
    clearTimeout(retry)
    clearTimeout(deadline)
    socket?.close()
  }
}
