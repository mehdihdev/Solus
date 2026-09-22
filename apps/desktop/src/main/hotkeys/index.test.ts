import { describe, expect, it, vi } from 'vitest'
import { startHotkeys, type HotkeyDeps, type HotkeyStatus, type Rect } from './index'
import { ACCELERATORS } from './globalHotkeys'
import type { KeyHook, KeyHookLoad } from './keyHook'
import { staticCapabilities } from '../platform/capabilities'

const DISPLAY = { id: 7, bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 2 }

interface Harness {
  deps: HotkeyDeps
  hook: { down(): void; up(): void; other(): void } | null
  cursor: { x: number; y: number }
  advance(ms: number): void
  fire(acc: string): void
  onSummon: ReturnType<typeof vi.fn>
  onToggleMode: ReturnType<typeof vi.fn>
  onRegion: ReturnType<typeof vi.fn>
  onStatus: ReturnType<typeof vi.fn>
}

function harness(opts: { hook: boolean; wayland?: boolean }): Harness {
  let t = 0
  const timers = new Map<number, { cb: () => void; ms: number; due: number }>()
  let nextId = 1
  const shortcuts = new Map<string, () => void>()
  const cursor = { x: 100, y: 100 }
  const noop = (): void => undefined
  const cbs: Record<'down' | 'up' | 'other', () => void> = { down: noop, up: noop, other: noop }
  const fakeHook: KeyHook = {
    onCtrlDown: (cb) => (cbs.down = cb),
    onCtrlUp: (cb) => (cbs.up = cb),
    onOtherKeyDown: (cb) => (cbs.other = cb),
    stop: vi.fn()
  }
  const loadHook = (): KeyHookLoad =>
    opts.hook
      ? { hook: fakeHook, state: { status: 'available', message: '' } }
      : { hook: null, state: { status: 'unavailable', message: 'no hook here' } }
  const h: Harness = {
    cursor,
    hook: opts.hook
      ? { down: () => cbs.down(), up: () => cbs.up(), other: () => cbs.other() }
      : null,
    onSummon: vi.fn(),
    onToggleMode: vi.fn(),
    onRegion: vi.fn(),
    onStatus: vi.fn(),
    fire: (acc) => shortcuts.get(acc)?.(),
    advance(ms) {
      const end = t + ms
      // run interval timers in due order until `end`
      for (;;) {
        const next = [...timers.entries()].sort((a, b) => a[1].due - b[1].due)[0]
        if (!next || next[1].due > end) break
        t = next[1].due
        next[1].due += next[1].ms
        next[1].cb()
      }
      t = end
    },
    deps: {
      capabilities: staticCapabilities({
        platform: 'linux',
        arch: 'x64',
        session: opts.wayland ? 'wayland' : 'x11'
      }),
      globalShortcut: {
        register: (acc, cb) => {
          shortcuts.set(acc, cb)
          return true
        },
        unregister: (acc) => void shortcuts.delete(acc),
        unregisterAll: () => shortcuts.clear()
      },
      getCursor: () => ({ ...cursor }),
      displayFor: () => DISPLAY,
      now: () => t,
      scheduler: {
        setInterval: (cb, ms) => {
          const id = nextId++
          timers.set(id, { cb, ms, due: t + ms })
          return id
        },
        clearInterval: (id) => void timers.delete(id as number)
      },
      loadHook,
      onSummon: () => h.onSummon(),
      onToggleMode: () => h.onToggleMode(),
      onRegion: (region, display) => h.onRegion(region, display),
      onStatus: (status) => h.onStatus(status)
    }
  }
  return h
}

/** Move the cursor around a circle over `ms` milliseconds while timers run. */
function drawCircle(h: Harness, cx: number, cy: number, r: number, ms = 600): void {
  const steps = 36
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI
    h.cursor.x = cx + r * Math.cos(a)
    h.cursor.y = cy + r * Math.sin(a)
    h.advance(ms / steps)
  }
}

describe('startHotkeys (docs/architecture/sol-window.md §2-§5, wireflow §A-§B)', () => {
  registerNativeGestureTests()
  registerFallbackCircleTests()
  registerHotkeyStatusAndTeardownTests()
})

function registerNativeGestureTests(): void {
  it('hook mode: a double-tap summons', () => {
    const h = harness({ hook: true })
    const handle = startHotkeys(h.deps)
    h.hook!.down()
    h.advance(60)
    h.hook!.up()
    h.advance(100)
    h.hook!.down()
    h.advance(60)
    h.hook!.up()
    expect(h.onSummon).toHaveBeenCalledTimes(1)
    expect(handle.status().mode).toBe('hook')
    expect(handle.status().summary).toContain('Ctrl+Shift+Space — open SOL')
    handle.stop()
  })

  it('hook mode: Ctrl+C in another app passes through untouched', () => {
    const h = harness({ hook: true })
    startHotkeys(h.deps)
    h.hook!.down()
    h.advance(20)
    h.hook!.other()
    h.advance(20)
    h.hook!.up()
    expect(h.onSummon).not.toHaveBeenCalled()
    expect(h.onRegion).not.toHaveBeenCalled()
  })

  it('hook mode: hold Ctrl and circle → onRegion with the 12 % margin on the display under the loop', () => {
    const h = harness({ hook: true })
    startHotkeys(h.deps)
    h.cursor.x = 600
    h.cursor.y = 400
    h.hook!.down()
    drawCircle(h, 500, 400, 100)
    h.hook!.up()
    expect(h.onRegion).toHaveBeenCalledTimes(1)
    const [region, display] = h.onRegion.mock.calls[0] as [Rect, typeof DISPLAY]
    expect(display).toBe(DISPLAY)
    expect(region.x).toBeCloseTo(376, -1)
    expect(region.width).toBeCloseTo(248, -1)
    expect(h.onSummon).not.toHaveBeenCalled()
  })

  it('hook mode: a straight drag does nothing', () => {
    const h = harness({ hook: true })
    startHotkeys(h.deps)
    h.hook!.down()
    for (let i = 0; i < 30; i++) {
      h.cursor.x += 15
      h.advance(16)
    }
    h.hook!.up()
    expect(h.onRegion).not.toHaveBeenCalled()
  })
}

