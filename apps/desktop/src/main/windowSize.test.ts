// SOLUSDEV-323: the signed-out window is compact and grows into onboarding /
// the workspace. Main owns the bounds; the renderer only names a size.
import { describe, expect, it, vi } from 'vitest'
import {
  COMPACT_SIZES,
  FULL_MIN,
  WindowSizer,
  centredRect,
  createRevealGate,
  createWindowSizeHandler,
  parseWindowSizeRequest,
  type Rect,
  type SizableWindow
} from './windowSize'

const WORK: Rect = { x: 0, y: 0, width: 1728, height: 1080 }

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type -- the vi.fn mocks are the type
function fakeWindow(bounds: Rect, visible = true) {
  let current = { ...bounds }
  const listeners: Record<string, (() => void) | undefined> = {}
  const win = {
    getBounds: vi.fn(() => ({ ...current })),
    setBounds: vi.fn((r: Rect, animate?: boolean) => {
      current = { ...r }
      return animate
    }),
    setMinimumSize: vi.fn(),
    setResizable: vi.fn(),
    setMaximizable: vi.fn(),
    setFullScreenable: vi.fn(),
    isMaximized: vi.fn(() => false),
    unmaximize: vi.fn(),
    isFullScreen: vi.fn(() => false),
    setFullScreen: vi.fn(() => {
      queueMicrotask(() => listeners['leave-full-screen']?.())
    }),
    isVisible: vi.fn(() => visible),
    isDestroyed: vi.fn(() => false),
    setBackgroundColor: vi.fn(),
    once: vi.fn((e: 'resized' | 'leave-full-screen', cb: () => void) => {
      listeners[e] = cb
    }),
    removeListener: vi.fn(),
    fireResized: () => listeners['resized']?.()
  }
  return win satisfies SizableWindow & { fireResized: () => void }
}

function sizer(win: SizableWindow, platform = 'darwin'): WindowSizer {
  return new WindowSizer(win, {
    platform,
    workArea: () => WORK,
    defaultFull: () => ({ width: 1440, height: 900 }),
    settleMs: 50
  })
}

describe('parseWindowSizeRequest', () => {
  it('accepts a known size with optional animate and a hex background', () => {
    expect(parseWindowSizeRequest({ size: 'starter' })).toEqual({ size: 'starter' })
    expect(parseWindowSizeRequest({ size: 'full', animate: false, background: '#0A0C0F' })).toEqual(
      { size: 'full', animate: false, background: '#0A0C0F' }
    )
  })

  it('rejects unknown sizes, non-objects and anything but a #rrggbb background', () => {
    expect(parseWindowSizeRequest({ size: 'huge' })).toBeNull()
    expect(parseWindowSizeRequest('starter')).toBeNull()
    expect(parseWindowSizeRequest(null)).toBeNull()
    expect(parseWindowSizeRequest({ size: 'auth', background: 'red; x' })).toEqual({
      size: 'auth'
    })
    expect(parseWindowSizeRequest({ size: 'auth', animate: 'yes' })).toEqual({ size: 'auth' })
  })
})

describe('centredRect', () => {
  it('keeps the centre of the current window', () => {
    const r = centredRect({ x: 100, y: 100, width: 1000, height: 800 }, COMPACT_SIZES.starter, WORK)
    expect(r.x + r.width / 2).toBe(600)
    expect(r.y + r.height / 2).toBe(500)
    expect(r).toMatchObject(COMPACT_SIZES.starter)
  })

  it('clamps into the work area', () => {
    const r = centredRect(
      { x: 1600, y: 1000, width: 100, height: 60 },
      { width: 1440, height: 900 },
      WORK
    )
    expect(r).toEqual({ x: 288, y: 180, width: 1440, height: 900 })
  })
})

