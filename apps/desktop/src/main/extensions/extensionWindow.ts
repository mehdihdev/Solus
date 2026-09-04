// SOLUSDEV-235 / EXT-05 — the extension WINDOW host (ADR-035 §1: "window
// views host the same frame in a second BrowserWindow"). The window loads the
// app's own renderer at #/ext-window/<id> — trusted code that owns the
// sandboxed iframe and the bridge — with the main window's preload and
// isolation posture, never the extension content directly. One window per
// extension id; size clamped to the manifest's px range; window.open goes to
// the system browser over https only; in-app navigation may not leave the
// renderer document. Registry logic is structural (solWindow.ts pattern), the
// BrowserWindow shell is on the QA checklist.
import { MANIFEST_LIMITS } from '@solus/shared-types'
import { BrowserWindow, shell } from 'electron'
import { is } from '@electron-toolkit/utils'
import { join } from 'path'
import { externalOpenHandler } from '../externalUrl'

/** Explicit and asserted — never inherited from an Electron default. */
export const EXT_WINDOW_WEB_PREFERENCES = {
  sandbox: false, // the preload imports @electron-toolkit/preload, as the main window does
  contextIsolation: true,
  nodeIntegration: false,
  webviewTag: false
} as const

export const EXT_WINDOW_SIZE = {
  min: MANIFEST_LIMITS.windowMinPx,
  max: MANIFEST_LIMITS.windowMaxPx,
  defaultWidth: 960,
  defaultHeight: 640
} as const

const FALLBACK_TITLE = 'Extension'
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f]/g

export interface ExtensionWindowSpec {
  readonly id: string
  readonly version: string
  readonly title: string
  readonly width: number
  readonly height: number
}

function clampPx(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(EXT_WINDOW_SIZE.max, Math.max(EXT_WINDOW_SIZE.min, Math.floor(value)))
}

export function clampWindowSize(size: { width?: unknown; height?: unknown }): {
  width: number
  height: number
} {
  return {
    width: clampPx(size.width, EXT_WINDOW_SIZE.defaultWidth),
    height: clampPx(size.height, EXT_WINDOW_SIZE.defaultHeight)
  }
}

/** The manifest's window title, renderer-supplied: control characters out,
 *  whitespace collapsed, contract length cap, fallback when empty. */
export function sanitizeWindowTitle(title: unknown): string {
  if (typeof title !== 'string') return FALLBACK_TITLE
  const clean = title.replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim()
  return clean.length === 0 ? FALLBACK_TITLE : clean.slice(0, MANIFEST_LIMITS.windowTitle)
}

export function extensionWindowHash(id: string): string {
  return `/ext-window/${id}`
}

/** Only hash changes on the SAME renderer document are in-app navigation. */
export function isWithinRendererOrigin(currentUrl: string, targetUrl: string): boolean {
  const base = currentUrl.split('#')[0]
  return base !== undefined && base.length > 0 && targetUrl.split('#')[0] === base
}

/** Structural slice of BrowserWindow — what the registry needs. */
export interface ExtensionWindowHandle {
  /** The window's webContents identity, for the IPC sender gate (SEC-M3). */
  readonly webContents: unknown
  isDestroyed(): boolean
  once(event: 'closed', listener: () => void): void
  focus(): void
  close(): void
}

export type OpenWindowResult = { ok: true; created: boolean } | { ok: false }

export interface ExtensionWindowManager {
  /** Create the window for `spec.id`, or focus the live one. */
  open(spec: ExtensionWindowSpec): OpenWindowResult
  isOpen(id: string): boolean
  /** SEC-M3: true only for the webContents of a LIVE window this manager created. */
  isSender(sender: unknown): boolean
  closeAll(): void
}

export function createExtensionWindowManager(
  create: (spec: ExtensionWindowSpec) => ExtensionWindowHandle
): ExtensionWindowManager {
  const windows = new Map<string, ExtensionWindowHandle>()
  const live = (id: string): ExtensionWindowHandle | null => {
    const win = windows.get(id)
    return win !== undefined && !win.isDestroyed() ? win : null
  }
  return {
    open(spec) {
      const existing = live(spec.id)
      if (existing) {
        existing.focus()
        return { ok: true, created: false }
      }
      let created: ExtensionWindowHandle
      try {
        created = create(spec)
      } catch {
        return { ok: false }
      }
      windows.set(spec.id, created)
      created.once('closed', () => {
        if (windows.get(spec.id) === created) windows.delete(spec.id)
      })
      return { ok: true, created: true }
    },
    isOpen: (id) => live(id) !== null,
    isSender: (sender) =>
      [...windows.keys()].some((id) => {
        const win = live(id)
        return win !== null && sender === win.webContents
      }),
    closeAll() {
      for (const id of [...windows.keys()]) live(id)?.close()
      windows.clear()
    }
  }
}

/** The real second BrowserWindow: same renderer, #/ext-window/<id> route. */
export function createExtensionBrowserWindow(spec: ExtensionWindowSpec): BrowserWindow {
  const win = new BrowserWindow({
    width: spec.width,
    height: spec.height,
    minWidth: EXT_WINDOW_SIZE.min,
    minHeight: EXT_WINDOW_SIZE.min,
    title: spec.title,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      ...EXT_WINDOW_WEB_PREFERENCES,
      preload: join(__dirname, '../preload/index.js')
    }
  })
  // The title is ours (manifest, sanitized) — a page-chosen title is ignored.
  win.webContents.on('page-title-updated', (event) => event.preventDefault())
  win.webContents.setWindowOpenHandler(externalOpenHandler((url) => shell.openExternal(url)))
  win.webContents.on('will-navigate', (event, url) => {
    if (!isWithinRendererOrigin(win.webContents.getURL(), url)) event.preventDefault()
  })
  win.webContents.on('will-attach-webview', (event) => event.preventDefault())
  win.on('ready-to-show', () => win.show())
  const hash = extensionWindowHash(spec.id)
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#${hash}`)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash })
  }
  return win
}
