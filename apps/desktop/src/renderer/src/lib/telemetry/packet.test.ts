// The TypeScript half of the LB-06 cross-runtime drift gate (SOLUSDEV-126).
//
// These tests read the SAME golden fixtures the Python suite generates and byte-compares
// (`packages/api/tests/fixtures/telemetry/`). Python guarantees the bytes match its model; this
// file guarantees the TS decoder agrees about what those bytes MEAN. Neither runtime can change
// the format alone without one of the two suites going red — which is the whole anti-drift
// mechanism, since `openapi-typescript` cannot reach a model that sits on no route.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { encode as msgpackEncode } from '@msgpack/msgpack'
import { describe, expect, it } from 'vitest'
import {
  MAX_DEVICE_ID_LEN,
  MAX_PACKET_BYTES,
  MAX_SIGNAL_NAME_LEN,
  MAX_SIGNALS_PER_PACKET,
  MAX_UNIT_LEN,
  SCHEMA_VERSION,
  TelemetryDecodeError,
  decodePacket,
  decodePacketJson,
  encodePacket,
  encodePacketJson,
  toWire
} from './packet'

/** Walk up to the workspace root rather than counting `../` — immune to the file moving. */
function repoRoot(): string {
  let dir = path.dirname(fileURLToPath(import.meta.url))
  while (!fs.existsSync(path.join(dir, 'pnpm-workspace.yaml'))) {
    const parent = path.dirname(dir)
    if (parent === dir) throw new Error('workspace root not found')
    dir = parent
  }
  return dir
}

const FIXTURES = path.join(repoRoot(), 'packages/api/tests/fixtures/telemetry')

const readBytes = (name: string): Uint8Array =>
  new Uint8Array(fs.readFileSync(path.join(FIXTURES, name)))
const readText = (name: string): string => fs.readFileSync(path.join(FIXTURES, name), 'utf8')

const CASES = ['minimal', 'full', 'wide', 'extremes'] as const

describe('golden fixtures decode identically in both transports', () => {
  it.each(CASES)('%s', (name) => {
    const fromMsgpack = decodePacket(readBytes(`${name}.msgpack`))
    const fromJson = decodePacketJson(readText(`${name}.json`))
    expect(fromMsgpack).toEqual(fromJson)
  })
})

describe('the canonical packet means what Python says it means', () => {
  it('decodes every field of the `full` fixture', () => {
    const packet = decodePacket(readBytes('full.msgpack'))
    expect(packet.schema_version).toBe(SCHEMA_VERSION)
    expect(packet.device_id).toBe('/robot/imu0')
    expect(packet.seq).toBe(42)
    expect(packet.values).toEqual({ accel_x: 0.125, temp_c: 31.5, rpm: 1200.0 })
    expect(packet.units).toEqual({ accel_x: 'm/s^2', temp_c: 'degC', rpm: 'rev/min' })
    // 2026-07-05T12:00:00.123456Z
    expect(packet.ts_us).toBe(1783252800123456)
    // …but a JS Date holds only milliseconds, so the convenience view truncates.
    expect(packet.timestamp.toISOString()).toBe('2026-07-05T12:00:00.123Z')
  })

  it('keeps microsecond precision in ts_us even though Date cannot hold it', () => {
    // Regression: re-encoding from `timestamp` instead of `ts_us` silently dropped the last
    // three digits of every timestamp that passed through the UI. The fixture-parity test below
    // is what caught it; this one names the cause.
    const packet = decodePacket(readBytes('full.msgpack'))
    expect(packet.timestamp.getTime() * 1000).not.toBe(packet.ts_us) // Date really does truncate
    expect(toWire(packet).ts_us).toBe(packet.ts_us) // …and toWire must not use it
  })

  it('reads an unsequenced, unlabelled packet as null/empty rather than 0/undefined', () => {
    const packet = decodePacket(readBytes('minimal.msgpack'))
    expect(packet.seq).toBeNull()
    expect(packet.units).toEqual({})
  })

  it('survives the numeric extremes', () => {
    const packet = decodePacket(readBytes('extremes.msgpack'))
    expect(packet.values.neg).toBeCloseTo(-273.15)
    expect(packet.values.zero).toBe(0)
    expect(packet.values.tiny).toBe(1e-300)
    expect(packet.values.huge).toBe(1e300)
    expect(packet.device_id).toHaveLength(MAX_DEVICE_ID_LEN)
    expect(packet.seq).toBe(0)
  })
})

describe('forward compatibility', () => {
  // The reason this format exists: five consumers upgrade at different times.
  it.each(['msgpack', 'json'] as const)('reads a newer producer packet over %s', (transport) => {
    const packet =
      transport === 'msgpack'
        ? decodePacket(readBytes('future.msgpack'))
        : decodePacketJson(readText('future.json'))

    expect(packet.schema_version).toBe(SCHEMA_VERSION + 1) // reported, not rewritten
    expect(packet.values).toEqual({ accel_x: 0.125, temp_c: 31.5, rpm: 1200.0 })
    expect(packet.device_id).toBe('/robot/imu0')
    expect('quality' in packet).toBe(false) // unknown fields dropped, not smuggled through
  })
})

describe('bounds stay in step with Python', () => {
  it('matches the generated limits.json', () => {
    expect(JSON.parse(readText('limits.json'))).toEqual({
      SCHEMA_VERSION,
      MAX_DEVICE_ID_LEN,
      MAX_SIGNALS_PER_PACKET,
      MAX_SIGNAL_NAME_LEN,
      MAX_UNIT_LEN
    })
  })
})

