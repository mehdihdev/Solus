// SOLUSDEV-324: the summon picture. Wireflow sol-window §D: SOL takes a picture
// of the screen when it is summoned. The capture hook runs BEFORE the pill is
// shown (so the pill never covers what the person is asking about), alongside
// the drive gate, never for a pill already on screen, and never holds a summon
// longer than SUMMON_CAPTURE_WAIT_MS. The picture reaches the pill's own top
// frame only, through sol:take-screen.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import {
  SOL_PILL_EXIT_MS,
  SOL_WINDOW_CHANNELS,
  SUMMON_CAPTURE_WAIT_MS
} from './solWindow.constants'
import {
  createSolWindowManager,
  registerSolIpcHandlers,
  type Rect,
  type SolIpcDeps,
  type SolState,
  type SolWindowHandle
} from './solWindow'
import type { SolScreenPayload } from '../capture/summonShot'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

const WA = { x: 0, y: 0, width: 1920, height: 1040 }

function fakeWindow(bounds: Rect, log: string[]): SolWindowHandle {
  let visible = true
  let rect = bounds
  return {
    isDestroyed: () => false,
    on: () => undefined,
    focus: () => void log.push('focus'),
    show: () => {
      visible = true
      log.push('show')
    },
    hide: () => void (visible = false),
    isVisible: () => visible,
    close: () => undefined,
    getBounds: () => rect,
    setBounds: (r) => void (rect = r),
    webContents: { send: () => undefined }
  }
}

function harness(): {
  manager: ReturnType<typeof createSolWindowManager>
  log: string[]
  windows: SolWindowHandle[]
} {
  const log: string[] = []
  const windows: SolWindowHandle[] = []
  const manager = createSolWindowManager({
    createWindow: (bounds) => {
      log.push('create')
      const w = fakeWindow(bounds, log)
      windows.push(w)
      return w
    },
    screen: {
      getCursorScreenPoint: () => ({ x: 10, y: 10 }),
      getDisplayNearestPoint: () => ({ id: 1, workArea: WA })
    },
    allWindows: () => []
  })
  return { manager, log, windows }
}

/** A summon-picture holder whose refresh is `refresh`. */
const holder = (
  refresh: (near: { x: number; y: number }) => Promise<void>
): { refresh: typeof refresh; clear: ReturnType<typeof vi.fn> } => ({ refresh, clear: vi.fn() })

/** Settle the summon's promise chain (gate, bounded capture, show). */
const flush = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0)
}