function registerFallbackCircleTests(): void {
  it('fallback: Ctrl+Shift+C, then a circle, reaches onRegion after the cursor pauses', () => {
    const h = harness({ hook: false })
    const handle = startHotkeys(h.deps)
    expect(handle.status().mode).toBe('fallback')
    expect(handle.status().shortcuts).toEqual({
      ctrlSpace: true,
      spawnFallback: true,
      circleMode: true
    })
    h.fire(ACCELERATORS.circleMode)
    expect(handle.status().circleModeActive).toBe(true)
    drawCircle(h, 500, 400, 100)
    expect(h.onRegion).not.toHaveBeenCalled()
    h.advance(320) // the pause
    expect(h.onRegion).toHaveBeenCalledTimes(1)
    expect(handle.status().circleModeActive).toBe(false)
    h.fire(ACCELERATORS.summonFallback)
    expect(h.onSummon).toHaveBeenCalledTimes(1)
    h.fire(ACCELERATORS.toggleMode)
    expect(h.onToggleMode).toHaveBeenCalledTimes(1)
  })

  it('fallback: a hesitation mid-loop keeps the stroke (live gate 2026-09-07: a 300 ms stall must not split a circle)', () => {
    const h = harness({ hook: false })
    const handle = startHotkeys(h.deps)
    h.fire(ACCELERATORS.circleMode)
    const half = (from: number, to: number): void => {
      for (let i = 0; i <= 18; i++) {
        const a = from + ((to - from) * i) / 18
        h.cursor.x = 500 + 100 * Math.cos(a)
        h.cursor.y = 400 + 100 * Math.sin(a)
        h.advance(16)
      }
    }
    half(0, Math.PI)
    h.advance(400) // the hand stalls: an evaluation runs on the half loop and fails
    expect(h.onRegion).not.toHaveBeenCalled()
    expect(handle.status().circleModeActive).toBe(true)
    half(Math.PI, 2 * Math.PI)
    h.advance(320)
    expect(h.onRegion).toHaveBeenCalledTimes(1)
    expect(handle.status().circleModeActive).toBe(false)
  })

  it('fallback: circle mode times out after 10 s without a loop and never polls afterwards', () => {
    const h = harness({ hook: false })
    const handle = startHotkeys(h.deps)
    const getCursor = vi.fn(h.deps.getCursor)
    h.deps.getCursor = getCursor
    h.fire(ACCELERATORS.circleMode)
    h.advance(10_100)
    expect(handle.status().circleModeActive).toBe(false)
    const polls = getCursor.mock.calls.length
    h.advance(1_000)
    expect(getCursor.mock.calls.length).toBe(polls)
    expect(h.onRegion).not.toHaveBeenCalled()
  })
}

function registerHotkeyStatusAndTeardownTests(): void {
  it('status summaries: fallback names the chord; circle mode names the gesture; onStatus fires on change', () => {
    const h = harness({ hook: false })
    const handle = startHotkeys(h.deps)
    expect(handle.status().summary).toContain('Ctrl+Shift+Space — open SOL')
    expect(handle.status().hook.message).toBe('no hook here')
    const first = h.onStatus.mock.calls.length
    handle.enterCircleMode()
    expect(handle.status().summary).toBe('Circle mode — draw a loop')
    expect(h.onStatus.mock.calls.length).toBeGreaterThan(first)
    const last = h.onStatus.mock.calls.at(-1)?.[0] as HotkeyStatus
    expect(last.circleModeActive).toBe(true)
  })

  it('Wayland: attempts the portal shortcut and dispatches summon', () => {
    const h = harness({ hook: false, wayland: true })
    const handle = startHotkeys(h.deps)
    expect(handle.status().shortcuts).toEqual({
      ctrlSpace: true,
      spawnFallback: true,
      circleMode: true
    })
    h.fire(ACCELERATORS.summonFallback)
    expect(h.onSummon).toHaveBeenCalledTimes(1)
  })

  it('a taken Ctrl+Space shows in the summary', () => {
    const h = harness({ hook: true })
    const real = h.deps.globalShortcut.register
    h.deps.globalShortcut.register = (acc, cb) => acc !== ACCELERATORS.toggleMode && real(acc, cb)
    const handle = startHotkeys(h.deps)
    expect(handle.status().shortcuts.ctrlSpace).toBe(false)
    expect(handle.status().summary).toMatch(/Ctrl\+Space is unavailable; use Open SOL window/)
  })

  it('stop() releases the hook, the shortcuts and the sampler', () => {
    const h = harness({ hook: true })
    const handle = startHotkeys(h.deps)
    const getCursor = vi.fn(h.deps.getCursor)
    h.deps.getCursor = getCursor
    h.hook!.down() // reads the cursor once for p0
    handle.stop()
    const polls = getCursor.mock.calls.length
    h.advance(100)
    expect(getCursor.mock.calls.length).toBe(polls)
    h.fire(ACCELERATORS.toggleMode)
    expect(h.onToggleMode).not.toHaveBeenCalled()
  })
}
