// SOLUSDEV-252 S3: the SOL window manager (docs/architecture/sol-window.md §2,
// wireflow §A/§B) — open-or-focus, geometry restore/clamp/reset, always-on-top,
// pushes and the sender-gated IPC — against structural fakes; the real
// BrowserWindow shell is on the COWORK QA checklist.
import { describe, it, expect, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import { readdirSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'
import {
  createSolWindowManager,
  GEOMETRY_SAVE_DEBOUNCE_MS,
  placeSolWindow,
  registerSolIpcHandlers,
  SOL_WINDOW_DEFAULT_SIZE,
  SOL_WINDOW_MARGIN,
  SOL_WINDOW_MIN_SIZE,
  SOL_WINDOW_OPTIONS,
  SOL_WINDOW_WEB_PREFERENCES,
  type Rect,
  type SolState,
  type SolWindowHandle,
  type SolWindowManagerDeps
} from './solWindow'
import { DEFAULT_SOL_SETTINGS, type SolSettingsState } from '../solSettings'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

const WA_A = { x: 0, y: 0, width: 1920, height: 1040 }
const WA_B = { x: 1920, y: 0, width: 1440, height: 860 }
const DISPLAY_A = { id: 1, workArea: WA_A }
const DISPLAY_B = { id: 2, workArea: WA_B }

interface Fake {
  handle: SolWindowHandle
  bounds: Rect
  alwaysOnTop: boolean
  focus: ReturnType<typeof vi.fn>
  sent: Array<{ channel: string; payload: unknown }>
  emit(event: string): void
  close(): void
}

function fakeWindow(bounds: Rect, alwaysOnTop: boolean): Fake {
  const listeners = new Map<string, Set<() => void>>()
  let destroyed = false
  const f: Fake = {
    bounds,
    alwaysOnTop,
    focus: vi.fn(),
    sent: [],
    emit: (event) => {
      for (const l of [...(listeners.get(event) ?? [])]) l()
    },
    close: () => {
      f.emit('close')
      destroyed = true
      f.emit('closed')
    },
    handle: {
      isDestroyed: () => destroyed,
      on: (event, listener) => {
        const set = listeners.get(event) ?? new Set()
        set.add(listener)
        listeners.set(event, set)
      },
      focus: (...a) => void f.focus(...a),
      show: () => {},
      close: () => f.close(),
      getBounds: () => f.bounds,
      setAlwaysOnTop: (flag) => {
        f.alwaysOnTop = flag
      },
      webContents: { send: (channel, payload) => void f.sent.push({ channel, payload }) }
    }
  }
  return f
}

function harness(
  settingsInit: Partial<SolSettingsState> = {},
  cursor = { x: 100, y: 100 }
): {
  deps: SolWindowManagerDeps
  windows: Fake[]
  settings: SolSettingsState
  timers: Array<{ fn: () => void; ms: number }>
  others: Fake[]
} {
  const windows: Fake[] = []
  const others = [fakeWindow(WA_A, false)]
  let settings: SolSettingsState = { ...DEFAULT_SOL_SETTINGS, ...settingsInit }
  const timers: Array<{ fn: () => void; ms: number }> = []
  const state = {
    get settings() {
      return settings
    }
  }
  const deps: SolWindowManagerDeps = {
    createWindow: (bounds, alwaysOnTop) => {
      const w = fakeWindow(bounds, alwaysOnTop)
      windows.push(w)
      return w.handle
    },
    screen: {
      getCursorScreenPoint: () => cursor,
      getDisplayNearestPoint: (p) => (p.x >= 1920 ? DISPLAY_B : DISPLAY_A),
      getAllDisplays: () => [DISPLAY_A, DISPLAY_B]
    },
    settings: {
      get: () => settings,
      setWindowGeometry: (window) => {
        settings = { ...settings, window }
      },
      setAlwaysOnTop: (alwaysOnTop) => {
        settings = { ...settings, alwaysOnTop }
      }
    },
    allWindows: () => [...others.map((o) => o.handle), ...windows.map((w) => w.handle)],
    scheduler: {
      setTimeout: (fn, ms) => {
        timers.push({ fn, ms })
        return timers.length
      },
      clearTimeout: (h) => {
        if (typeof h === 'number') timers.splice(h - 1, 1, { fn: () => {}, ms: -1 })
      }
    }
  }
  return {
    deps,
    windows,
    timers,
    others,
    get settings() {
      return state.settings
    }
  }
}

describe('placeSolWindow', () => {
  it('no saved geometry → default size, bottom-right of the cursor display work area', () => {
    expect(placeSolWindow(null, [DISPLAY_A, DISPLAY_B], DISPLAY_B)).toEqual({
      x: WA_B.x + WA_B.width - SOL_WINDOW_DEFAULT_SIZE.width - SOL_WINDOW_MARGIN,
      y: WA_B.y + WA_B.height - SOL_WINDOW_DEFAULT_SIZE.height - SOL_WINDOW_MARGIN,
      ...SOL_WINDOW_DEFAULT_SIZE
    })
  })

  it('restores saved geometry on its display, clamped into the work area', () => {
    const saved = { x: 3200, y: -50, width: 2000, height: 500, displayId: 2 }
    expect(placeSolWindow(saved, [DISPLAY_A, DISPLAY_B], DISPLAY_A)).toEqual({
      x: WA_B.x,
      y: WA_B.y,
      width: WA_B.width,
      height: 500
    })
  })

  it('saved display gone → reset to default placement on the cursor display', () => {
    const saved = { x: 10, y: 10, width: 500, height: 700, displayId: 99 }
    expect(placeSolWindow(saved, [DISPLAY_A, DISPLAY_B], DISPLAY_A)).toEqual(
      placeSolWindow(null, [DISPLAY_A, DISPLAY_B], DISPLAY_A)
    )
  })

  it('a work area smaller than the minimum keeps the minimum, anchored at the work-area origin', () => {
    const tiny = { id: 3, workArea: { x: 100, y: 50, width: 300, height: 300 } }
    const saved = { x: -100, y: -100, width: 500, height: 700, displayId: 3 }
    expect(placeSolWindow(saved, [tiny], tiny)).toEqual({ x: 100, y: 50, ...SOL_WINDOW_MIN_SIZE })
  })

  it('never goes below the minimum size', () => {
    const saved = { x: 0, y: 0, width: 10, height: 10, displayId: 1 }
    expect(placeSolWindow(saved, [DISPLAY_A], DISPLAY_A)).toMatchObject(SOL_WINDOW_MIN_SIZE)
  })
})

describe('manager', () => {
  registerWindowLifecycleAndGeometryTests()
  registerWindowStateBroadcastsTests()
  registerWindowRegionReadinessTests()
})

const STATE: SolState = {
  actionMode: 'guide',
  screenIntelligence: false,
  hotkeysEnabled: true,
  alwaysOnTop: false,
  capture: { mode: 'available', message: '' },
  hotkeys: null,
  lastRegionRefused: false
}

const EVENT = {} as IpcMainInvokeEvent

function registerWith(allowed: () => boolean): {
  handlers: Map<string, (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown>
  calls: string[]
} {
  const handlers = new Map<string, (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown>()
  const calls: string[] = []
  registerSolIpcHandlers(
    { handle: (channel, fn) => void handlers.set(channel, fn) },
    {
      windows: {
        open: () => void calls.push('open'),
        setAlwaysOnTop: (b) => void calls.push(`aot:${b}`),
        markReady: () => void calls.push('ready')
      },
      settings: {
        setMode: (m) => void calls.push(`mode:${m}`),
        setScreenIntelligence: (b) => void calls.push(`si:${b}`),
        setHotkeys: (b) => void calls.push(`hk:${b}`)
      },
      state: () => STATE
    },
    allowed
  )
  return { handlers, calls }
}

describe('IPC registration', () => {
  it('registers the six invokes on the shared constants and returns the state', () => {
    const { handlers, calls } = registerWith(() => true)
    const c = SOL_WINDOW_CHANNELS
    expect([...handlers.keys()].sort()).toEqual(
      [
        c.open,
        c.getState,
        c.setMode,
        c.setScreenIntelligence,
        c.setAlwaysOnTop,
        c.setHotkeys
      ].sort()
    )
    expect(handlers.get(c.getState)?.(EVENT)).toEqual(STATE) // marks the sender ready
    expect(handlers.get(c.open)?.(EVENT)).toEqual(STATE)
    handlers.get(c.setMode)?.(EVENT, 'do')
    handlers.get(c.setMode)?.(EVENT, 'expert') // not a mode: ignored
    handlers.get(c.setScreenIntelligence)?.(EVENT, true)
    handlers.get(c.setScreenIntelligence)?.(EVENT, 'yes')
    handlers.get(c.setAlwaysOnTop)?.(EVENT, false)
    handlers.get(c.setHotkeys)?.(EVENT, false)
    handlers.get(c.setHotkeys)?.(EVENT, 'off') // not a boolean: ignored
    expect(calls).toEqual(['ready', 'open', 'mode:do', 'si:true', 'aot:false', 'hk:false'])
  })

  it('a foreign sender gets null and no action', () => {
    const { handlers, calls } = registerWith(() => false)
    for (const channel of Object.values(SOL_WINDOW_CHANNELS)) {
      expect(handlers.get(channel)?.(EVENT, 'do') ?? null).toBeNull()
    }
    expect(calls).toEqual([])
  })
})

describe('channel-literal ratchet', () => {
  it('no sol: channel literal appears outside the constants module', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const roots = [join(here, '..'), join(here, '..', '..', 'preload')]
    const sources = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) return sources(full)
        return entry.name.endsWith('.ts') &&
          !entry.name.endsWith('.test.ts') &&
          entry.name !== 'solWindow.constants.ts'
          ? [full]
          : []
      })
    const offenders = roots
      .flatMap(sources)
      .filter((file) => /["'`]sol(-window)?:/.test(readFileSync(file, 'utf8')))
    expect(offenders).toEqual([])
  })
})

describe('window hardening (SOLX-02 Phase-4 security, kept)', () => {
  it('pins the isolation posture explicitly — never an Electron default', () => {
    expect(SOL_WINDOW_WEB_PREFERENCES).toEqual({
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false
    })
  })

  it('native frame, resizable, minimum 360×420, no webPreferences of its own', () => {
    expect('webPreferences' in SOL_WINDOW_OPTIONS).toBe(false)
    expect(SOL_WINDOW_OPTIONS).toMatchObject({
      frame: true,
      resizable: true,
      minWidth: 360,
      minHeight: 420
    })
  })
})

function registerWindowLifecycleAndGeometryTests(): void {
  it('open creates one window near the cursor; a repeat focuses it; closed clears the slot', () => {
    const h = harness({}, { x: 2500, y: 300 })
    const m = createSolWindowManager(h.deps)
    expect(m.isOpen()).toBe(false)
    m.open()
    expect(h.windows).toHaveLength(1)
    expect(h.windows[0].bounds).toEqual(placeSolWindow(null, [DISPLAY_A, DISPLAY_B], DISPLAY_B))
    m.open()
    expect(h.windows).toHaveLength(1)
    expect(h.windows[0].focus).toHaveBeenCalledTimes(1)
    h.windows[0].close()
    expect(m.isOpen()).toBe(false)
    m.open({ near: { x: 5, y: 5 } })
    expect(h.windows).toHaveLength(2)
    expect(h.windows[1].bounds).toEqual(placeSolWindow(null, [DISPLAY_A, DISPLAY_B], DISPLAY_A))
  })

  it('saves geometry 300 ms after the last move/resize, tagged with its display', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    const w = h.windows[0]
    w.bounds = { x: 2000, y: 100, width: 500, height: 700 }
    w.emit('move')
    w.emit('resize')
    expect(h.settings.window).toBeNull()
    // Two events, one live timer: the first was cleared by the second (debounce).
    const live = h.timers.filter((t) => t.ms === GEOMETRY_SAVE_DEBOUNCE_MS)
    expect(live).toHaveLength(1)
    live[0].fn()
    expect(h.settings.window).toEqual({ x: 2000, y: 100, width: 500, height: 700, displayId: 2 })
  })

  it('a pending save is flushed on close, and nothing fires after closed', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    const w = h.windows[0]
    w.bounds = { x: 50, y: 60, width: 400, height: 500 }
    w.emit('move')
    w.close()
    expect(h.settings.window).toEqual({ x: 50, y: 60, width: 400, height: 500, displayId: 1 })
    expect(h.timers.every((t) => t.ms === -1)).toBe(true)
  })

  it('always-on-top is read from settings at creation and toggled live', () => {
    const h = harness({ alwaysOnTop: true })
    const m = createSolWindowManager(h.deps)
    m.open()
    expect(h.windows[0].alwaysOnTop).toBe(true)
    m.setAlwaysOnTop(false)
    expect(h.windows[0].alwaysOnTop).toBe(false)
    expect(h.settings.alwaysOnTop).toBe(false)
    h.windows[0].close()
    m.setAlwaysOnTop(true) // no window: settings only, no throw
    expect(h.settings.alwaysOnTop).toBe(true)
  })
}

