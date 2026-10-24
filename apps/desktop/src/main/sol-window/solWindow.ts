import type { ToolWindowRef } from '@solus/shared-types'
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
import type { SolActionMode, SolSettings } from '../solSettings'
import type { CaptureCapability } from '../capture/screenCapture'
import type { CapabilityState } from '../platform/capabilities'
import type { ActiveWindowInfo } from '../capture/activeWindow'
import {
  growPill,
  placePill,
  SOL_PILL_INITIAL_HEIGHT,
  SOL_PILL_WIDTH,
  type Point,
  type Rect
} from './pillGeometry'

export type { Point, Rect } from './pillGeometry'

/** The isolation posture, explicit and asserted — never inherited from an
 *  Electron default that a template bump could flip (SEC-H2). */
export const SOL_WINDOW_WEB_PREFERENCES = {
  sandbox: false, // the preload imports @electron-toolkit/preload, as the main window does
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false
} as const

/** SOLUSDEV-319: the Ember Pill. Frameless and transparent (the renderer draws
 *  the rounded surfaces and their shadow), always on top, sized by main from
 *  the renderer's measured height — never by hand. */
export const SOL_WINDOW_OPTIONS = {
  frame: false,
  transparent: true,
  resizable: false,
  alwaysOnTop: true,
  skipTaskbar: true,
  hasShadow: false,
  width: SOL_PILL_WIDTH,
  height: SOL_PILL_INITIAL_HEIGHT,
  show: false,
  autoHideMenuBar: true,
  title: 'SOL'
} as const

export interface DisplaySlice {
  id: number
  workArea: Rect
}

/** Structural slice of BrowserWindow — just what the manager needs. */
export interface SolWindowHandle {
  isDestroyed(): boolean
  on(event: 'blur' | 'closed', listener: () => void): void
  focus(): void
  show(): void
  hide(): void
  isVisible(): boolean
  close(): void
  getBounds(): Rect
  setBounds(bounds: Rect): void
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
  createWindow(bounds: Rect): SolWindowHandle
  screen: {
    getCursorScreenPoint(): Point
    getDisplayNearestPoint(point: Point): DisplaySlice
  }
  /** The app's OWN renderers that hear state pushes (the main window). The SOL
   *  window is always included by the manager; extension windows never are —
   *  they host third-party bundles (security review M2). */
  allWindows(): ReadonlyArray<Pick<SolWindowHandle, 'isDestroyed' | 'webContents'>>
}

export interface SolWindowManager {
  /** Create the pill (near `near`, else the cursor), re-summon a hidden one
   *  there, or focus a shown one. */
  open(opts?: { near?: Point }): void
  /** Double-tap Ctrl: hide a shown pill, else open. */
  toggle(): void
  /** Esc / blur: hide; the window and its renderer state live on. */
  hide(): void
  /** The renderer's measured content height; main grows the pill upward. */
  resize(height: number): void
  /** A busy pill (streaming, approval parked, plan running) ignores blur. */
  setBusy(busy: boolean): void
  focus(): void
  isOpen(): boolean
  isVisible(): boolean
  close(): void
  pushState(state: SolState): void
  /** False when no SOL window is open. Queued until the renderer is mounted. */
  pushRegion(payload: SolRegionPayload): boolean
  /** The SOL renderer's first state request proves it is mounted: flush a
   *  queued region. Any other sender is ignored. */
  markReady(sender: unknown): void
  /** True for the live SOL window's webContents — the IPC sender gate. */
  isSender(sender: unknown): boolean
}

/** SOLUSDEV-319: where the pointer was at summon, the pill's collapsed
 *  placement there, and the last height the renderer asked for. */
function createPillPlacement(screen: SolWindowManagerDeps['screen']): {
  summon(near: Point, fresh?: boolean): Rect
  grow(height: number): Rect | null
} {
  let anchor: Point = { x: 0, y: 0 }
  let home: Rect | null = null
  let height: number = SOL_PILL_INITIAL_HEIGHT
  const workAreaAt = (p: Point): Rect => screen.getDisplayNearestPoint(p).workArea
  return {
    /** Re-anchor at `near`: the collapsed placement, grown to the current
     *  height — or collapsed, for a `fresh` window. */
    summon(near, fresh = false) {
      if (fresh) height = SOL_PILL_INITIAL_HEIGHT
      const wa = workAreaAt(near)
      anchor = near
      home = placePill(near, wa, { width: SOL_PILL_WIDTH, height: SOL_PILL_INITIAL_HEIGHT })
      return height === SOL_PILL_INITIAL_HEIGHT ? home : growPill(near, home, height, wa)
    },
    grow(next) {
      if (home === null) return null
      height = next
      return growPill(anchor, home, next, workAreaAt(anchor))
    }
  }
}

