// SOLX-02: the app's SECOND BrowserWindow — the detached, always-on-top SOL
// orb. The registry/teardown logic is injected-structural (the companion /
// orbOverlayWire testing pattern); the thin BrowserWindow shell lives in
// createSolBrowserWindow and is exercised on the COWORK QA checklist.
//
// The detached window loads the same renderer at the #/orb hash route and gets
// the CTR-06 orb↔overlay wire attached at creation, so the detached orb owns
// the handoff seam; the wire tears itself down on 'closed'.
import { BrowserWindow, shell, type IpcMainInvokeEvent } from 'electron'
import { externalOpenHandler } from '../externalUrl'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import { attachOrbOverlayWire, type WireIpc } from './orbOverlayWire'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'

/** The isolation posture, explicit and asserted — never inherited from an
 *  Electron default that a template bump could flip (SEC-H2). */
export const SOL_WINDOW_WEB_PREFERENCES = {
  sandbox: false, // the preload imports @electron-toolkit/preload, as the main window does
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false
} as const

export const SOL_WINDOW_OPTIONS = {
  width: 380,
  height: 560,
  alwaysOnTop: true,
  frame: false,
  show: false,
  autoHideMenuBar: true
} as const

/** Structural slice of BrowserWindow — just what the registry needs. */
export interface SolWindowHandle {
  isDestroyed(): boolean
  once(event: 'closed', listener: () => void): void
  focus(): void
  close(): void
}

/** Structural slice of ipcMain for invoke registration. */
export interface SolWindowIpc {
  handle(channel: string, listener: (event: IpcMainInvokeEvent) => unknown): void
}

export interface SolWindowState {
  detached: boolean
}

export interface SolWindowManager {
  /** Ensure the detached window exists (create or focus). */
  detach(): SolWindowState
  /** Close the detached window if open; safe when none is. */
  attach(): SolWindowState
  isDetached(): boolean
}

/**
 * One-window registry: at most one detached orb, recreated freely after the
 * user closes it directly ('closed' clears the slot — a stale handle must
 * never pin the registry).
 */
export function createSolWindowManager(createWindow: () => SolWindowHandle): SolWindowManager {
  let current: SolWindowHandle | null = null
  const alive = (): boolean => current !== null && !current.isDestroyed()
  return {
    detach() {
      if (alive()) {
        current?.focus()
        return { detached: true }
      }
      const created = createWindow()
      current = created
      created.once('closed', () => {
        if (current === created) current = null
      })
      return { detached: true }
    },
    attach() {
      if (alive()) current?.close()
      current = null
      return { detached: false }
    },
    isDetached: () => alive()
  }
}

/** Wire the detach/attach invokes (channel constants only — see the ratchet). */
export function registerSolWindowHandlers(
  ipc: SolWindowIpc,
  createWindow: () => SolWindowHandle,
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
): SolWindowManager {
  const manager = createSolWindowManager(createWindow)
  // SEC-M1: only the app's own renderer may raise or dismiss an always-on-top
  // window. Any other webContents that gains IPC reach gets the current state
  // and no action. The predicate is required, not defaulted — a forgotten
  // argument must not silently mean "anyone may".
  ipc.handle(SOL_WINDOW_CHANNELS.detach, (event) =>
    isAllowedSender(event) ? manager.detach() : { detached: manager.isDetached() }
  )
  ipc.handle(SOL_WINDOW_CHANNELS.attach, (event) =>
    isAllowedSender(event) ? manager.attach() : { detached: manager.isDetached() }
  )
  return manager
}

/** The real always-on-top orb window: same renderer, #/orb route, CTR-06 wire. */
export function createSolBrowserWindow(ipc: WireIpc): BrowserWindow {
  const win = new BrowserWindow({
    ...SOL_WINDOW_OPTIONS,
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
  // SEC-M2: a frameless always-on-top window whose renderer died has no exit
  // affordance — close it rather than leave it floating over everything.
  win.webContents.on('render-process-gone', () => {
    if (!win.isDestroyed()) win.close()
  })
  win.on('ready-to-show', () => win.show())
  attachOrbOverlayWire(win, ipc)
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#/orb`)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash: '/orb' })
  }
  return win
}
