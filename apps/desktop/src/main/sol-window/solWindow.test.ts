// SOLUSDEV-252 S3: the SOL window manager (docs/architecture/sol-window.md §2,
// wireflow §A/§B) — open-or-focus, pushes and the sender-gated IPC — against
// structural fakes; the real BrowserWindow shell is on the COWORK QA checklist.
// SOLUSDEV-319: the Ember Pill — summoned at the cursor, hide-on-blur unless
// busy, double-tap toggle, renderer-driven upward growth.
import { describe, it, expect, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import { readdirSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'
import {
  createSolWindowManager,
  registerSolIpcHandlers,
  SOL_WINDOW_OPTIONS,
  SOL_WINDOW_WEB_PREFERENCES,
  type Rect,
  type SolState,
  type SolWindowHandle,
  type SolWindowManagerDeps
} from './solWindow'
import { growPill, placePill, SOL_PILL_INITIAL_HEIGHT, SOL_PILL_WIDTH } from './pillGeometry'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

const WA_A = { x: 0, y: 0, width: 1920, height: 1040 }
const WA_B = { x: 1920, y: 0, width: 1440, height: 860 }
const DISPLAY_A = { id: 1, workArea: WA_A }
const DISPLAY_B = { id: 2, workArea: WA_B }

interface Fake {
  handle: SolWindowHandle
  bounds: Rect
  visible: boolean
  focus: ReturnType<typeof vi.fn>
  sent: Array<{ channel: string; payload: unknown }>
  emit(event: string): void
  close(): void
}

function fakeWindow(bounds: Rect): Fake {
  const listeners = new Map<string, Set<() => void>>()
  let destroyed = false
  const f: Fake = {
    bounds,
    visible: true,
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
      show: () => {
        f.visible = true
      },
      hide: () => {
        f.visible = false
      },
      isVisible: () => f.visible,
      close: () => f.close(),
      getBounds: () => f.bounds,
      setBounds: (rect) => {
        f.bounds = rect
      },
      webContents: { send: (channel, payload) => void f.sent.push({ channel, payload }) }
    }
  }
  return f
}

function harness(cursor = { x: 100, y: 100 }): {
  moveCursor(p: { x: number; y: number }): void
  deps: SolWindowManagerDeps
  windows: Fake[]
  others: Fake[]
} {
  const windows: Fake[] = []
  const others = [fakeWindow(WA_A)]
  let pointer = cursor
  const deps: SolWindowManagerDeps = {
    createWindow: (bounds) => {
      const w = fakeWindow(bounds)
      windows.push(w)
      return w.handle
    },
    screen: {
      getCursorScreenPoint: () => pointer,
      getDisplayNearestPoint: (p) => (p.x >= 1920 ? DISPLAY_B : DISPLAY_A)
    },
    allWindows: () => [...others.map((o) => o.handle), ...windows.map((w) => w.handle)]
  }
  return {
    moveCursor: (p) => {
      pointer = p
    },
    deps,
    windows,
    others
  }
}

describe('manager', () => {
  registerWindowLifecycleAndGeometryTests()
  registerPillSummonTests()
  registerWindowStateBroadcastsTests()
  registerWindowRegionReadinessTests()
})

const STATE: SolState = {
  actionMode: 'guide',
  screenIntelligence: false,
  hotkeysEnabled: true,
  capture: { mode: 'available', message: '' },
  hotkeys: null,
  lastRegionRefused: false
}

const EVENT = {} as IpcMainInvokeEvent
const PILL_FRAME = {}
const PILL_EVENT = {
  sender: { mainFrame: PILL_FRAME },
  senderFrame: PILL_FRAME
} as unknown as IpcMainInvokeEvent

function registerWith(
  allowed: () => boolean,
  fromPill: (sender: unknown) => boolean = () => true
): {
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
        markReady: () => void calls.push('ready'),
        isSender: fromPill,
        resize: (h) => void calls.push(`resize:${h}`),
        setBusy: (b) => void calls.push(`busy:${b}`),
        hide: () => void calls.push('hide')
      },
      settings: {
        setMode: (m) => void calls.push(`mode:${m}`),
        setScreenIntelligence: (b) => void calls.push(`si:${b}`),
        setHotkeys: (b) => void calls.push(`hk:${b}`)
      },
      state: () => STATE,
      openCaptureSettings: () => void calls.push('capture-settings')
    },
    allowed
  )
  return { handlers, calls }
}

