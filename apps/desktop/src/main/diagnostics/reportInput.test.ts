// SOLUSDEV-311: `diag:report` input is untrusted (any app window's renderer can
// send it) — malformed shapes are refused, oversize fields are truncated.
import { describe, it, expect } from 'vitest'
import { parseRendererReport } from './reportInput'

const VALID = {
  origin: 'render',
  surface: 'bench',
  name: 'TypeError',
  message: 'boom',
  stack: 'TypeError: boom\n    at BenchScreen (bench.tsx:10:5)',
  componentStack: '\n    at BenchScreen'
}

describe('parseRendererReport', () => {
  it('accepts a well-formed report', () => {
    expect(parseRendererReport(VALID)).toEqual(VALID)
  })

  it('accepts a report without the optional stacks', () => {
    const bare = { origin: VALID.origin, surface: VALID.surface, name: VALID.name, message: 'boom' }
    expect(parseRendererReport(bare)).toEqual(bare)
  })

  it.each([
    ['a non-object', 'boom'],
    ['null', null],
    ['an array', [VALID]],
    ['a crash origin (main-only)', { ...VALID, origin: 'main_process' }],
    ['an unknown surface', { ...VALID, surface: 'nowhere' }],
    ['a non-string message', { ...VALID, message: 42 }],
    ['a non-string stack', { ...VALID, stack: {} }],
    ['an extra key', { ...VALID, token: 'x' }]
  ])('refuses %s', (_label, raw) => {
    expect(parseRendererReport(raw)).toBeNull()
  })

  it('bounds oversize fields at the transport limits (final limits apply after scrubbing)', () => {
    const out = parseRendererReport({ ...VALID, name: 'N'.repeat(500), stack: 's'.repeat(50_000) })
    expect(out?.name).toHaveLength(256)
    expect(out?.stack).toHaveLength(32_000)
  })
})
