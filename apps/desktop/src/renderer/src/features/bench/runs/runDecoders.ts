import type { RunComparison, RunDetail, RunFindings, RunSummary, RunNarration } from './runsApi'
type Check = (value: unknown) => boolean
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const text =
  (max: number, min = 1): Check =>
  (value) =>
    typeof value === 'string' && value.length >= min && value.length <= max
const finite: Check = (value) => typeof value === 'number' && Number.isFinite(value)
const count =
  (max = Number.MAX_SAFE_INTEGER): Check =>
  (value) =>
    typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max
const nullable =
  (check: Check): Check =>
  (value) =>
    value === null || check(value)
const optional =
  (check: Check): Check =>
  (value) =>
    value === undefined || check(value)
const oneOf =
  (...items: unknown[]): Check =>
  (value) =>
    items.includes(value)
const uuid: Check = (value) =>
  typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value)
const array =
  (max: number, check: Check): Check =>
  (value) =>
    Array.isArray(value) && value.length <= max && value.every(check)
function shape(fields: Record<string, Check>): Check {
  return (value) =>
    object(value) &&
    Object.keys(value).every((key) => Object.hasOwn(fields, key)) &&
    Object.entries(fields).every(([key, check]) => check(value[key]))
}
function validDate(year: number, month: number, day: number): boolean {
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= days
}
function characterBytes(character: string): number {
  const point = character.codePointAt(0) ?? 0
  if (point < 32 || (point >= 0xd800 && point <= 0xdfff)) return 6
  if (character === '"' || character === '\\') return 2
  if (point < 128) return 1
  if (point < 2048) return 2
  return point < 65536 ? 3 : 4
}
const timestamp: Check = (value) => {
  if (typeof value !== 'string' || value.length > 40) return false
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(
      value
    )
  if (!match) return false
  const [, year, month, day, hour, minute, second, zoneHour = '0', zoneMinute = '0'] = match
  return (
    validDate(Number(year), Number(month), Number(day)) &&
    validClock(Number(hour), Number(minute), Number(second)) &&
    validClock(Number(zoneHour), Number(zoneMinute), 0) &&
    Number.isFinite(Date.parse(value))
  )
}
const summaryCheck = shape({
  id: uuid,
  robot_id: uuid,
  session_id: nullable(uuid),
  name: text(120),
  origin: oneOf('live', 'recorded', 'synthetic'),
  status: oneOf('running', 'completed', 'truncated', 'interrupted'),
  started_at: timestamp,
  ended_at: nullable(timestamp),
  packet_count: count(10000),
  drop_count: count(),
  artifact_id: nullable(uuid)
})
const dictionary =
  (max: number, keyCheck: Check, valueCheck: Check, min = 0): Check =>
  (value) =>
    object(value) &&
    Object.keys(value).length >= min &&
    Object.keys(value).length <= max &&
    Object.entries(value).every(([key, item]) => keyCheck(key) && valueCheck(item))
const packetShape = shape({
  device_id: text(512),
  timestamp,
  values: dictionary(256, text(128), finite, 1),
  units: dictionary(256, text(128), text(32)),
  seq: optional(nullable(count())),
  schema_version: optional((value) => count(1000000)(value) && value !== 0)
})
const packet: Check = (value) =>
  packetShape(value) &&
  object(value) &&
  object(value.units) &&
  object(value.values) &&
  Object.keys(value.units).every((key) => Object.hasOwn(value.values as object, key))
const part = shape({
  entity_id: uuid,
  name: text(512),
  device_id: text(512),
  current_signal: optional(nullable(text(128))),
  position_signal: optional(nullable(text(128))),
  command_signal: optional(nullable(text(128))),
  stall_current_a: optional(nullable((value) => finite(value) && (value as number) > 0)),
  position_min: optional(nullable(finite)),
  position_max: optional(nullable(finite)),
  position_unit: optional(nullable(text(32, 0))),
  code_site: optional(nullable(text(512))),
  cad_revision: optional(nullable(text(512)))
})
const sensor = shape({
  artifact_id: uuid,
  timestamp,
  kind: oneOf('camera', 'lidar'),
  device_id: text(512)
})
const snapshot = shape({
  entity_id: uuid,
  kind: text(512),
  name: text(512),
  source_id: optional(nullable(uuid)),
  revision: optional(nullable(text(512))),
  data: optional(nullable(text(65536, 0)))
})
const manifestShape = shape({
  schema_version: oneOf(1),
  robot_id: uuid,
  started_at: timestamp,
  packets: array(10000, packet),
  sensors: array(10000, sensor),
  parts: array(256, part),
  snapshots: array(256, snapshot)
})
const manifest: Check = (value) => {
  if (!bounded(value) || !manifestShape(value) || !object(value)) return false
  const parts = value.parts as Array<{ entity_id: string; device_id: string }>
  if (
    new Set(parts.map((row) => row.entity_id.toLowerCase())).size !== parts.length ||
    new Set(parts.map((row) => row.device_id)).size !== parts.length
  )
    return false
  const identities = new Set<string>()
  for (const row of value.packets as Array<{ device_id: string; values: object }>) {
    for (const key of Object.keys(row.values)) identities.add(JSON.stringify([row.device_id, key]))
    if (identities.size > 4096) return false
  }
  return true
}
const detailCheck: Check = (value) =>
  shape({ summary: summaryCheck, manifest })(value) &&
  object(value) &&
  object(value.summary) &&
  object(value.manifest) &&
  value.summary.robot_id === value.manifest.robot_id
