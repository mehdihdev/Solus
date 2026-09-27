// SOLUSDEV-311: the crash marker carries a prior session's crash to the next
// renderer (once) and remembers the last relaunch so a crash-on-boot cannot
// relaunch forever. Its file is read defensively — garbage reads as empty.
import { describe, it, expect } from 'vitest'
import { createCrashMarker, RELAUNCH_WINDOW_MS } from './crashMarker'
import type { PendingCrash } from './diagnostics.constants'

const CRASH: PendingCrash = {
  origin: 'main_process',
  surface: 'main',
  errorName: 'TypeError',
  fingerprint: '0123456789abcdef',
  appVersion: '1.0.0'
}

function fakeFs(initial?: string): {
  read: () => string | null
  write: (t: string) => void
  text: () => string | null
} {
  let text: string | null = initial ?? null
  return { read: () => text, write: (t) => (text = t), text: () => text }
}

const marker = (fs: ReturnType<typeof fakeFs>): ReturnType<typeof createCrashMarker> =>
  createCrashMarker({ read: fs.read, write: fs.write })

describe('createCrashMarker', () => {
  it('hands a recorded crash to exactly one take()', () => {
    const fs = fakeFs()
    marker(fs).record(CRASH)
    const next = marker(fs)
    expect(next.take()).toEqual(CRASH)
    expect(next.take()).toBeNull()
  })

  it('allows one relaunch, then refuses another inside the window', () => {
    const fs = fakeFs()
    const m = marker(fs)
    expect(m.mayRelaunch(1_000)).toBe(true)
    m.markRelaunch(1_000)
    expect(marker(fs).mayRelaunch(1_000 + RELAUNCH_WINDOW_MS - 1)).toBe(false)
    expect(marker(fs).mayRelaunch(1_000 + RELAUNCH_WINDOW_MS + 1)).toBe(true)
  })

  it('keeps the relaunch history when the pending crash is taken', () => {
    const fs = fakeFs()
    const m = marker(fs)
    m.record(CRASH)
    m.markRelaunch(5_000)
    m.take()
    expect(marker(fs).mayRelaunch(5_001)).toBe(false)
  })

  it.each([
    ['not JSON', '{nope'],
    ['a wrong shape', JSON.stringify({ pending: { origin: 'evil' }, lastRelaunchAt: 'x' })],
    ['an array', '[]']
  ])('reads %s as empty', (_label, text) => {
    const m = marker(fakeFs(text))
    expect(m.take()).toBeNull()
    expect(m.mayRelaunch(0)).toBe(true)
  })

  it('markRelaunch reports whether the guard was persisted', () => {
    expect(marker(fakeFs()).markRelaunch(1)).toBe(true)
    const readOnly = createCrashMarker({
      read: () => null,
      write: () => {
        throw new Error('EROFS')
      }
    })
    expect(readOnly.markRelaunch(1)).toBe(false)
  })

  it('never throws when the disk fails', () => {
    const m = createCrashMarker({
      read: () => {
        throw new Error('EIO')
      },
      write: () => {
        throw new Error('EIO')
      }
    })
    expect(() => m.record(CRASH)).not.toThrow()
    expect(m.take()).toBeNull()
  })
})