function registerWindowStateBroadcastsTests(): void {
  it('pushState reaches every live window; pushRegion reaches only the SOL window', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    const region = {
      pngBase64: 'AA==',
      contextPngBase64: 'AA==',
      width: 1,
      height: 1,
      source: null,
      capturedAt: 1
    }
    expect(m.pushRegion(region)).toBe(false)
    m.open()
    m.pushState(STATE)
    expect(h.others[0].sent).toEqual([{ channel: SOL_WINDOW_CHANNELS.state, payload: STATE }])
    expect(h.windows[0].sent).toEqual([{ channel: SOL_WINDOW_CHANNELS.state, payload: STATE }])
    m.markReady(h.windows[0].handle.webContents)
    expect(m.pushRegion(region)).toBe(true)
    expect(h.windows[0].sent.at(-1)).toEqual({
      channel: SOL_WINDOW_CHANNELS.region,
      payload: region
    })
    expect(h.others[0].sent).toHaveLength(1)
  })

  it('pushState reaches the SOL window even when allWindows() is empty', () => {
    const h = harness()
    const m = createSolWindowManager({ ...h.deps, allWindows: () => [] })
    m.open()
    m.pushState(STATE)
    expect(h.windows[0].sent).toEqual([{ channel: SOL_WINDOW_CHANNELS.state, payload: STATE }])
  })

  it('a pending region dies with its window: closed drops it, the next window never sees it', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    const region = {
      pngBase64: 'AA==',
      contextPngBase64: '',
      width: 1,
      height: 1,
      source: null,
      capturedAt: 1
    }
    expect(m.pushRegion(region)).toBe(true)
    h.windows[0].close()
    m.open()
    m.markReady(h.windows[1].handle.webContents)
    expect(h.windows[0].sent).toEqual([])
    expect(h.windows[1].sent).toEqual([])
  })
}

