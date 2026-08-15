// The LB-06 telemetry packet decoder — the TypeScript half of the format (SOLUSDEV-126).
//
// This mirrors `packages/api/src/solus_api/graph/codec.py` field for field. It is a SECOND
// implementation of one format, so the risk is drift, and the guard against drift is the golden
// fixture corpus at `packages/api/tests/fixtures/telemetry/`: the Python suite regenerates and
// byte-compares it, this file's test suite decodes it, and `limits.json` pins the shared bounds.
// Change the format on either side without regenerating and one of the two suites goes red.
//
// Field names stay snake_case to match the backend wire shape, per the convention
// `lib/api/resources.ts` already follows. The functions carry a `...Packet` suffix rather than a
// bare `decode`/`encode` so the mirror of a Python symbol is distinguishable at a UI call site.
//
// `ts_us` is epoch MICROSECONDS as an integer, never seconds and never a string — the Python
// side computes it with integer arithmetic because float seconds lose microsecond precision at
// modern epoch magnitudes. JS numbers are exact to 2^53, which covers microsecond timestamps
// past the year 2255, so plain `number` is safe here.
//
// Decoding is a TRUST BOUNDARY (CLAUDE.md §7): in Live Bench real mode these bytes can arrive
// from a local robot/bridge without the backend in the path, so malformed input must throw
// rather than surface `undefined` or `NaN` into a chart.
import { decode as msgpackDecode, encode as msgpackEncode } from '@msgpack/msgpack'

/** Wire-format version this build was written against. Mirrors `limits.json`. */
export const SCHEMA_VERSION = 1

/** Wire key for the timestamp: integer microseconds since the Unix epoch. */
export const TS_KEY = 'ts_us'

/** A packet is one reading from one device, not a file. */
export const MAX_PACKET_BYTES = 64 * 1024

// FIELD-level bounds, shared with Python and asserted against the generated `limits.json`, so a
// change on either side fails a test instead of drifting silently.
//
// The UNPACKER-level bounds are deliberately NOT mirrored and cannot be: Python caps
// max_str_len/max_map_len/max_array_len and disables bin/ext outright, while @msgpack/msgpack v3
// removed its decoder-limit options. The asymmetry is contained rather than dangerous — unknown
// fields are dropped before they reach the app, every retained field is type- and
// length-checked individually, and the payload is size-capped first — but it is real, so a
// packet Python refuses for an oversized unknown field may decode here. The backend stays the
// authoritative validator; see `docs/contracts/telemetry-packet.md` §6.
export const MAX_DEVICE_ID_LEN = 512
export const MAX_SIGNALS_PER_PACKET = 256
export const MAX_SIGNAL_NAME_LEN = 128
export const MAX_UNIT_LEN = 32

/**
 * One reading from a device/topic: named numeric signals at an instant.
 *
 * `readonly` throughout, mirroring the Python model's `frozen=True` — a decoded packet is a
 * value, not a mutable buffer.
 *
 * TWO timestamp fields, and the distinction matters. `ts_us` is CANONICAL: the exact integer the
 * wire carries, and the only one `toWire` re-encodes. `timestamp` is a convenience for chart and
 * axis code, and a JS `Date` holds MILLISECONDS — so it silently truncates the format's
 * microsecond resolution (…123456µs reads back as …123000µs). Re-encoding from `timestamp` would
 * therefore corrupt every packet that passes through the UI, which is exactly what the
 * fixture-parity test caught. Read `timestamp`; round-trip `ts_us`.
 */
export interface TelemetryPacket {
  readonly schema_version: number
  readonly device_id: string
  /** Canonical: integer microseconds since the Unix epoch, exactly as the wire carries it. */
  readonly ts_us: number
  /** Convenience view of `ts_us`, truncated to millisecond resolution by `Date` itself. */
  readonly timestamp: Date
  /** Monotonic per-device counter, or null when the producer does not sequence its stream. */
  readonly seq: number | null
  readonly values: Readonly<Record<string, number>>
  readonly units: Readonly<Record<string, string>>
}

/**
 * The single error type callers catch — malformed framing and failed validation alike.
 *
 * Named `Telemetry...` rather than mirroring Python's `PacketDecodeError` because hook H6 blocks
 * a class name that already exists anywhere in the repo, across languages. Same concept, same
 * role, one name apart; see the completion report.
 */
export class TelemetryDecodeError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'TelemetryDecodeError'
  }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requireInteger(raw: unknown, field: string): number {
  // isSafeInteger, NOT isInteger: `Number.isInteger(1e300)` is TRUE, and 1e300 microseconds
  // produces an `Invalid Date` whose getTime() is NaN — exactly the "never surface NaN into a
  // chart" failure this module exists to prevent. It also rejects values above 2^53 that would
  // otherwise decode with silent precision loss, plus booleans, NaN and Infinity.
  if (!Number.isSafeInteger(raw)) throw new TelemetryDecodeError(`${field} must be a safe integer`)
  return raw as number
}

function readValues(raw: unknown): Record<string, number> {
  if (!isPlainRecord(raw)) throw new TelemetryDecodeError('values must be a map')
  // Object.create(null), NOT `{}`: a signal legitimately named `__proto__` (topic names are free
  // text on a robot bus) is an OWN property after JSON.parse, but assigning it on a normal object
  // literal hits the Object.prototype setter and silently vanishes — Python would keep it, so the
  // two runtimes would disagree about the packet's contents.
  const values: Record<string, number> = Object.create(null)
  for (const [name, value] of Object.entries(raw)) {
    if (!name || name.length > MAX_SIGNAL_NAME_LEN) {
      throw new TelemetryDecodeError(`signal name length out of range: ${name.slice(0, 32)}`)
    }
    // Rejecting NaN/Infinity is the point: msgpack and JSON can both carry them, and a NaN
    // reaching a chart axis corrupts the whole view instead of failing loudly.
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw new TelemetryDecodeError(`signal ${name.slice(0, 32)} is not a finite number`)
    }
    values[name] = value
  }
  // Counted AFTER the loop, so the bounds measure what was actually built rather than what the
  // payload claimed — otherwise `{"__proto__": 1}` passes a non-empty check and yields no signals.
  const count = Object.keys(values).length
  if (count === 0) throw new TelemetryDecodeError('packet carries no signal values')
  if (count > MAX_SIGNALS_PER_PACKET) {
    throw new TelemetryDecodeError(`too many signals (max ${MAX_SIGNALS_PER_PACKET})`)
  }
  return values
}