describe('IPC registration', () => {
  it('opens the capture settings pane with no renderer argument (SOLUSDEV-318)', () => {
    const { handlers, calls } = registerWith(() => true)
    const c = SOL_WINDOW_CHANNELS
    expect(handlers.get(c.openCaptureSettings)?.(EVENT, 'https://evil.example')).toEqual(STATE)
    expect(calls).toEqual(['capture-settings'])
  })

  it('the pill invokes validate their argument and act only for the SOL window itself', () => {
    const c = SOL_WINDOW_CHANNELS
    const pill = registerWith(() => true)
    const send = (channel: string, event: IpcMainInvokeEvent, arg?: unknown): unknown =>
      pill.handlers.get(channel)?.(event, arg) ?? null
    send(c.resize, PILL_EVENT, 320)
    send(c.resize, PILL_EVENT, '320') // not a number: ignored
    send(c.resize, PILL_EVENT, Number.POSITIVE_INFINITY) // not finite: ignored
    send(c.setBusy, PILL_EVENT, true)
    send(c.setBusy, PILL_EVENT, 1) // not a boolean: ignored
    expect(send(c.hide, PILL_EVENT, 'anything')).toEqual(STATE)
    expect(pill.calls).toEqual(['resize:320', 'busy:true', 'hide'])
    // A subframe of the pill's own webContents is not the pill.
    const subframe = { ...PILL_EVENT, senderFrame: {} } as unknown as IpcMainInvokeEvent
    expect(send(c.hide, subframe)).toBeNull()
    expect(pill.calls).toHaveLength(3)
    // The main window is an allowed sender for the other invokes, never for these.
    const main = registerWith(
      () => true,
      () => false
    )
    for (const channel of [c.resize, c.setBusy, c.hide]) {
      expect(main.handlers.get(channel)?.(PILL_EVENT, true) ?? null).toBeNull()
    }
    expect(main.calls).toEqual([])
  })

  it('registers the ten invokes on the shared constants and returns the state', () => {
    const { handlers, calls } = registerWith(() => true)
    const c = SOL_WINDOW_CHANNELS
    expect([...handlers.keys()].sort()).toEqual(
      [
        c.open,
        c.getState,
        c.guideTarget,
        c.setMode,
        c.setScreenIntelligence,
        c.setHotkeys,
        c.openCaptureSettings,
        c.resize,
        c.setBusy,
        c.hide
      ].sort()
    )
    expect(handlers.get(c.getState)?.(EVENT)).toEqual(STATE) // marks the sender ready
    expect(handlers.get(c.open)?.(EVENT)).toEqual(STATE)
    handlers.get(c.setMode)?.(EVENT, 'do')
    handlers.get(c.setMode)?.(EVENT, 'expert') // not a mode: ignored
    handlers.get(c.setScreenIntelligence)?.(EVENT, true)
    handlers.get(c.setScreenIntelligence)?.(EVENT, 'yes')
    handlers.get(c.setHotkeys)?.(EVENT, false)
    handlers.get(c.setHotkeys)?.(EVENT, 'off') // not a boolean: ignored
    expect(calls).toEqual(['ready', 'open', 'mode:do', 'si:true', 'hk:false'])
  })

  it('a foreign sender gets null and no action', async () => {
    const { handlers, calls } = registerWith(() => false)
    for (const channel of Object.values(SOL_WINDOW_CHANNELS)) {
      expect((await handlers.get(channel)?.(EVENT, 'do')) ?? null).toBeNull()
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

  it('a frameless, transparent, always-on-top pill with no webPreferences of its own', () => {
    expect('webPreferences' in SOL_WINDOW_OPTIONS).toBe(false)
    expect(SOL_WINDOW_OPTIONS).toMatchObject({
      frame: false,
      transparent: true,
      resizable: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      hasShadow: false,
      width: SOL_PILL_WIDTH
    })
  })
})

function registerWindowLifecycleAndGeometryTests(): void {
  const pill = { width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT }

  it('open creates one pill at the cursor; a repeat focuses it; closed clears the slot', () => {
    const h = harness({ x: 2500, y: 300 })
    const m = createSolWindowManager(h.deps)
    expect(m.isOpen()).toBe(false)
    m.open()
    expect(h.windows).toHaveLength(1)
    expect(h.windows[0].bounds).toEqual(placePill({ x: 2500, y: 300 }, WA_B, pill))
    m.open()
    expect(h.windows).toHaveLength(1)
    expect(h.windows[0].focus).toHaveBeenCalledTimes(1)
    h.windows[0].close()
    expect(m.isOpen()).toBe(false)
    m.open({ near: { x: 5, y: 5 } })
    expect(h.windows).toHaveLength(2)
    expect(h.windows[1].bounds).toEqual(placePill({ x: 5, y: 5 }, WA_A, pill))
  })
}

function registerPillSummonTests(): void {
  const pill = { width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT }

  it('blur hides an idle pill, keeps a busy one, and the window survives hiding', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    const w = h.windows[0]
    m.setBusy(true)
    w.emit('blur')
    expect(w.visible).toBe(true)
    m.setBusy(false)
    w.emit('blur')
    expect(w.visible).toBe(false)
    expect(m.isOpen()).toBe(true)
    expect(m.isVisible()).toBe(false)
  })

  it('toggle hides a shown pill and re-summons a hidden one at the new cursor', () => {
    const h = harness({ x: 600, y: 300 })
    const m = createSolWindowManager(h.deps)
    m.toggle() // nothing open: opens
    const w = h.windows[0]
    expect(w.visible).toBe(true)
    m.toggle()
    expect(w.visible).toBe(false)
    h.moveCursor({ x: 900, y: 500 })
    m.toggle()
    expect(h.windows).toHaveLength(1)
    expect(w.visible).toBe(true)
    expect(w.bounds).toEqual(placePill({ x: 900, y: 500 }, WA_A, pill))
    expect(w.focus).toHaveBeenCalled()
  })

  it('open on a hidden pill shows it again (tray, page button, gesture)', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    m.hide()
    expect(h.windows[0].visible).toBe(false)
    m.open()
    expect(h.windows[0].visible).toBe(true)
  })

  it('resize grows upward from the summon placement and keeps that height on re-summon', () => {
    const h = harness({ x: 600, y: 300 })
    const m = createSolWindowManager(h.deps)
    m.resize(300) // no window: ignored, no throw
    m.open()
    const home = placePill({ x: 600, y: 300 }, WA_A, pill)
    m.resize(300)
    expect(h.windows[0].bounds).toEqual(growPill({ x: 600, y: 300 }, home, 300, WA_A))
    m.hide()
    h.moveCursor({ x: 700, y: 900 })
    m.open()
    const home2 = placePill({ x: 700, y: 900 }, WA_A, pill)
    expect(h.windows[0].bounds).toEqual(growPill({ x: 700, y: 900 }, home2, 300, WA_A))
  })

  it('a closed window forgets busy, so the next pill hides on blur', () => {
    const h = harness()
    const m = createSolWindowManager(h.deps)
    m.open()
    m.setBusy(true)
    h.windows[0].close()
    m.open()
    h.windows[1].emit('blur')
    expect(h.windows[1].visible).toBe(false)
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

it('native lookup rejects late mode/scope changes and never queries for foreign senders', async () => {
  let generation = 1
  let mode: 'guide' | 'do' = 'guide'
  let finish!: (value: null) => void
  const lookup = vi.fn(
    () =>
      new Promise<null>((resolve) => {
        finish = resolve
      })
  )
  const handlers = new Map<string, (event: IpcMainInvokeEvent) => unknown>()
  registerSolIpcHandlers(
    { handle: (channel, fn) => void handlers.set(channel, fn) },
    {
      windows: {
        open: vi.fn(),
        markReady: vi.fn(),
        isSender: () => true,
        resize: vi.fn(),
        setBusy: vi.fn(),
        hide: vi.fn()
      },
      settings: { setMode: vi.fn(), setScreenIntelligence: vi.fn(), setHotkeys: vi.fn() },
      state: () => ({ ...STATE, actionMode: mode }),
      guideScope: () => generation,
      guideTarget: lookup
    },
    (event) => event === EVENT
  )
  const handler = handlers.get(SOL_WINDOW_CHANNELS.guideTarget)!
  expect(await handler({} as IpcMainInvokeEvent)).toBeNull()
  expect(lookup).not.toHaveBeenCalled()
  const pending = handler(EVENT)
  generation += 2 // project A → B → A
  finish(null)
  expect(await pending).toBeNull()
  mode = 'do'
  expect(await handler(EVENT)).toBeNull()
  expect(lookup).toHaveBeenCalledTimes(1)
})