function registerWindowRegionReadinessTests(): void {
  it('a region pushed before the renderer asked for state is queued, then delivered once', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    const w = h.windows[0]
    const region = {
      pngBase64: 'AA==',
      contextPngBase64: '',
      width: 1,
      height: 1,
      source: null,
      capturedAt: 1
    }
    expect(m.pushRegion(region)).toBe(true)
    expect(w.sent).toEqual([]) // renderer not mounted yet
    m.markReady(h.others[0].handle.webContents) // some other renderer: not ours
    expect(w.sent).toEqual([])
    m.markReady(w.handle.webContents)
    expect(w.sent).toEqual([{ channel: SOL_WINDOW_CHANNELS.region, payload: region }])
    m.markReady(w.handle.webContents)
    expect(w.sent).toHaveLength(1)
    // now live: pushes go straight through
    expect(m.pushRegion(region)).toBe(true)
    expect(w.sent).toHaveLength(2)
    // a new window starts unready again
    w.close()
    m.open()
    m.pushRegion(region)
    expect(h.windows[1].sent).toEqual([])
  })

  it('isSender recognises only the live SOL window webContents', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    expect(m.isSender({})).toBe(false)
    m.open()
    expect(m.isSender(h.windows[0].handle.webContents)).toBe(true)
    expect(m.isSender(h.others[0].handle.webContents)).toBe(false)
    h.windows[0].close()
    expect(m.isSender(h.windows[0].handle.webContents)).toBe(false)
  })
}
