// SOLUSDEV-319 drive slice 3 (sol-drive.md §3 "Outline geometry"): the
// companion's stdout carries `drive_window` lines; everything else, and
// anything malformed or oversized, is ignored silently.
import { describe, expect, it, vi } from 'vitest'
import {
  createCompanionStdoutReader,
  parseDriveCancel,
  parseDriveRequest,
  createLineSplitter,
  MAX_STDOUT_LINE_BYTES,
  parseDriveWindowLine
} from './driveWindow'

const line = (bounds: unknown, type = 'drive_window'): string => JSON.stringify({ type, bounds })

describe('parseDriveWindowLine', () => {
  it('accepts a drive_window line with finite numbers', () => {
    expect(parseDriveWindowLine(line({ x: -10.5, y: 20, width: 800, height: 600 }))).toEqual({
      x: -10.5,
      y: 20,
      width: 800,
      height: 600
    })
  })

  it('keeps only the four numbers (no title, bundle id or path can ride along)', () => {
    const raw = JSON.stringify({
      type: 'drive_window',
      bounds: { x: 0, y: 0, width: 1, height: 1, title: 'secret.kicad_sch' },
      path: '/x'
    })
    expect(parseDriveWindowLine(raw)).toEqual({ x: 0, y: 0, width: 1, height: 1 })
  })

  it.each([
    ['another type', line({ x: 0, y: 0, width: 1, height: 1 }, 'log')],
    ['not JSON', 'Traceback (most recent call last):'],
    ['no bounds', JSON.stringify({ type: 'drive_window' })],
    ['a string number', line({ x: '0', y: 0, width: 1, height: 1 })],
    ['NaN-ish', '{"type":"drive_window","bounds":{"x":1e999,"y":0,"width":1,"height":1}}'],
    ['zero width', line({ x: 0, y: 0, width: 0, height: 1 })],
    ['negative height', line({ x: 0, y: 0, width: 1, height: -1 })],
    ['an absurd size', line({ x: 0, y: 0, width: 1e6, height: 1 })],
    ['an absurd origin', line({ x: 1e7, y: 0, width: 1, height: 1 })],
    ['an array', '[1,2]']
  ])('null for %s', (_label, raw) => {
    expect(parseDriveWindowLine(raw)).toBeNull()
  })
})

describe('createLineSplitter', () => {
  it('splits on newlines across chunk boundaries', () => {
    const onLine = vi.fn()
    const split = createLineSplitter(onLine)
    split.push(Buffer.from('ab'))
    split.push(Buffer.from('c\nde\n\nf'))
    split.push(Buffer.from('\n'))
    expect(onLine.mock.calls.map((c) => c[0])).toEqual(['abc', 'de', 'f'])
  })

  it('drops an oversized line whole, then resumes at the next newline', () => {
    const onLine = vi.fn()
    const split = createLineSplitter(onLine)
    split.push(Buffer.from('x'.repeat(MAX_STDOUT_LINE_BYTES)))
    split.push(Buffer.from('yyyy'))
    split.push(Buffer.from('tail\nok\n'))
    expect(onLine.mock.calls.map((c) => c[0])).toEqual(['ok'])
  })

  it('drops a single oversized line that arrives in one chunk', () => {
    const onLine = vi.fn()
    createLineSplitter(onLine).push(Buffer.from(`${'z'.repeat(MAX_STDOUT_LINE_BYTES + 1)}\nok\n`))
    expect(onLine.mock.calls.map((c) => c[0])).toEqual(['ok'])
  })
})

// Slice 3b, XPC (sol-drive.md §3 helper.py relay): the companion asks main to
// run a helper command; only these exact shapes are accepted.
describe('parseDriveRequest', () => {
  const ok = { type: 'drive_request', id: 7, argv: ['identify', '--within', '/w'] }

  it('accepts {type, id, argv} exactly', () => {
    expect(parseDriveRequest(JSON.stringify(ok))).toEqual({ id: 7, argv: ok.argv })
  })

  it.each([
    ['an extra key', { ...ok, socket: '/x' }],
    ['a zero id', { ...ok, id: 0 }],
    ['a fractional id', { ...ok, id: 1.5 }],
    ['a string id', { ...ok, id: '7' }],
    ['an empty argv', { ...ok, argv: [] }],
    ['a non-string arg', { ...ok, argv: ['act', 3] }],
    ['a NUL in an arg', { ...ok, argv: ['act', 'a\u0000b'] }],
    ['65 args', { ...ok, argv: Array.from({ length: 65 }, () => 'x') }],
    ['another type', { ...ok, type: 'drive_reply' }]
  ])('null for %s', (_label, value) => {
    expect(parseDriveRequest(JSON.stringify(value))).toBeNull()
  })

  it('accepts 64 args', () => {
    const argv = Array.from({ length: 64 }, () => 'x')
    expect(parseDriveRequest(JSON.stringify({ ...ok, argv }))?.argv).toHaveLength(64)
  })
})

describe('parseDriveCancel', () => {
  it('accepts {type, id} exactly', () => {
    expect(parseDriveCancel('{"type":"drive_cancel","id":3}')).toBe(3)
  })
  it.each([
    ['{"type":"drive_cancel","id":3,"x":1}'],
    ['{"type":"drive_cancel","id":-1}'],
    ['{"type":"drive_cancel"}']
  ])('null for %s', (raw) => {
    expect(parseDriveCancel(raw)).toBeNull()
  })
})

describe('createCompanionStdoutReader', () => {
  it('routes bounds, requests and cancels; ignores everything else', () => {
    const onBounds = vi.fn()
    const onRequest = vi.fn()
    const onCancel = vi.fn()
    const reader = createCompanionStdoutReader({ onBounds, onRequest, onCancel })
    reader.push(Buffer.from('noise\n{"type":"drive_window","bounds":{"x":1,"y":2,'))
    reader.push(Buffer.from('"width":3,"height":4}}\n{"type":"other"}\n'))
    reader.push(Buffer.from('{"type":"drive_request","id":1,"argv":["capture"]}\n'))
    reader.push(Buffer.from('{"type":"drive_cancel","id":1}\n'))
    reader.push(Buffer.from('{"type":"drive_session_needed"}\n')) // retired: ignored
    expect(onBounds.mock.calls).toEqual([[{ x: 1, y: 2, width: 3, height: 4 }]])
    expect(onRequest.mock.calls).toEqual([[{ id: 1, argv: ['capture'] }]])
    expect(onCancel.mock.calls).toEqual([[1]])
  })

  it('a drive_request line up to the 64 KiB cap gets through', () => {
    expect(MAX_STDOUT_LINE_BYTES).toBe(64 * 1024)
    const onRequest = vi.fn()
    const reader = createCompanionStdoutReader({ onBounds: vi.fn(), onRequest, onCancel: vi.fn() })
    const big = 'y'.repeat(30 * 1024)
    reader.push(
      Buffer.from(`${JSON.stringify({ type: 'drive_request', id: 2, argv: ['act', big] })}\n`)
    )
    expect(onRequest).toHaveBeenCalledTimes(1)
  })
})
