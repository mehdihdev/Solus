// SOLUSDEV-329 — the `solus-companion runtime` JSON Lines parser
// (docs/architecture/mcp-fork-runtime.md §6), driven by the SAME golden
// fixtures the companion's emitter tests against.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  RUNTIME_LINE_MAX_BYTES,
  createRuntimeLineReader,
  parseRuntimeLine,
  type RuntimeEvent
} from './protocol'

const FIXTURES = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../../packages/companion/tests/fixtures/mcp_runtime'
)

function readFixture(name: string): { events: RuntimeEvent[]; dropped: number } {
  const events: RuntimeEvent[] = []
  const reader = createRuntimeLineReader({ onEvent: (e) => events.push(e) })
  const bytes = readFileSync(resolve(FIXTURES, name))
  // Split into odd-sized chunks so line reassembly across chunks is exercised.
  for (let i = 0; i < bytes.length; i += 97) reader.push(bytes.subarray(i, i + 97))
  reader.end()
  return { events, dropped: reader.stats().dropped }
}

const types = (events: RuntimeEvent[]): string[] => events.map((e) => e.type)

describe('golden fixtures', () => {
  it('detect_ok: 4 candidates (2 supported), done ok', () => {
    const { events, dropped } = readFixture('detect_ok.jsonl')
    expect(dropped).toBe(0)
    expect(types(events)).toEqual(['candidate', 'candidate', 'candidate', 'candidate', 'done'])
    expect(events[0]).toEqual({
      type: 'candidate',
      path: '/opt/homebrew/bin/python3.12',
      version: '3.12.7',
      implementation: 'cpython',
      source: 'known_location',
      supported: true,
      reason: null
    })
    const supported = events.filter((e) => e.type === 'candidate' && e.supported)
    expect(supported).toHaveLength(2)
    expect(events[4]).toEqual({ type: 'done', outcome: 'ok', ok: 2, failed: 0, skipped: 2 })
  })

  it('detect_none: store alias refused, error python_not_found, done failed', () => {
    const { events, dropped } = readFixture('detect_none.jsonl')
    expect(dropped).toBe(0)
    expect(types(events)).toEqual(['candidate', 'error', 'done'])
    expect(events[0]).toMatchObject({ supported: false, reason: 'python_store_alias' })
    expect(events[1]).toMatchObject({ error_code: 'python_not_found' })
    expect(events[2]).toMatchObject({ outcome: 'failed' })
  })

  it('provision_ok: kicad + code ok, altium skipped, done ok', () => {
    const { events, dropped } = readFixture('provision_ok.jsonl')
    expect(dropped).toBe(0)
    const results = events.filter((e) => e.type === 'fork_result')
    expect(results.map((r) => [r.fork, r.outcome])).toEqual([
      ['kicad', 'ok'],
      ['code', 'ok'],
      ['altium', 'skipped']
    ])
    expect(events.at(-1)).toEqual({ type: 'done', outcome: 'ok', ok: 2, failed: 0, skipped: 1 })
    expect(events[0]).toEqual({
      type: 'progress',
      fork: 'kicad',
      step: 'venv',
      done: 0,
      total: null
    })
  })

  it('provision_partial: local failed venv_copies_unhealthy, done partial', () => {
    const { events } = readFixture('provision_partial.jsonl')
    const failed = events.find((e) => e.type === 'fork_result' && e.outcome === 'failed')
    expect(failed).toMatchObject({ fork: 'local', error_code: 'venv_copies_unhealthy' })
    expect(events.at(-1)).toMatchObject({ type: 'done', outcome: 'partial', ok: 1, failed: 1 })
  })

  it('provision_network_error: both failed network_unreachable, error, done failed', () => {
    const { events } = readFixture('provision_network_error.jsonl')
    expect(types(events)).toEqual(['progress', 'fork_result', 'fork_result', 'error', 'done'])
    expect(events[3]).toMatchObject({ error_code: 'network_unreachable' })
  })

  it('malformed: 5 lines dropped, then 1 status + 1 done kept', () => {
    const { events, dropped } = readFixture('malformed.jsonl')
    expect(dropped).toBe(5)
    expect(types(events)).toEqual(['status', 'done'])
    expect(events[0]).toEqual({
      type: 'status',
      fork: 'kicad',
      state: 'ready',
      detail: null,
      base_version: '3.12.7',
      managed: false
    })
  })
})

