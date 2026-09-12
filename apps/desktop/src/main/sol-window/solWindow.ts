// SOLUSDEV-252 S3: the SOL window manager (docs/architecture/sol-window.md §2,
// wireflow §A/§B) — replaces the SOLX-02 detach/attach registry. ONE
// resizable, geometry-remembering, optionally always-on-top BrowserWindow at
// #/sol-window, summoned by hotkey/gesture or from the page. It stays the
// CTR-06 host: attachOrbOverlayWire is attached at creation. The manager and
// the IPC seam are injected-structural (the companion / orbOverlayWire testing
// pattern); the thin BrowserWindow shell is exercised on the COWORK QA list.
import { BrowserWindow, shell, type IpcMainInvokeEvent } from 'electron'
import { externalOpenHandler } from '../externalUrl'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import { attachOrbOverlayWire, type WireIpc } from './orbOverlayWire'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'
import type { SolActionMode, SolSettings, SolWindowGeometry } from '../solSettings'
import type { CaptureCapability } from '../capture/screenCapture'
import type { CapabilityState } from '../platform/capabilities'
import type { ActiveWindowInfo } from '../capture/activeWindow'

/** The isolation posture, explicit and asserted — never inherited from an
 *  Electron default that a template bump could flip (SEC-H2). */
export const SOL_WINDOW_WEB_PREFERENCES = {
  sandbox: false, // the preload imports @electron-toolkit/preload, as the main window does
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false
} as const

export const SOL_WINDOW_DEFAULT_SIZE = { width: 420, height: 640 } as const
export const SOL_WINDOW_MIN_SIZE = { width: 360, height: 420 } as const
export const SOL_WINDOW_MARGIN = 24
export const GEOMETRY_SAVE_DEBOUNCE_MS = 300

export const SOL_WINDOW_OPTIONS = {
  frame: true,
  resizable: true,
  minWidth: SOL_WINDOW_MIN_SIZE.width,
  minHeight: SOL_WINDOW_MIN_SIZE.height,
  show: false,
  autoHideMenuBar: true,
  title: 'SOL'
} as const

export interface Point {
  x: number
  y: number
}
export interface Rect extends Point {
  width: number
  height: number
}

export interface DisplaySlice {
  id: number
  workArea: Rect
}

/** Structural slice of BrowserWindow — just what the manager needs. */
export interface SolWindowHandle {
  isDestroyed(): boolean
  on(event: 'move' | 'resize' | 'close' | 'closed', listener: () => void): void
  focus(): void
  show(): void
  close(): void
  getBounds(): Rect
  setAlwaysOnTop(flag: boolean): void
  webContents: { send(channel: string, payload: unknown): void }
}

/** Structural slice of ipcMain for invoke registration. */
export interface SolWindowIpc {
  handle(
    channel: string,
    listener: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown
  ): void
}

/** What the hotkeys lane reports (main/hotkeys HotkeyStatus, structurally). */
export interface SolHotkeyStatus {
  hook: CapabilityState
  shortcuts: object
  mode: 'hook' | 'fallback'
  circleModeActive: boolean
  summary: string
}

/** The state snapshot (SOL_WINDOW_CHANNELS.state) every app renderer receives (§7). */
export interface SolState {
  actionMode: SolActionMode
  screenIntelligence: boolean
  /** The hold-Ctrl gestures setting (main/solSettings `hotkeys`); `hotkeys`
   *  below is what is actually running given the platform. */
  hotkeysEnabled: boolean
  alwaysOnTop: boolean
  capture: CaptureCapability
  hotkeys: SolHotkeyStatus | null
  /** The last gesture opened the window without a capture because the setting is off. */
  lastRegionRefused: boolean
}

/** The region payload (SOL_WINDOW_CHANNELS.region) — pushed to the SOL window only, never persisted. */
export interface SolRegionPayload {
  /** The crop, PNG. */
  pngBase64: string
  /** The downscaled full-screen context, PNG. */
  contextPngBase64: string
  width: number
  height: number
  source: ActiveWindowInfo | null
  capturedAt: number
}

export interface SolWindowManagerDeps {
  createWindow(bounds: Rect, alwaysOnTop: boolean): SolWindowHandle
  screen: {
    getCursorScreenPoint(): Point
    getDisplayNearestPoint(point: Point): DisplaySlice
    getAllDisplays(): DisplaySlice[]
  }
  settings: Pick<SolSettings, 'get' | 'setWindowGeometry' | 'setAlwaysOnTop'>
  /** The app's OWN renderers that hear state pushes (the main window). The SOL
   *  window is always included by the manager; extension windows never are —
   *  they host third-party bundles (security review M2). */
  allWindows(): ReadonlyArray<Pick<SolWindowHandle, 'isDestroyed' | 'webContents'>>
  scheduler?: {
    setTimeout(fn: () => void, ms: number): unknown
    clearTimeout(handle: unknown): void
  }
}