function readUnits(raw: unknown, values: Record<string, number>): Record<string, string> {
  if (raw === undefined || raw === null) return Object.create(null)
  if (!isPlainRecord(raw)) throw new TelemetryDecodeError('units must be a map')
  const units: Record<string, string> = Object.create(null)
  for (const [name, unit] of Object.entries(raw)) {
    if (typeof unit !== 'string' || !unit || unit.length > MAX_UNIT_LEN) {
      throw new TelemetryDecodeError(`unit for ${name.slice(0, 32)} length out of range`)
    }
    // Object.hasOwn, NOT `in`: `in` walks the prototype chain, so `'toString' in values` is true
    // and units named toString/constructor/valueOf slipped past this check entirely — Python
    // rejects them (it compares real key sets), and the decoded object then carried a STRING
    // `toString`, so any template-literal or tooltip touching it threw and unmounted the panel.
    if (!Object.hasOwn(values, name)) {
      throw new TelemetryDecodeError(`units name a signal not in this packet: ${name.slice(0, 32)}`)
    }
    units[name] = unit
  }
  return units
}

function readDeviceId(raw: unknown): string {
  if (typeof raw !== 'string' || !raw || raw.length > MAX_DEVICE_ID_LEN) {
    throw new TelemetryDecodeError('device_id length out of range')
  }
  return raw
}

function readSeq(raw: unknown): number | null {
  if (raw === undefined || raw === null) return null
  const seq = requireInteger(raw, 'seq')
  if (seq < 0) throw new TelemetryDecodeError('seq must not be negative')
  return seq
}

function readSchemaVersion(raw: unknown): number {
  if (raw === undefined) return SCHEMA_VERSION
  const version = requireInteger(raw, 'schema_version')
  if (version < 1) throw new TelemetryDecodeError('schema_version must be >= 1')
  return version
}

function readTsUs(wire: Record<string, unknown>): number {
  if (!(TS_KEY in wire)) throw new TelemetryDecodeError(`packet is missing ${TS_KEY}`)
  return requireInteger(wire[TS_KEY], TS_KEY)
}

/**
 * Wire object → packet, TOLERANTLY: unknown keys are ignored so a packet from a NEWER producer
 * still decodes here, and its higher `schema_version` is reported rather than rewritten. This is
 * the forward-compatibility contract — adding a field is never a breaking change.
 */
export function fromWire(wire: unknown): TelemetryPacket {
  if (!isPlainRecord(wire)) throw new TelemetryDecodeError('packet payload must be a map')
  const values = readValues(wire.values)
  const tsUs = readTsUs(wire)
  return {
    schema_version: readSchemaVersion(wire.schema_version),
    device_id: readDeviceId(wire.device_id),
    ts_us: tsUs,
    timestamp: new Date(tsUs / 1000),
    seq: readSeq(wire.seq),
    values,
    units: readUnits(wire.units, values)
  }
}

/** Packet → the canonical wire object. Omits what carries no information, exactly as Python does. */
export function toWire(packet: TelemetryPacket): Record<string, unknown> {
  const wire: Record<string, unknown> = {
    schema_version: packet.schema_version,
    device_id: packet.device_id,
    // From `ts_us`, NEVER from `timestamp` — a Date would truncate microseconds to zero.
    [TS_KEY]: packet.ts_us,
    values: { ...packet.values }
  }
  if (packet.seq !== null) wire.seq = packet.seq
  if (Object.keys(packet.units).length > 0) wire.units = { ...packet.units }
  return wire
}

/** msgpack → packet. Size-capped before unpacking; every failure is a `TelemetryDecodeError`. */
export function decodePacket(raw: Uint8Array): TelemetryPacket {
  if (raw.byteLength === 0) throw new TelemetryDecodeError('empty packet payload')
  if (raw.byteLength > MAX_PACKET_BYTES) {
    throw new TelemetryDecodeError(`packet exceeds ${MAX_PACKET_BYTES} bytes`)
  }
  let wire: unknown
  try {
    wire = msgpackDecode(raw)
  } catch {
    throw new TelemetryDecodeError('malformed msgpack payload')
  }
  return fromWire(wire)
}

/** packet → msgpack, the throughput form. */
export function encodePacket(packet: TelemetryPacket): Uint8Array {
  return msgpackEncode(toWire(packet))
}

/** JSON debug form → packet. Same tolerance, same single error type as `decodePacket`. */
export function decodePacketJson(raw: string): TelemetryPacket {
  if (raw.length > MAX_PACKET_BYTES) {
    throw new TelemetryDecodeError(`packet exceeds ${MAX_PACKET_BYTES} bytes`)
  }
  let wire: unknown
  try {
    wire = JSON.parse(raw)
  } catch {
    throw new TelemetryDecodeError('malformed JSON payload')
  }
  return fromWire(wire)
}

/** packet → the JSON debug form (the same wire object, JSON-encoded). */
export function encodePacketJson(packet: TelemetryPacket): string {
  return JSON.stringify(toWire(packet))
}
