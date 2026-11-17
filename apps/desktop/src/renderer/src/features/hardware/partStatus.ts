// SOLUSDEV-326 P3: a part's status on the Hardware page. Derived from what is true now (the
// device rows, the robot's connection, the machine's memory), never a stored value.
import type { DetectedDeviceOut } from '../../lib/api/hardware'

export type PartStatus =
  | { kind: 'connected' | 'not_connected' | 'identifying' | 'streaming' | 'not_seen' }
  | { kind: 'last_seen'; at: string }

export interface StatusFacts {
  /** Its robot's connection is live. */
  live: boolean
  /** A plain connection: a device kept with no protocol and no parts. */
  plain: boolean
  /** Its device, when it is plugged in now. */
  device: DetectedDeviceOut | null
  /** When this machine last saw its device, when it remembers it. */
  lastSeen: string | null
}

/** Known hardware's status. What the workspace only describes is `{ kind: 'not_seen' }`. */
export function deriveStatus({ live, plain, device, lastSeen }: StatusFacts): PartStatus {
  if (device?.state === 'inspecting' && device.dismissed !== true) return { kind: 'identifying' }
  if (live || device) return { kind: plain ? 'streaming' : 'connected' }
  if (lastSeen) return { kind: 'last_seen', at: lastSeen }
  return { kind: 'not_connected' }
}

const WORDS: Record<Exclude<PartStatus['kind'], 'last_seen'>, string> = {
  connected: 'Connected',
  not_connected: 'Not connected',
  identifying: 'Identifying',
  streaming: 'Unknown, streaming',
  not_seen: 'Not seen yet'
}

const MINUTE = 60_000
const UNITS = [
  ['day', 1440 * MINUTE],
  ['hour', 60 * MINUTE],
  ['minute', MINUTE]
] as const
const AGO = new Intl.RelativeTimeFormat('en', { numeric: 'always' })

export function statusLabel(status: PartStatus, now: number = Date.now()): string {
  if (status.kind !== 'last_seen') return WORDS[status.kind]
  const elapsed = now - Date.parse(status.at)
  // A time that does not parse is no memory at all.
  if (Number.isNaN(elapsed)) return WORDS.not_connected
  const unit = UNITS.find(([, ms]) => elapsed >= ms)
  if (!unit) return 'Last seen just now'
  return `Last seen ${AGO.format(-Math.floor(elapsed / unit[1]), unit[0])}`
}