describe('summon capture hook', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('runs before the pill is created or shown', async () => {
    const { manager, log } = harness()
    manager.setSummonCapture(holder(async () => void log.push('capture')))
    manager.open()
    await flush()
    expect(log.slice(0, 2)).toEqual(['capture', 'create'])
  })

  it('runs alongside the drive gate; both settle before the show', async () => {
    const { manager, log } = harness()
    manager.setSummonGate(async () => void log.push('gate'))
    manager.setSummonCapture(holder(async () => void log.push('capture')))
    manager.open()
    await flush()
    expect(log.indexOf('create')).toBeGreaterThan(log.indexOf('gate'))
    expect(log.indexOf('create')).toBeGreaterThan(log.indexOf('capture'))
  })

  it('a re-summon of a hidden pill captures again, before the show', async () => {
    const { manager, log, windows } = harness()
    const capture = vi.fn(async () => void log.push('capture'))
    manager.setSummonCapture(holder(capture))
    manager.open()
    await flush()
    windows[0].hide()
    log.length = 0
    manager.open()
    await flush()
    expect(capture).toHaveBeenCalledTimes(2)
    expect(log.indexOf('capture')).toBeLessThan(log.indexOf('show'))
  })

  it('a pill already on screen is only focused — no capture (it would picture itself)', async () => {
    const { manager } = harness()
    const capture = vi.fn(async () => undefined)
    manager.setSummonCapture(holder(capture))
    manager.open()
    await flush()
    manager.open()
    await flush()
    expect(capture).toHaveBeenCalledTimes(1)
  })

  it('a slow capture never holds the summon past SUMMON_CAPTURE_WAIT_MS', async () => {
    const { manager, log } = harness()
    manager.setSummonCapture(holder(() => new Promise(() => undefined)))
    manager.open()
    await flush()
    expect(log).not.toContain('create')
    await vi.advanceTimersByTimeAsync(SUMMON_CAPTURE_WAIT_MS)
    expect(log).toContain('create')
  })

  it('pictures the display the pill opens on (the summon point), not a later cursor', async () => {
    const { manager } = harness()
    const capture = vi.fn(async () => undefined)
    manager.setSummonCapture(holder(capture))
    manager.open({ near: { x: 3000, y: 20 } })
    await flush()
    expect(capture).toHaveBeenCalledWith({ x: 3000, y: 20 })
  })

  it('the picture is dropped when the pill hides, and on dropSummonCapture (sign-out)', async () => {
    const { manager } = harness()
    const h = holder(async () => undefined)
    manager.setSummonCapture(h)
    manager.open()
    await flush()
    manager.hide()
    await vi.advanceTimersByTimeAsync(SOL_PILL_EXIT_MS)
    expect(h.clear).toHaveBeenCalledTimes(1)
    manager.dropSummonCapture()
    expect(h.clear).toHaveBeenCalledTimes(2)
  })

  it('a failing capture still opens the pill', async () => {
    const { manager, log } = harness()
    manager.setSummonCapture(
      holder(async () => {
        throw new Error('boom')
      })
    )
    manager.open()
    await flush()
    expect(log).toContain('create')
  })
})

const STATE = { actionMode: 'guide' } as unknown as SolState
const SHOT: SolScreenPayload = {
  jpegBase64: '/9j/AAAA',
  width: 1920,
  height: 1080,
  source: null,
  capturedAt: 1
}

describe('sol:take-screen IPC', () => {
  type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown
  function register(): {
    take: Handler
    takeScreen: ReturnType<typeof vi.fn>
    pill: IpcMainInvokeEvent
    mainWindow: IpcMainInvokeEvent
  } {
    const handlers = new Map<string, Handler>()
    const pillContents = { mainFrame: {} }
    const mainContents = { mainFrame: {} }
    const takeScreen = vi.fn(() => SHOT)
    const deps: SolIpcDeps = {
      windows: {
        open: vi.fn(),
        markReady: vi.fn(),
        isSender: (s) => s === pillContents,
        resize: vi.fn(),
        setBusy: vi.fn(),
        hide: vi.fn()
      },
      settings: { setMode: vi.fn(), setScreenIntelligence: vi.fn(), setHotkeys: vi.fn() },
      state: () => STATE,
      takeScreen
    }
    registerSolIpcHandlers({ handle: (c, l) => void handlers.set(c, l) }, deps, () => true)
    const event = (sender: { mainFrame: object }, frame: object): IpcMainInvokeEvent =>
      ({ sender, senderFrame: frame }) as unknown as IpcMainInvokeEvent
    return {
      take: handlers.get(SOL_WINDOW_CHANNELS.takeScreen) as Handler,
      takeScreen,
      pill: event(pillContents, pillContents.mainFrame),
      mainWindow: event(mainContents, mainContents.mainFrame)
    }
  }

  it("hands the summon picture to the pill's top frame", () => {
    const { take, pill } = register()
    expect(take(pill)).toEqual(SHOT)
  })

  it('answers null to any other renderer and never consumes the picture for it', () => {
    const { take, mainWindow, takeScreen } = register()
    expect(take(mainWindow)).toBeNull()
    expect(takeScreen).not.toHaveBeenCalled()
  })

  it('answers null to a subframe inside the pill', () => {
    const { take, pill, takeScreen } = register()
    const sub = { ...pill, senderFrame: {} } as unknown as IpcMainInvokeEvent
    expect(take(sub)).toBeNull()
    expect(takeScreen).not.toHaveBeenCalled()
  })
})