const scalar: Check = (value) => value === null || finite(value) || text(512, 0)(value)
const findingFields = {
  evidence_origin: optional(oneOf('live', 'recorded', 'synthetic')),
  findings: array(
    256,
    shape({
      entity_id: uuid,
      headline: text(1024),
      explanation: text(2048),
      detail: text(2048),
      code_site: nullable(text(512)),
      cad_revision: nullable(text(512)),
      evidence: shape({
        stall_current_a: (value) => finite(value) && (value as number) > 0,
        measured_current_min_a: finite,
        commanded_min: finite,
        commanded_max: finite,
        configured_min: nullable(finite),
        configured_max: nullable(finite),
        position_unit: text(32),
        samples: (value) => count(10000)(value) && (value as number) >= 3,
        window_start: timestamp,
        window_end: timestamp
      })
    })
  ),
  insufficient: array(256, shape({ entity_id: nullable(uuid), reason: text(2048) }))
}
const findingsCheck = shape(findingFields)
const configChange: Check = (value) => {
  if (
    !shape({
      entity_id: uuid,
      field: oneOf('position_min', 'position_max', 'position_unit', 'code_site', 'cad_revision'),
      before: scalar,
      after: scalar
    })(value) ||
    !object(value)
  )
    return false
  const check =
    value.field === 'position_min' || value.field === 'position_max'
      ? nullable(finite)
      : nullable(
          text(value.field === 'position_unit' ? 32 : 512, value.field === 'position_unit' ? 0 : 1)
        )
  return check(value.before) && check(value.after)
}
const comparisonCheck = shape({
  config_changes: array(1280, configChange),
  source_snapshots_changed: oneOf(true, false),
  divergences: array(
    8192,
    shape({
      device_id: text(512),
      signal: text(128),
      aligned_samples: count(10000),
      max_difference: (value) => finite(value) && (value as number) >= 0,
      unit: nullable(text(32))
    })
  ),
  clamp_attributions: array(
    256,
    shape({ entity_id: uuid, explanation: text(2048), before_limit: finite, after_limit: finite })
  ),
  insufficient: array(8192, shape({ device_id: text(512), signal: text(128), reason: text(2048) }))
})
/** Bound traversal and decoded text before nested validation. Never stringify an
 * unvalidated graph or allocate a second whole response to measure its size. */
class DecodeBudget {
  private bytes = 0
  private nodes = 0
  constructor(private readonly limit: number) {}
  visit(item: unknown, depth: number): boolean {
    if (++this.nodes > 4194304 || depth > 12 || this.bytes > this.limit) return false
    if (typeof item === 'string') return this.string(item)
    if (Array.isArray(item)) return this.array(item, depth)
    if (object(item)) return this.record(item, depth)
    if (item === null || typeof item === 'boolean' || finite(item))
      this.bytes += String(item).length
    else return false
    return this.bytes <= this.limit
  }
  private string(item: string): boolean {
    if (item.length > 65536) return false
    this.bytes += 2
    for (const character of item) this.bytes += characterBytes(character)
    return this.bytes <= this.limit
  }
  private array(item: unknown[], depth: number): boolean {
    if (item.length > 10000) return false
    this.bytes += item.length + 2
    return item.every((child) => this.visit(child, depth + 1)) && this.bytes <= this.limit
  }
  private record(item: Record<string, unknown>, depth: number): boolean {
    const entries = Object.entries(item)
    if (entries.length > 256) return false
    this.bytes += entries.length * 2 + 2
    return (
      entries.every(([key, child]) => this.visit(key, depth + 1) && this.visit(child, depth + 1)) &&
      this.bytes <= this.limit
    )
  }
}
function bounded(value: unknown, limit = 8 * 1024 * 1024): boolean {
  return new DecodeBudget(limit).visit(value, 0)
}
function decode<T>(value: unknown, check: Check, limit?: number): T {
  if (!bounded(value, limit) || !check(value))
    throw new Error('Invalid run response; recorded evidence could not be read safely.')
  return value as T
}
export const decodeRunSummary = (value: unknown): RunSummary => decode(value, summaryCheck)
export const decodeRunDetail = (value: unknown): RunDetail =>
  decode(value, detailCheck, 8 * 1024 * 1024 + 4096)
export const decodeRunFindings = (value: unknown): RunFindings => decode(value, findingsCheck)
export const decodeRunComparison = (value: unknown): RunComparison => decode(value, comparisonCheck)
export const decodeRunList = (value: unknown): { runs: RunSummary[]; next_cursor: string | null } =>
  decode(value, shape({ runs: array(50, summaryCheck), next_cursor: nullable(text(2048)) }))

export const decodeRunNarration = (value: unknown): RunNarration =>
  decode(
    value,
    shape({
      ...findingFields,
      mode: oneOf('model', 'deterministic'),
      reason: text(2048),
      narration: array(256, text(2048))
    })
  )

function validClock(hour: number, minute: number, second: number): boolean {
  return hour <= 23 && minute <= 59 && second <= 59
}