export interface SolWindowManager {
  /** Create the window (near `near`, else the cursor) or focus the live one. */
  open(opts?: { near?: Point }): void
  focus(): void
  isOpen(): boolean
  close(): void
  setAlwaysOnTop(flag: boolean): void
  pushState(state: SolState): void
  /** False when no SOL window is open. Queued until the renderer is mounted. */
  pushRegion(payload: SolRegionPayload): boolean
  /** The SOL renderer's first state request proves it is mounted: flush a
   *  queued region. Any other sender is ignored. */
  markReady(sender: unknown): void
  /** True for the live SOL window's webContents — the IPC sender gate. */
  isSender(sender: unknown): boolean
}

const clamp = (n: number, lo: number, hi: number): number => Math.min(Math.max(n, lo), hi)

/** Saved geometry on a display that still exists, clamped into its work area;
 *  otherwise the default 420×640 bottom-right of `fallback`'s work area. */
export function placeSolWindow(
  saved: SolWindowGeometry | null,
  displays: DisplaySlice[],
  fallback: DisplaySlice
): Rect {
  const home = saved ? displays.find((d) => d.id === saved.displayId) : undefined
  if (saved && home) {
    const wa = home.workArea
    // Electron enforces the window's own minimum size, so on a work area smaller
    // than it the window IS the minimum — compute x/y against that, not a
    // collapsed clamp (review M6).
    const width = Math.max(SOL_WINDOW_MIN_SIZE.width, Math.min(saved.width, wa.width))
    const height = Math.max(SOL_WINDOW_MIN_SIZE.height, Math.min(saved.height, wa.height))
    return {
      x: clamp(saved.x, wa.x, Math.max(wa.x, wa.x + wa.width - width)),
      y: clamp(saved.y, wa.y, Math.max(wa.y, wa.y + wa.height - height)),
      width,
      height
    }
  }
  const wa = fallback.workArea
  return {
    x: wa.x + wa.width - SOL_WINDOW_DEFAULT_SIZE.width - SOL_WINDOW_MARGIN,
    y: wa.y + wa.height - SOL_WINDOW_DEFAULT_SIZE.height - SOL_WINDOW_MARGIN,
    ...SOL_WINDOW_DEFAULT_SIZE
  }
}

export function createSolWindowManager(deps: SolWindowManagerDeps): SolWindowManager {
  const scheduler = deps.scheduler ?? { setTimeout, clearTimeout }
  let current: SolWindowHandle | null = null
  // A fresh window has no renderer yet; a region pushed before its first
  // state request would be lost, so it waits here (one turn's worth — never disk).
  let ready = false
  let pending: SolRegionPayload | null = null
  const alive = (): boolean => current !== null && !current.isDestroyed()

  const create = (near: Point): void => {
    const display = deps.screen.getDisplayNearestPoint(near)
    const bounds = placeSolWindow(deps.settings.get().window, deps.screen.getAllDisplays(), display)
    const win = deps.createWindow(bounds, deps.settings.get().alwaysOnTop)
    current = win
    ready = false
    pending = null
    let timer: unknown = null
    const save = (): void => {
      timer = null
      if (win.isDestroyed()) return
      const b = win.getBounds()
      const d = deps.screen.getDisplayNearestPoint({ x: b.x + b.width / 2, y: b.y + b.height / 2 })
      deps.settings.setWindowGeometry({ ...b, displayId: d.id })
    }
    const scheduleSave = (): void => {
      if (timer !== null) scheduler.clearTimeout(timer)
      timer = scheduler.setTimeout(save, GEOMETRY_SAVE_DEBOUNCE_MS)
    }
    win.on('move', scheduleSave)
    win.on('resize', scheduleSave)
    win.on('close', () => {
      if (timer === null) return
      scheduler.clearTimeout(timer)
      save()
    })
    win.on('closed', () => {
      if (timer !== null) scheduler.clearTimeout(timer)
      if (current === win) current = null
      pending = null // ephemeral by construction: a region never outlives its window
      ready = false
    })
  }

  return {
    open(opts) {
      if (alive()) {
        current?.focus()
        return
      }
      create(opts?.near ?? deps.screen.getCursorScreenPoint())
    },
    focus: () => void (alive() && current?.focus()),
    isOpen: alive,
    close: () => void (alive() && current?.close()),
    setAlwaysOnTop(flag) {
      deps.settings.setAlwaysOnTop(flag)
      if (alive()) current?.setAlwaysOnTop(flag)
    },
    pushState(state) {
      const targets = new Set<Pick<SolWindowHandle, 'isDestroyed' | 'webContents'>>(
        deps.allWindows()
      )
      if (alive() && current !== null) targets.add(current)
      for (const w of targets) {
        if (!w.isDestroyed()) w.webContents.send(SOL_WINDOW_CHANNELS.state, state)
      }
    },
    pushRegion(payload) {
      if (!alive() || current === null) return false
      if (ready) current.webContents.send(SOL_WINDOW_CHANNELS.region, payload)
      else pending = payload
      return true
    },
    markReady(sender) {
      if (!alive() || current === null || current.webContents !== sender) return
      ready = true
      if (pending !== null) current.webContents.send(SOL_WINDOW_CHANNELS.region, pending)
      pending = null
    },
    isSender: (sender) => alive() && current?.webContents === sender
  }
}

