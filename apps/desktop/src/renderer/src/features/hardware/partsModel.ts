// SOLUSDEV-326 P3: the Hardware page's parts list as groups of rows. Pure: the reads and the
// device rows in, what to draw out. Robots and parts come oldest first, so a new one lands at
// the end of its group and nothing that was on show moves.
import type { DetectedDeviceOut, HardwarePartRow } from '../../lib/api/hardware'
import type { Entity } from '../../lib/api/resources'
import { deriveStatus, type PartStatus } from './partStatus'

export interface PartsData {
  robots: readonly Entity[]
  parts: readonly HardwarePartRow[]
  /** The machine nodes; `properties.devices` (the memory) reaches a machine's owner alone. */
  machines: readonly Entity[]
}

export interface PartRow {
  id: string
  name: string
  what: string
  robot: string | null
  inGraph: boolean
  /** The route takes it: a part no robot holds that is not in the graph yet. */
  canAdd: boolean
  status: PartStatus
}

export interface PartGroup {
  /** The robot's id, or `lone` for the parts no robot holds. */
  id: string
  title: string
  countLabel: string
  /** Null for the "Not on a robot" group, which is not a thing to add. */
  inGraph: boolean | null
  canAdd: boolean
  /** A robot with no parts (a plain connection) says its own status. */
  status: PartStatus | null
  rows: PartRow[]
}

const LONE = 'lone'
const text = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const inGraph = (entity: Entity): boolean => entity.properties?.in_graph !== false
const oldestFirst = (a: Entity, b: Entity): number =>
  (a.created_at ?? '').localeCompare(b.created_at ?? '') || a.id.localeCompare(b.id)

function isLive(robot: Entity | undefined): boolean {
  const connection = robot?.properties?.connection
  return (
    typeof connection === 'object' &&
    connection !== null &&
    (connection as { status?: unknown }).status === 'connected'
  )
}

/** One row of a machine's memory: the device and when it was last seen. Null for anything else. */
function remembered(row: unknown): { ref: string; at: string } | null {
  if (typeof row !== 'object' || row === null) return null
  const { device_ref: ref, last_seen: at } = row as Record<string, unknown>
  return typeof ref === 'string' && typeof at === 'string' ? { ref, at } : null
}

/** When this machine last saw each device it remembers. */
function memory(machines: readonly Entity[]): Map<string, string> {
  const seen = new Map<string, string>()
  for (const machine of machines) {
    const rows: unknown = machine.properties?.devices
    for (const row of Array.isArray(rows) ? (rows as unknown[]) : []) {
      const entry = remembered(row)
      if (entry && entry.at > (seen.get(entry.ref) ?? '')) seen.set(entry.ref, entry.at)
    }
  }
  return seen
}

/** One key per described row, built once per read for both React and new-row detection. A
 *  described row has no id, and several can be identical (three planned servo slots with no part
 *  name), so each is numbered among the rows that share its source, name and what. */
export function expectedKeys(
  rows: readonly { source: string; name: string; what: string }[]
): string[] {
  const seen = new Map<string, number>()
  return rows.map((row) => {
    const base = `expected:${row.source}:${row.name}:${row.what}`
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    return `${base}:${n}`
  })
}

/** A thing's status, from its device: the one it names, or one bound to a holder. */
type StatusOf = (ref: string | null, holders: string[], live: boolean, plain: boolean) => PartStatus

function statusReader(
  devices: readonly DetectedDeviceOut[],
  left: readonly DetectedDeviceOut[],
  seen: ReadonlyMap<string, string>
): StatusOf {
  return (ref, holders, live, plain) => {
    const mine = (row: DetectedDeviceOut): boolean =>
      (!!ref && row.device_ref === ref) || (!!row.bound_to && holders.includes(row.bound_to))
    return deriveStatus({
      live,
      plain,
      device: devices.find(mine) ?? null,
      // Seen leaving is newer than the memory as last read.
      lastSeen: left.find(mine)?.last_seen || (ref && seen.get(ref)) || null
    })
  }
}

const whatOf = (part: HardwarePartRow): string =>
  text(part.properties?.model) ?? text(part.properties?.category) ?? ''

function partRow(part: HardwarePartRow, robot: Entity | undefined, status: StatusOf): PartRow {
  const ref = text(part.properties?.device_ref)
  return {
    id: part.id,
    name: part.name,
    what: whatOf(part),
    robot: robot?.name ?? null,
    inGraph: inGraph(part),
    canAdd: !robot && !inGraph(part),
    // A part that names its device is on that one alone: its robot may hold several.
    status: status(ref, robot && !ref ? [part.id, robot.id] : [part.id], isLive(robot), false)
  }
}

/** The parts' rows under their robot's id, or under `lone`. */
function rowsByGroup(
  parts: readonly HardwarePartRow[],
  shown: readonly Entity[],
  status: StatusOf
): Map<string, PartRow[]> {
  const byId = new Map(shown.map((robot) => [robot.id, robot]))
  const rows = new Map<string, PartRow[]>()
  for (const part of [...parts].sort(oldestFirst)) {
    const robot = part.parent_id ? byId.get(part.parent_id) : undefined
    // A connector's part no robot holds is workspace design, not hardware.
    if (!robot && part.origin !== 'manual') continue
    const key = robot?.id ?? LONE
    rows.set(key, [...(rows.get(key) ?? []), partRow(part, robot, status)])
  }
  return rows
}

function robotGroup(robot: Entity, own: PartRow[], status: StatusOf): PartGroup {
  return {
    id: robot.id,
    title: robot.name,
    countLabel: own.length === 1 ? '1 part' : `${own.length} parts`,
    inGraph: inGraph(robot),
    canAdd: !inGraph(robot),
    status: own.length ? null : status(robot.source_key, [robot.id], isLive(robot), true),
    rows: own
  }
}

function loneGroup(lone: PartRow[]): PartGroup {
  return {
    id: LONE,
    title: 'Not on a robot',
    countLabel: String(lone.length),
    inGraph: null,
    canAdd: false,
    status: null,
    rows: lone
  }
}

export function groupParts(
  { robots, parts, machines }: PartsData,
  devices: readonly DetectedDeviceOut[],
  /** The rows that left while watched (deviceStore), `last_seen` the moment each left. */
  left: readonly DetectedDeviceOut[] = []
): { groups: PartGroup[]; count: number } {
  const status = statusReader(devices, left, memory(machines))
  const shown = robots
    .filter((robot) => robot.type === 'physical_robot' && robot.origin === 'manual')
    .sort(oldestFirst)
  const rows = rowsByGroup(parts, shown, status)
  const groups = shown.map((robot) => robotGroup(robot, rows.get(robot.id) ?? [], status))
  const lone = rows.get(LONE) ?? []
  if (lone.length) groups.push(loneGroup(lone))
  return { groups, count: groups.reduce((sum, group) => sum + group.rows.length, 0) }
}
