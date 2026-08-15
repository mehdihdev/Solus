// SOLUS-TU-10 / SOLX-03: the Guide overlay window — the app's THIRD BrowserWindow.
//
// A transparent, click-through, always-on-top surface positioned over an
// EXTERNAL application's window, so SOL can point at a real control instead of
// describing it. The orb hands off through the CTR-06 contract
// (docs/contracts/orb-overlay.md); this module owns only the window itself.
//
// RESEARCH-GRADE (per SOLUSDEV-213). The posture below is per-OS and each
// platform fails differently: transparency needs a compositor on Linux/X11,
// macOS needs a panel-level window to float above full-screen apps, and
// click-through needs the `forward` flag on Windows to keep hover working in the
// app underneath. `overlayPosture()` is a pure function precisely so those
// per-OS decisions are asserted in tests on every platform, rather than only on
// whichever machine happens to run the app.
//
// What this module deliberately does NOT do: decide WHETHER to show an
// annotation. That is the confidence gate in `overlayController.ts` — a window
// that positions itself correctly but points at a guess is the failure SOLX-03
// exists to prevent.
import { BrowserWindow } from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import type { WindowBounds } from '@solus/shared-types'
import { attachOrbOverlayWire, type WireIpc } from '../sol-window/orbOverlayWire'

/** The isolation posture, explicit and asserted — never inherited from an
 *  Electron default a template bump could flip (mirrors SOL_WINDOW_WEB_PREFERENCES). */
export const OVERLAY_WEB_PREFERENCES = {
  sandbox: false, // the preload imports @electron-toolkit/preload, as every window does
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false
} as const

/** Chrome-less and inert: it must look like an annotation, not a window. */
export const OVERLAY_WINDOW_OPTIONS = {
  transparent: true,
  frame: false,
  show: false,
  alwaysOnTop: true,
  skipTaskbar: true,
  hasShadow: false,
  resizable: false,
  movable: false,
  minimizable: false,
  maximizable: false,
  fullscreenable: false,
  // Never steal focus from the tool the user is actually driving. An overlay
  // that takes focus interrupts the very action it is narrating.
  focusable: false,
  acceptFirstMouse: false
} as const

export type OverlayPlatform = 'darwin' | 'win32' | 'linux'

/** Per-OS window posture. Pure so every branch is asserted on every platform. */
export interface OverlayPosture {
  /** `setAlwaysOnTop(true, level)` — the stacking level to request. */
  alwaysOnTopLevel: 'screen-saver' | 'pop-up-menu' | 'floating'
  /** `setIgnoreMouseEvents(true, { forward })` — forward keeps hover alive in
   *  the app underneath, which Windows needs and the others tolerate. */
  forwardMouseEvents: boolean
  /** macOS only: follow the user across Spaces, else the overlay is stranded
   *  on the Space it was born in while the tool moves. */
  visibleOnAllWorkspaces: boolean
}

export function overlayPosture(platform: OverlayPlatform): OverlayPosture {
  if (platform === 'darwin') {
    // 'screen-saver' is the only level that floats above a full-screen app,
    // which is exactly how CAD tools are normally used.
    return {
      alwaysOnTopLevel: 'screen-saver',
      forwardMouseEvents: true,
      visibleOnAllWorkspaces: true
    }
  }
  if (platform === 'win32') {
    return {
      alwaysOnTopLevel: 'screen-saver',
      forwardMouseEvents: true,
      visibleOnAllWorkspaces: false
    }
  }
  // Linux/X11: 'screen-saver' is honoured by most WMs; transparency requires a
  // running compositor, and without one the window renders opaque black rather
  // than failing — the controller's degradation path is what keeps that from
  // covering the user's tool.
  return {
    alwaysOnTopLevel: 'screen-saver',
    forwardMouseEvents: false,
    visibleOnAllWorkspaces: false
  }
}

/** Structural slice of BrowserWindow — just what the posture/positioning needs,
 *  so tests need no Electron. */
export interface OverlayWindowHandle {
  setAlwaysOnTop(flag: boolean, level?: string): void
  setIgnoreMouseEvents(ignore: boolean, options?: { forward: boolean }): void
  setVisibleOnAllWorkspaces?(visible: boolean): void
  setBounds(bounds: WindowBounds): void
  isDestroyed(): boolean
}

/** Apply the per-OS posture to a window. Separated from creation so the real
 *  window and a test double take the identical path. */
export function applyOverlayPosture(win: OverlayWindowHandle, platform: OverlayPlatform): void {
  const posture = overlayPosture(platform)
  win.setAlwaysOnTop(true, posture.alwaysOnTopLevel)
  win.setIgnoreMouseEvents(true, { forward: posture.forwardMouseEvents })
  if (posture.visibleOnAllWorkspaces) win.setVisibleOnAllWorkspaces?.(true)
}

/**
 * Move the overlay to cover a tool window.
 *
 * `WindowBounds` are OS pixels in the CTR-06 contract, which is what `setBounds`
 * wants — no scaling here. A destroyed window is a no-op rather than a throw:
 * `reposition` races window teardown by nature (the tool can close while a move
 * is in flight), and that race must not take the main process down.
 */
export function positionOverlayOver(win: OverlayWindowHandle, bounds: WindowBounds): boolean {
  if (win.isDestroyed()) return false
  win.setBounds(bounds)
  return true
}

/** The real overlay window: same renderer bundle, #/overlay route, CTR-06 wire. */
export function createOverlayBrowserWindow(
  ipc: WireIpc,
  bounds: WindowBounds,
  platform: OverlayPlatform = process.platform as OverlayPlatform
): BrowserWindow {
  const win = new BrowserWindow({
    ...OVERLAY_WINDOW_OPTIONS,
    ...bounds,
    webPreferences: {
      ...OVERLAY_WEB_PREFERENCES,
      preload: join(__dirname, '../preload/index.js')
    }
  })
  applyOverlayPosture(win as unknown as OverlayWindowHandle, platform)
  // An overlay whose renderer died is worse than no overlay: it is an opaque
  // rectangle pinned over the user's tool with no way to dismiss it.
  win.webContents.on('render-process-gone', () => {
    if (!win.isDestroyed()) win.close()
  })
  // No window.open and no navigation away from the bundle — the overlay is the
  // least trustworthy end of the CTR-06 channel (contract §"trust"), so it gets
  // the tightest surface of any window in the app.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', (event) => event.preventDefault())
  win.on('ready-to-show', () => win.showInactive())
  attachOrbOverlayWire(win, ipc)
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#/overlay`)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash: '/overlay' })
  }
  return win
}
