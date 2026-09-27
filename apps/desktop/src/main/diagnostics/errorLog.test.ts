// SOLUSDEV-311: every caught error reaches stdout (the dev terminal) AND a
// size-capped JSON-lines file (so packaged builds leave evidence). The log
// itself must never throw — a failing disk cannot become a second crash.
import { describe, it, expect } from 'vitest'
import { createErrorLog, type ErrorLogDeps, type ErrorLogEntry } from './errorLog'

const ENTRY: ErrorLogEntry = {
  at: '2026-09-26T10:00:00.000Z',
  origin: 'render',
  surface: 'bench',
  fingerprint: '0123456789abcdef',
  name: 'TypeError',
  message: 'boom',
  stack: 'TypeError: boom\n    at BenchScreen'
}

function fakeDeps(): ErrorLogDeps & { files: Map<string, string>; out: string[] } {
  const files = new Map<string, string>()
  const out: string[] = []
  return {
    files,
    out,
    append: (path, text) => files.set(path, (files.get(path) ?? '') + text),
    size: (path) => (files.has(path) ? Buffer.byteLength(files.get(path)!) : null),
    rename: (from, to) => {
      files.set(to, files.get(from) ?? '')
      files.delete(from)
    },
    stderr: (line) => out.push(line)
  }
}

describe('createErrorLog', () => {
  it('writes a readable line to stderr and one JSON line to the file', () => {
    const deps = fakeDeps()
    createErrorLog({ path: '/logs/e.log', maxBytes: 10_000, deps }).write(ENTRY)
    expect(deps.out.join('\n')).toContain(
      '[solus:error] render bench TypeError: boom (0123456789abcdef)'
    )
    expect(deps.out.join('\n')).toContain('at BenchScreen')
    const lines = deps.files.get('/logs/e.log')!.trim().split('\n')
    expect(lines).toHaveLength(1)
    expect(JSON.parse(lines[0])).toEqual(ENTRY)
  })

  it('neutralises control characters and forged lines on the console', () => {
    const deps = fakeDeps()
    createErrorLog({ path: '/logs/e.log', maxBytes: 10_000, deps }).write({
      ...ENTRY,
      name: 'Type\u001b[31mError',
      message: 'boom\n[solus:error] render root Error: forged (ffffffffffffffff)',
      stack: 'TypeError: boom\n[solus:error] forged too\u0007'
    })
    const out = deps.out.join('\n')
    // eslint-disable-next-line no-control-regex -- asserting control characters are gone
    expect(out).not.toMatch(/[\u0000-\u0008\u000b-\u001f\u007f]/)
    expect(out.split('\n').filter((line) => line.startsWith('[solus:error]'))).toHaveLength(1)
  })

  it('rotates to .1 when the next line would exceed the cap', () => {
    const deps = fakeDeps()
    const log = createErrorLog({ path: '/logs/e.log', maxBytes: 300, deps })
    log.write(ENTRY)
    log.write(ENTRY)
    expect(deps.files.has('/logs/e.log.1')).toBe(true)
    expect(deps.files.get('/logs/e.log')!.trim().split('\n')).toHaveLength(1)
  })

  it('never throws when the disk fails, and says so on stderr', () => {
    const deps = fakeDeps()
    deps.append = () => {
      throw new Error('EACCES')
    }
    expect(() => createErrorLog({ path: '/x', maxBytes: 100, deps }).write(ENTRY)).not.toThrow()
    expect(deps.out.some((l) => l.includes('could not write error log'))).toBe(true)
  })
})