describe('WindowSizer', () => {
  it('shrinks to the compact starter, locks resizing and animates on macOS', async () => {
    const win = fakeWindow({ x: 100, y: 90, width: 1440, height: 900 })
    const s = sizer(win)
    const done = s.apply({ size: 'starter', background: '#0A0C0F' })
    await Promise.resolve()
    win.fireResized()
    await done
    expect(win.setBackgroundColor).toHaveBeenCalledWith('#0A0C0F')
    expect(win.setMinimumSize).toHaveBeenCalledWith(460, 640)
    expect(win.setResizable).toHaveBeenCalledWith(false)
    expect(win.setMaximizable).toHaveBeenCalledWith(false)
    expect(win.setBounds).toHaveBeenCalledWith({ x: 590, y: 220, width: 460, height: 640 }, true)
    expect(s.size).toBe('starter')
  })

  it('grows back to the remembered full size and only then restores the minimum', async () => {
    const win = fakeWindow({ x: 100, y: 90, width: 1300, height: 820 })
    const s = sizer(win, 'win32') // no native animation: resolves at once
    await s.apply({ size: 'starter' })
    win.setMinimumSize.mockClear()
    await s.apply({ size: 'full' })
    const last = win.setBounds.mock.calls.at(-1)
    expect(last?.[0]).toMatchObject({ width: 1300, height: 820 })
    expect(last?.[1]).toBe(false)
    expect(win.setMinimumSize).toHaveBeenLastCalledWith(FULL_MIN.width, FULL_MIN.height)
    expect(win.setResizable).toHaveBeenLastCalledWith(true)
  })

  it('applies instantly while the window is hidden (first paint)', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 }, false)
    await sizer(win).apply({ size: 'starter' })
    expect(win.setBounds.mock.calls[0]?.[1]).toBe(false)
  })

  it('honours animate:false (reduced motion)', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    await sizer(win).apply({ size: 'auth', animate: false })
    expect(win.setBounds.mock.calls[0]?.[1]).toBe(false)
  })

  it('does nothing for the size it already has', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    await sizer(win).apply({ size: 'full' })
    expect(win.setBounds).not.toHaveBeenCalled()
  })

  it('settles on the timeout when macOS never reports resized', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    await sizer(win).apply({ size: 'starter' })
    expect(win.removeListener).toHaveBeenCalled()
  })

  it('runs requests one after another and never drops a grow', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    const s = sizer(win, 'linux')
    await s.apply({ size: 'starter' })
    await Promise.all([s.apply({ size: 'full' }), s.apply({ size: 'starter' })])
    expect(win.setBounds.mock.calls.map((c) => c[0].height)).toEqual([640, 900, 640])
    expect(s.size).toBe('starter')
  })

  it('leaves full screen before shrinking, then jumps to the starter', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1728, height: 1080 })
    win.isFullScreen.mockReturnValue(true)
    const s = sizer(win)
    await s.apply({ size: 'starter' })
    expect(win.setFullScreen).toHaveBeenCalledWith(false)
    expect(win.setBounds.mock.calls[0]?.[1]).toBe(false)
    expect(s.size).toBe('starter')
  })

  it('treats full screen as already full', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1728, height: 1080 })
    const s = sizer(win, 'linux')
    await s.apply({ size: 'starter' })
    win.isFullScreen.mockReturnValue(true)
    win.setBounds.mockClear()
    await s.apply({ size: 'full' })
    expect(win.setBounds).not.toHaveBeenCalled()
    expect(s.size).toBe('full')
  })

  it('keeps one compact minimum, so starter → auth never snaps before it animates', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    const s = sizer(win, 'linux')
    await s.apply({ size: 'starter' })
    await s.apply({ size: 'auth' })
    expect(win.setMinimumSize.mock.calls.every(([w, h]) => w === 460 && h === 640)).toBe(true)
  })

  it('never sets a minimum taller than the screen', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1366, height: 600 })
    await new WindowSizer(win, {
      platform: 'linux',
      workArea: () => ({ x: 0, y: 0, width: 1366, height: 600 }),
      defaultFull: () => ({ width: 1366, height: 600 })
    }).apply({ size: 'starter' })
    expect(win.setMinimumSize).toHaveBeenCalledWith(460, 600)
  })

  it('drops a compact request a newer one already replaced', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    const s = sizer(win, 'linux')
    await Promise.all([
      s.apply({ size: 'starter' }),
      s.apply({ size: 'auth' }),
      s.apply({ size: 'starter' })
    ])
    expect(win.setBounds.mock.calls.map((c) => c[0].height)).toEqual([640])
  })

  it('does not wait for a resize that cannot happen (already that size)', async () => {
    const win = fakeWindow({ x: 490, y: 220, width: 460, height: 640 })
    const s = sizer(win)
    await s.apply({ size: 'starter' })
    expect(win.setBounds).not.toHaveBeenCalled()
    expect(win.once).not.toHaveBeenCalled()
  })

  it('is safe on a destroyed window', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    win.isDestroyed.mockReturnValue(true)
    await sizer(win).apply({ size: 'starter' })
    expect(win.setBounds).not.toHaveBeenCalled()
  })

  it('a failed resize does not wedge later ones', async () => {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    const s = sizer(win, 'linux')
    win.setBounds.mockImplementationOnce(() => {
      throw new Error('destroyed')
    })
    await s.apply({ size: 'starter' })
    await s.apply({ size: 'auth' })
    expect(s.size).toBe('auth')
  })
})

describe('createWindowSizeHandler', () => {
  // eslint-disable-next-line @typescript-eslint/explicit-function-return-type -- mocks are the type
  function handler(isMain: boolean) {
    const win = fakeWindow({ x: 0, y: 0, width: 1440, height: 900 })
    const s = sizer(win, 'linux')
    const apply = vi.spyOn(s, 'apply')
    const onSized = vi.fn()
    const handle = createWindowSizeHandler({
      isMainSender: () => isMain,
      sizer: () => s,
      onSized
    })
    return { handle, apply, onSized }
  }

  it('refuses any window but the main one, without touching the sizer or the gate', async () => {
    const { handle, apply, onSized } = handler(false)
    await expect(handle({ sender: {} }, { size: 'starter' })).resolves.toBe(false)
    expect(apply).not.toHaveBeenCalled()
    expect(onSized).not.toHaveBeenCalled()
  })

  it('refuses a bad payload', async () => {
    const { handle, apply, onSized } = handler(true)
    await expect(handle({ sender: {} }, { size: 'huge' })).resolves.toBe(false)
    expect(apply).not.toHaveBeenCalled()
    expect(onSized).not.toHaveBeenCalled()
  })

  it('applies a valid request from the main window and releases the gate', async () => {
    const { handle, apply, onSized } = handler(true)
    await expect(handle({ sender: {} }, { size: 'starter' })).resolves.toBe(true)
    expect(apply).toHaveBeenCalledWith({ size: 'starter' })
    expect(onSized).toHaveBeenCalledTimes(1)
  })
})

describe('createRevealGate', () => {
  it('shows once the page is ready and its first size is applied', () => {
    vi.useFakeTimers()
    const show = vi.fn()
    const gate = createRevealGate(show, 600)
    gate.sized()
    expect(show).not.toHaveBeenCalled()
    gate.ready()
    expect(show).toHaveBeenCalledTimes(1)
    gate.sized()
    vi.runAllTimers()
    expect(show).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('falls back to showing after the wait when no size ever arrives', () => {
    vi.useFakeTimers()
    const show = vi.fn()
    const gate = createRevealGate(show, 600)
    gate.ready()
    expect(show).not.toHaveBeenCalled()
    vi.advanceTimersByTime(600)
    expect(show).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})
