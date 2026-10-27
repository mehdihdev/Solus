// SOLUSDEV-319 drive slice 3 (sol-drive.md §3 "Outline geometry"): the
// companion's stdout carries `drive_window` lines; everything else, and
// anything malformed or oversized, is ignored silently.
import { describe, expect, it, vi } from 'vitest'
import {
  createCompanionStdoutReader,
  parseDriveSessionNeeded,
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

describe('parseDriveSessionNeeded', () => {
  it('accepts exactly {"type":"drive_session_needed"}', () => {
    expect(parseDriveSessionNeeded('{"type":"drive_session_needed"}')).toBe(true)
  })

  it.each([
    ['an extra key', '{"type":"drive_session_needed","socket":"/tmp/evil.sock"}'],
    ['another type', '{"type":"drive_window"}'],
    ['not JSON', 'drive_session_needed'],
    ['an array', '["drive_session_needed"]']
  ])('false for %s', (_label, raw) => {
    expect(parseDriveSessionNeeded(raw)).toBe(false)
  })
})

describe('createCompanionStdoutReader', () => {
  it('routes valid bounds and session requests; ignores everything else', () => {
    const onBounds = vi.fn()
    const onSessionNeeded = vi.fn()
    const reader = createCompanionStdoutReader({ onBounds, onSessionNeeded })
    reader.push(Buffer.from('noise\n{"type":"drive_window","bounds":{"x":1,"y":2,'))
    reader.push(Buffer.from('"width":3,"height":4}}\n{"type":"other"}\n'))
    reader.push(Buffer.from('{"type":"drive_session_needed"}\n'))
    expect(onBounds.mock.calls).toEqual([[{ x: 1, y: 2, width: 3, height: 4 }]])
    expect(onSessionNeeded).toHaveBeenCalledTimes(1)
  })
})
