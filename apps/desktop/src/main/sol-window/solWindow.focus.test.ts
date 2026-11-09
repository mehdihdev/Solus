// SOLUSDEV-319: dismissing the pill by hand (Esc, ×, double-tap Ctrl) must
// return the user to the app they summoned it over — not raise the main Solus
// window, which is what macOS does when the app's last key window hides while
// the app stays active. A blur hide needs nothing: focus already went elsewhere.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SOL_PILL_EXIT_MS } from './solWindow.constants'
import {
  createSolWindowManager,
  type Rect,
  type SolWindowHandle,
  type SolWindowManagerDeps
} from './solWindow'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

const WA = { x: 0, y: 0, width: 1920, height: 1040 }

interface Fake {
  handle: SolWindowHandle
  emit(event: string): void
}

function fakeWindow(bounds: Rect): Fake {
  let visible = true
  let rect = bounds
  const listeners = new Map<string, Array<() => void>>()
  return {
    emit: (event) => listeners.get(event)?.forEach((fn) => fn()),
    handle: {
      isDestroyed: () => false,
      on: (event, fn) => void listeners.set(event, [...(listeners.get(event) ?? []), fn]),
      focus: () => undefined,
      show: () => void (visible = true),
      hide: () => void (visible = false),
      isVisible: () => visible,
      close: () => undefined,
      getBounds: () => rect,
      setBounds: (r) => void (rect = r),
      webContents: { send: () => undefined }
    }
  }
}

function harness(appActive: boolean): {
  manager: ReturnType<typeof createSolWindowManager>
  windows: Fake[]
  yieldFocus: ReturnType<typeof vi.fn>
  setActive(flag: boolean): void
} {
  const windows: Fake[] = []
  let active = appActive
  const yieldFocus = vi.fn()
  const deps: SolWindowManagerDeps = {
    createWindow: (bounds) => {
      const w = fakeWindow(bounds)
      windows.push(w)
      return w.handle
    },
    screen: {
      getCursorScreenPoint: () => ({ x: 100, y: 100 }),
      getDisplayNearestPoint: () => ({ id: 1, workArea: WA, bounds: WA })
    },
    allWindows: () => [],
    appActive: () => active,
    yieldFocus
  }
  return {
    manager: createSolWindowManager(deps),
    windows,
    yieldFocus,
    setActive: (flag) => void (active = flag)
  }
}

const exit = (): void => void vi.advanceTimersByTime(SOL_PILL_EXIT_MS)

describe('pill dismissal returns focus', () => {
  beforeEach(() => void vi.useFakeTimers())
  afterEach(() => void vi.useRealTimers())

  it('hands focus back to the previous app after a hand hide (Esc / ×)', () => {
    const h = harness(false)
    h.manager.open()
    h.setActive(true) // the pill took focus
    h.manager.hide()
    expect(h.yieldFocus).not.toHaveBeenCalled() // not before the window hides
    exit()
    expect(h.yieldFocus).toHaveBeenCalledTimes(1)
  })

  it('hands focus back after a double-tap toggle hide', () => {
    const h = harness(false)
    h.manager.open()
    h.manager.toggle()
    exit()
    expect(h.yieldFocus).toHaveBeenCalledTimes(1)
  })

  it('stays in Solus when the pill was summoned over a Solus window', () => {
    const h = harness(true)
    h.manager.open()
    h.manager.hide()
    exit()
    expect(h.yieldFocus).not.toHaveBeenCalled()
  })

  it('does not yield on a blur hide — the user already went elsewhere', () => {
    const h = harness(false)
    h.manager.open()
    h.windows[0].emit('blur')
    exit()
    expect(h.windows[0].handle.isVisible()).toBe(false)
    expect(h.yieldFocus).not.toHaveBeenCalled()
  })

  it('remembers where it was summoned from across a resume, not the pill itself', () => {
    const h = harness(false)
    h.manager.open()
    h.setActive(true)
    h.manager.open() // re-open while shown: Solus is active only because of the pill
    h.manager.hide()
    exit()
    expect(h.yieldFocus).toHaveBeenCalledTimes(1)
  })

  it('a summon cancelled mid-exit does not yield', () => {
    const h = harness(false)
    h.manager.open()
    h.manager.toggle()
    h.manager.toggle()
    exit()
    expect(h.yieldFocus).not.toHaveBeenCalled()
  })
})