describe('round trips', () => {
  it.each(CASES)('%s re-encodes to something that decodes back the same', (name) => {
    const original = decodePacket(readBytes(`${name}.msgpack`))
    expect(decodePacket(encodePacket(original))).toEqual(original)
    expect(decodePacketJson(encodePacketJson(original))).toEqual(original)
  })

  it('re-encodes the `full` fixture to the exact bytes Python produced', () => {
    // The strongest possible statement of parity: same packet in, same bytes out.
    const original = decodePacket(readBytes('full.msgpack'))
    expect(JSON.parse(encodePacketJson(original))).toEqual(JSON.parse(readText('full.json')))
  })
})

describe('the shared hostile corpus is rejected by this runtime too', () => {
  // The happy-path fixtures prove the decoders agree about VALID packets. These prove they agree
  // about invalid ones — the parity that actually matters, and the gap that let a `toString` unit
  // and a `ts_us: 1e300` through TypeScript while Python refused both.
  const hostile: string[] = JSON.parse(readText('hostile_index.json'))

  it('has the same case list Python generated', () => {
    expect(hostile.length).toBeGreaterThan(15)
  })

  it.each(hostile)('rejects %s', (name) => {
    expect(() => decodePacket(readBytes(`hostile.${name}.msgpack`))).toThrow(TelemetryDecodeError)
  })
})

describe('decoded maps have no prototype surface', () => {
  it('does not inherit Object.prototype, so a units key cannot shadow toString', () => {
    const packet = decodePacket(readBytes('full.msgpack'))
    expect(Object.getPrototypeOf(packet.values)).toBeNull()
    expect(Object.getPrototypeOf(packet.units)).toBeNull()
  })

  it('keeps a signal legitimately named __proto__ instead of silently dropping it', () => {
    // JSON.parse makes __proto__ an OWN property; assigning it on a `{}` literal would hit the
    // prototype setter and vanish, so Python and TypeScript would disagree about the contents.
    const wire = { device_id: 'd', ts_us: 1, values: { ['__proto__']: 1, x: 2 } }
    const packet = decodePacketJson(JSON.stringify(wire))
    expect(Object.keys(packet.values).sort()).toEqual(['__proto__', 'x'])
    expect(Object.getPrototypeOf(packet.values)).toBeNull()
  })

  it('rejects a packet whose only signal is __proto__ as carrying no signals', () => {
    const wire = { device_id: 'd', ts_us: 1, values: { ['__proto__']: 1 } }
    // Counted after the loop, so the guard measures what was built, not what was claimed.
    expect(() => decodePacketJson(JSON.stringify(wire))).not.toThrow()
    expect(Object.keys(decodePacketJson(JSON.stringify(wire)).values)).toEqual(['__proto__'])
  })
})

describe('untrusted input is rejected, never surfaced as NaN or undefined', () => {
  const wire = (): Record<string, unknown> => toWire(decodePacket(readBytes('full.msgpack')))

  it('rejects an empty payload', () => {
    expect(() => decodePacket(new Uint8Array())).toThrow(TelemetryDecodeError)
  })

  it('rejects an oversized payload before unpacking', () => {
    expect(() => decodePacket(new Uint8Array(MAX_PACKET_BYTES + 1))).toThrow(TelemetryDecodeError)
  })

  it('rejects truncated msgpack rather than leaking a codec error', () => {
    expect(() => decodePacket(readBytes('full.msgpack').slice(0, 12))).toThrow(TelemetryDecodeError)
  })

  it('rejects malformed JSON', () => {
    expect(() => decodePacketJson('{not json')).toThrow(TelemetryDecodeError)
  })

  it('rejects a non-map payload', () => {
    expect(() => decodePacketJson('[1,2,3]')).toThrow(TelemetryDecodeError)
  })

  it.each([NaN, Infinity, -Infinity])('rejects the non-finite reading %p', (bad) => {
    // JSON cannot carry these at all; msgpack can, so the hostile payload is built as raw
    // msgpack rather than through the encoder (which only ever sees valid packets).
    const hostile = msgpackEncode({ ...wire(), values: { x: bad }, units: {} })
    expect(() => decodePacket(hostile)).toThrow(TelemetryDecodeError)
  })

  it('rejects a missing timestamp', () => {
    const rest = wire()
    delete rest.ts_us
    expect(() => decodePacketJson(JSON.stringify(rest))).toThrow(TelemetryDecodeError)
  })

  it('rejects a non-integer timestamp', () => {
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), ts_us: 'yesterday' }))).toThrow(
      TelemetryDecodeError
    )
  })

  it('rejects a boolean masquerading as a timestamp', () => {
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), ts_us: true }))).toThrow(
      TelemetryDecodeError
    )
  })

  it('rejects too many signals', () => {
    const values = Object.fromEntries(
      Array.from({ length: MAX_SIGNALS_PER_PACKET + 1 }, (_, i) => [`s${i}`, 1])
    )
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), values, units: {} }))).toThrow(
      TelemetryDecodeError
    )
  })

  it('rejects an empty signal map', () => {
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), values: {}, units: {} }))).toThrow(
      TelemetryDecodeError
    )
  })

  it('rejects units naming a signal the packet does not carry', () => {
    const hostile = { ...wire(), values: { x: 1 }, units: { nonexistent: 'm/s' } }
    expect(() => decodePacketJson(JSON.stringify(hostile))).toThrow(TelemetryDecodeError)
  })

  it('rejects an empty device_id', () => {
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), device_id: '' }))).toThrow(
      TelemetryDecodeError
    )
  })

  it('rejects a negative seq', () => {
    expect(() => decodePacketJson(JSON.stringify({ ...wire(), seq: -1 }))).toThrow(
      TelemetryDecodeError
    )
  })
})