export interface SolIpcDeps {
  windows: Pick<SolWindowManager, 'open' | 'setAlwaysOnTop' | 'markReady'>
  settings: Pick<SolSettings, 'setMode' | 'setScreenIntelligence' | 'setHotkeys'>
  state(): SolState
}

/** Wire the five invokes (channel constants only — see the ratchet). Every
 *  handler answers the current SolState to an allowed sender and null to any
 *  other webContents that gained IPC reach; arguments are validated here. */
export function registerSolIpcHandlers(
  ipc: SolWindowIpc,
  deps: SolIpcDeps,
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
): void {
  const gated =
    (action: (arg: unknown, event: IpcMainInvokeEvent) => void) =>
    (event: IpcMainInvokeEvent, arg?: unknown): SolState | null => {
      if (!isAllowedSender(event)) return null
      action(arg, event)
      return deps.state()
    }
  const c = SOL_WINDOW_CHANNELS
  ipc.handle(
    c.getState,
    gated((_arg, event) => deps.windows.markReady(event.sender))
  )
  ipc.handle(
    c.open,
    gated(() => deps.windows.open())
  )
  ipc.handle(
    c.setMode,
    gated((mode) => {
      if (mode === 'guide' || mode === 'do') deps.settings.setMode(mode)
    })
  )
  ipc.handle(
    c.setScreenIntelligence,
    gated((on) => {
      if (typeof on === 'boolean') deps.settings.setScreenIntelligence(on)
    })
  )
  ipc.handle(
    c.setAlwaysOnTop,
    gated((on) => {
      if (typeof on === 'boolean') deps.windows.setAlwaysOnTop(on)
    })
  )
  ipc.handle(
    c.setHotkeys,
    gated((on) => {
      if (typeof on === 'boolean') deps.settings.setHotkeys(on)
    })
  )
}

/** The real SOL window: same renderer, #/sol-window route, CTR-06 wire. */
export function createSolBrowserWindow(
  bounds: Rect,
  alwaysOnTop: boolean,
  ipc: WireIpc,
  icon?: string
): BrowserWindow {
  const win = new BrowserWindow({
    ...SOL_WINDOW_OPTIONS,
    ...bounds,
    alwaysOnTop,
    ...(icon ? { icon } : {}),
    webPreferences: {
      ...SOL_WINDOW_WEB_PREFERENCES,
      preload: join(__dirname, '../preload/index.js')
    }
  })
  // SEC-H1: the app's most exposed surface gets the main window's guards —
  // window.open goes to the system browser, and in-app navigation may not
  // leave the renderer bundle.
  win.webContents.setWindowOpenHandler(externalOpenHandler((url) => shell.openExternal(url)))
  win.webContents.on('will-navigate', (event, url) => {
    const current = win.webContents.getURL().split('#')[0]
    if (current && !url.startsWith(current)) event.preventDefault()
  })
  // SEC-M2: a (possibly always-on-top) window whose renderer died must not
  // float over everything with a dead body — close it.
  win.webContents.on('render-process-gone', () => {
    if (!win.isDestroyed()) win.close()
  })
  win.on('ready-to-show', () => win.show())
  attachOrbOverlayWire(win, ipc)
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#/sol-window`)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash: '/sol-window' })
  }
  return win
}