describe('parseRuntimeLine', () => {
  const ok = (o: Record<string, unknown>): string => JSON.stringify({ v: 1, ...o })

  it('strips v and keeps only the documented fields', () => {
    expect(
      parseRuntimeLine(ok({ type: 'error', error_code: 'internal', message: 'x', extra: 1 }))
    ).toEqual({ type: 'error', error_code: 'internal', message: 'x' })
  })

  it.each([
    ['unknown error code', { type: 'error', error_code: 'rm -rf', message: 'x' }],
    ['message over 300 chars', { type: 'error', error_code: 'internal', message: 'x'.repeat(301) }],
    [
      'relative candidate path',
      {
        type: 'candidate',
        path: 'python3',
        version: null,
        implementation: 'cpython',
        source: 'path',
        supported: false,
        reason: null
      }
    ],
    [
      'bad fork name',
      { type: 'fork_result', fork: '../x', outcome: 'ok', error_code: null, message: '' }
    ],
    [
      'negative progress',
      { type: 'progress', fork: null, step: 'download', done: -1, total: null }
    ],
    ['fractional count', { type: 'done', outcome: 'ok', ok: 1.5, failed: 0, skipped: 0 }],
    [
      'bad state',
      {
        type: 'status',
        fork: 'kicad',
        state: 'great',
        detail: null,
        base_version: null,
        managed: false
      }
    ],
    ['missing field', { type: 'done', outcome: 'ok', ok: 1, failed: 0 }],
    [
      'detail with a path',
      {
        type: 'status',
        fork: 'kicad',
        state: 'needs_setup',
        detail: '/etc/passwd',
        base_version: null,
        managed: false
      }
    ]
  ])('drops %s', (_label, body) => {
    expect(parseRuntimeLine(ok(body))).toBeNull()
  })

  it('accepts §5 detail codes and a global progress step', () => {
    expect(
      parseRuntimeLine(
        ok({
          type: 'status',
          fork: 'code',
          state: 'needs_setup',
          detail: 'needs_setup:no_env',
          base_version: null,
          managed: false
        })
      )
    ).toMatchObject({ detail: 'needs_setup:no_env' })
    expect(
      parseRuntimeLine(ok({ type: 'progress', fork: null, step: 'download', done: 10, total: 100 }))
    ).toMatchObject({ fork: null, step: 'download' })
  })

  it('drops non-object JSON', () => {
    expect(parseRuntimeLine('[1]')).toBeNull()
    expect(parseRuntimeLine('null')).toBeNull()
  })
})

describe('createRuntimeLineReader', () => {
  it('drops a line over the byte cap even when it arrives in pieces', () => {
    const events: RuntimeEvent[] = []
    const reader = createRuntimeLineReader({ onEvent: (e) => events.push(e) })
    const huge = `{"v":1,"type":"error","error_code":"internal","message":"${'y'.repeat(RUNTIME_LINE_MAX_BYTES)}"}\n`
    for (let i = 0; i < huge.length; i += 500) reader.push(Buffer.from(huge.slice(i, i + 500)))
    reader.push(Buffer.from('{"v":1,"type":"done","outcome":"ok","ok":0,"failed":0,"skipped":0}\n'))
    expect(types(events)).toEqual(['done'])
    expect(reader.stats().dropped).toBe(1)
  })

  it('treats a final unterminated line as a line at end()', () => {
    const events: RuntimeEvent[] = []
    const reader = createRuntimeLineReader({ onEvent: (e) => events.push(e) })
    reader.push(Buffer.from('{"v":1,"type":"done","outcome":"ok","ok":0,"failed":0,"skipped":0}'))
    expect(events).toHaveLength(0)
    reader.end()
    expect(events).toHaveLength(1)
  })

  it('stops reading and reports overflow past the total cap', () => {
    const events: RuntimeEvent[] = []
    let overflowed = 0
    const reader = createRuntimeLineReader({
      onEvent: (e) => events.push(e),
      maxTotalBytes: 200,
      onOverflow: () => overflowed++
    })
    const line = '{"v":1,"type":"done","outcome":"ok","ok":0,"failed":0,"skipped":0}\n'
    for (let i = 0; i < 10; i++) reader.push(Buffer.from(line))
    expect(events.length).toBeLessThan(4)
    expect(overflowed).toBe(1)
    expect(reader.stats().overflow).toBe(true)
  })

  it('never throws on garbage bytes', () => {
    const reader = createRuntimeLineReader({ onEvent: () => undefined })
    expect(() => reader.push(Buffer.from([0xff, 0xfe, 0x0a, 0x00, 0x0a]))).not.toThrow()
    expect(reader.stats().dropped).toBe(2)
  })
})

describe('python_is_venv (SOLUSDEV-329 Phase 4)', () => {
  it('accepts python_is_venv as a candidate reason and an error code', () => {
    const candidate = parseRuntimeLine(
      JSON.stringify({
        v: 1,
        type: 'candidate',
        path: '/home/dev/.venv/bin/python3.12',
        version: '3.12.7',
        implementation: 'cpython',
        source: 'path',
        supported: false,
        reason: 'python_is_venv'
      })
    )
    expect(candidate).toMatchObject({ reason: 'python_is_venv' })
    const error = parseRuntimeLine(
      JSON.stringify({ v: 1, type: 'error', error_code: 'python_is_venv', message: 'venv' })
    )
    expect(error).toMatchObject({ error_code: 'python_is_venv' })
  })
})