export function createSolWindowManager(deps: SolWindowManagerDeps): SolWindowManager {
  let current: SolWindowHandle | null = null
  // A fresh window has no renderer yet; a region pushed before its first
  // state request would be lost, so it waits here (one turn's worth — never disk).
  let ready = false
  let pending: SolRegionPayload | null = null
  const placement = createPillPlacement(deps.screen)
  let busy = false
  const alive = (): boolean => current !== null && !current.isDestroyed()

  const create = (near: Point): void => {
    const win = deps.createWindow(placement.summon(near, true))
    current = win
    ready = false
    pending = null
    win.on('blur', () => {
      if (!busy && !win.isDestroyed()) win.hide()
    })
    win.on('closed', () => {
      if (current === win) current = null
      pending = null // ephemeral by construction: a region never outlives its window
      ready = false
      busy = false
    })
  }

  const open = (opts?: { near?: Point }): void => {
    const near = opts?.near ?? deps.screen.getCursorScreenPoint()
    if (!alive() || current === null) return create(near)
    if (!current.isVisible()) {
      current.setBounds(placement.summon(near))
      current.show()
    }
    current.focus()
  }

  return {
    open,
    toggle() {
      if (alive() && current?.isVisible()) current.hide()
      else open()
    },
    hide: () => void (alive() && current?.hide()),
    resize(next) {
      const bounds = alive() ? placement.grow(next) : null
      if (bounds !== null) current?.setBounds(bounds)
    },
    setBusy: (flag) => void (busy = flag),
    focus: () => void (alive() && current?.focus()),
    isOpen: alive,
    isVisible: () => alive() && (current?.isVisible() ?? false),
    close: () => void (alive() && current?.close()),
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
  windows: Pick<SolWindowManager, 'open' | 'markReady' | 'isSender' | 'resize' | 'setBusy' | 'hide'>
  settings: Pick<SolSettings, 'setMode' | 'setScreenIntelligence' | 'setHotkeys'>
  state(): SolState
  guideTarget?(): Promise<ToolWindowRef | null>
  guideScope?(): number | null
  /** Open the capture capability's own settings pane (SOLUSDEV-318). */
  openCaptureSettings?(): void
}

/** Wire the invokes (channel constants only — see the ratchet). Every
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
  const guideScopeMatches = (scope: number): boolean =>
    deps.guideScope?.() === scope && deps.state().actionMode === 'guide'
  ipc.handle(c.guideTarget, async (event) => {
    const scope = deps.guideScope?.()
    if (!isAllowedSender(event) || scope == null || deps.state().actionMode !== 'guide') return null
    const target = await deps.guideTarget?.().catch(() => null)
    return isAllowedSender(event) && guideScopeMatches(scope) ? (target ?? null) : null
  })
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
    c.setHotkeys,
    gated((on) => {
      if (typeof on === 'boolean') deps.settings.setHotkeys(on)
    })
  )
  registerPillIpcHandlers(ipc, deps, isAllowedSender)
  // Any renderer argument is ignored: main opens its own capability's URL.
  ipc.handle(
    c.openCaptureSettings,
    gated(() => deps.openCaptureSettings?.())
  )
}

/** SOLUSDEV-319: the pill's own invokes. The main window is an allowed sender
 *  for the others but must not size, pin open or hide the pill. */
function registerPillIpcHandlers(
  ipc: SolWindowIpc,
  deps: SolIpcDeps,
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
): void {
  const c = SOL_WINDOW_CHANNELS
  // The pill's own top frame only — never a subframe it might one day host.
  const fromPillTopFrame = (event: IpcMainInvokeEvent): boolean =>
    deps.windows.isSender(event.sender) && event.senderFrame === event.sender?.mainFrame
  const pillOnly =
    (action: (arg: unknown) => void) =>
    (event: IpcMainInvokeEvent, arg?: unknown): SolState | null => {
      if (!isAllowedSender(event) || !fromPillTopFrame(event)) return null
      action(arg)
      return deps.state()
    }
  ipc.handle(
    c.resize,
    pillOnly((h) => {
      if (typeof h === 'number' && Number.isFinite(h)) deps.windows.resize(h)
    })
  )
  ipc.handle(
    c.setBusy,
    pillOnly((on) => {
      if (typeof on === 'boolean') deps.windows.setBusy(on)
    })
  )
  ipc.handle(
    c.hide,
    pillOnly(() => deps.windows.hide())
  )
}

/** The real SOL window: same renderer, #/sol-window route, CTR-06 wire. */
export function createSolBrowserWindow(bounds: Rect, ipc: WireIpc, icon?: string): BrowserWindow {
  const win = new BrowserWindow({
    ...SOL_WINDOW_OPTIONS,
    ...bounds,
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
  // SOLUSDEV-319: summoned over whatever is in front, full-screen tools included.
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  win.on('ready-to-show', () => win.show())
  attachOrbOverlayWire(win, ipc)
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#/sol-window`)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash: '/sol-window' })
  }
  return win
}
