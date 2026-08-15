// SOLUS-TU-10: the overlay window's posture is per-OS, and each platform fails
// differently — so every branch is asserted here rather than only on whichever
// machine runs the app. The BrowserWindow shell itself (createOverlayBrowserWindow)
// is exercised on the Cowork QA checklist; everything decidable without Electron
// is decided here.
import { describe, it, expect, vi } from 'vitest'
import type { WindowBounds } from '@solus/shared-types'

// Same shape as solWindow.test.ts: the module under test imports electron for
// the BrowserWindow factory, which vitest's node environment cannot load. The
// posture/positioning logic below never touches it.
vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

import {
  OVERLAY_WEB_PREFERENCES,
  OVERLAY_WINDOW_OPTIONS,
  applyOverlayPosture,
  overlayPosture,
  positionOverlayOver,
  type OverlayPlatform,
  type OverlayWindowHandle
} from './overlayWindow'

function fakeWindow(overrides: Partial<OverlayWindowHandle> = {}): OverlayWindowHandle & {
  calls: Record<string, unknown[][]>
} {
  const calls: Record<string, unknown[][]> = {
    setAlwaysOnTop: [],
    setIgnoreMouseEvents: [],
    setVisibleOnAllWorkspaces: [],
    setBounds: []
  }
  return {
    calls,
    setAlwaysOnTop: (...args: unknown[]) => void calls.setAlwaysOnTop.push(args),
    setIgnoreMouseEvents: (...args: unknown[]) => void calls.setIgnoreMouseEvents.push(args),
    setVisibleOnAllWorkspaces: (...args: unknown[]) =>
      void calls.setVisibleOnAllWorkspaces.push(args),
    setBounds: (...args: unknown[]) => void calls.setBounds.push(args),
    isDestroyed: () => false,
    ...overrides
  } as OverlayWindowHandle & { calls: Record<string, unknown[][]> }
}

describe('overlay window isolation posture', () => {
  // These are security defaults, not preferences: an Electron template bump that
  // flipped one silently would hand the least-trustworthy window in the app more
  // power than the main one.
  it('keeps the renderer isolated and node-free', () => {
    expect(OVERLAY_WEB_PREFERENCES.contextIsolation).toBe(true)
    expect(OVERLAY_WEB_PREFERENCES.nodeIntegration).toBe(false)
    expect(OVERLAY_WEB_PREFERENCES.webviewTag).toBe(false)
  })

  it('is chrome-less, inert, and never steals focus from the tool being driven', () => {
    expect(OVERLAY_WINDOW_OPTIONS.transparent).toBe(true)
    expect(OVERLAY_WINDOW_OPTIONS.frame).toBe(false)
    expect(OVERLAY_WINDOW_OPTIONS.alwaysOnTop).toBe(true)
    // The overlay narrates an action the user performs in ANOTHER app; taking
    // focus would interrupt the very thing it is describing.
    expect(OVERLAY_WINDOW_OPTIONS.focusable).toBe(false)
    expect(OVERLAY_WINDOW_OPTIONS.skipTaskbar).toBe(true)
    expect(OVERLAY_WINDOW_OPTIONS.resizable).toBe(false)
  })
})

describe('overlayPosture (per-OS)', () => {
  it('floats above full-screen apps on every platform', () => {
    // CAD tools are normally run full-screen; a lower level means the overlay
    // is simply invisible where it matters most.
    for (const platform of ['darwin', 'win32', 'linux'] as OverlayPlatform[]) {
      expect(overlayPosture(platform).alwaysOnTopLevel).toBe('screen-saver')
    }
  })

  it('forwards mouse events on Windows and macOS so hover still works underneath', () => {
    expect(overlayPosture('win32').forwardMouseEvents).toBe(true)
    expect(overlayPosture('darwin').forwardMouseEvents).toBe(true)
  })

  it('follows the user across Spaces on macOS only', () => {
    // Without this the overlay is stranded on the Space it was born in while
    // the tool window moves to another.
    expect(overlayPosture('darwin').visibleOnAllWorkspaces).toBe(true)
    expect(overlayPosture('win32').visibleOnAllWorkspaces).toBe(false)
    expect(overlayPosture('linux').visibleOnAllWorkspaces).toBe(false)
  })
})

describe('applyOverlayPosture', () => {
  it('makes the window click-through — it annotates, it never intercepts', () => {
    const win = fakeWindow()
    applyOverlayPosture(win, 'linux')
    expect(win.calls.setIgnoreMouseEvents[0][0]).toBe(true)
  })

  it('requests the platform stacking level', () => {
    const win = fakeWindow()
    applyOverlayPosture(win, 'darwin')
    expect(win.calls.setAlwaysOnTop[0]).toEqual([true, 'screen-saver'])
  })

  it('only asks for all-Spaces visibility on macOS', () => {
    const mac = fakeWindow()
    applyOverlayPosture(mac, 'darwin')
    expect(mac.calls.setVisibleOnAllWorkspaces).toHaveLength(1)

    const linux = fakeWindow()
    applyOverlayPosture(linux, 'linux')
    expect(linux.calls.setVisibleOnAllWorkspaces).toHaveLength(0)
  })

  it('survives a platform whose window lacks the optional Spaces API', () => {
    const win = fakeWindow({ setVisibleOnAllWorkspaces: undefined })
    expect(() => applyOverlayPosture(win, 'darwin')).not.toThrow()
  })
})

describe('positionOverlayOver', () => {
  const BOUNDS: WindowBounds = { x: 100, y: 200, width: 800, height: 600 }

  it('places the overlay on the tool window in OS pixels, unscaled', () => {
    // CTR-06 WindowBounds are already OS pixels — scaling them here would put
    // the annotation next to the control instead of on it.
    const win = fakeWindow()
    expect(positionOverlayOver(win, BOUNDS)).toBe(true)
    expect(win.calls.setBounds[0][0]).toEqual(BOUNDS)
  })

  it('is a no-op on a destroyed window rather than a crash', () => {
    // `reposition` races window teardown by nature: the tool can close while a
    // move is in flight, and that must not take the main process down.
    const setBounds = vi.fn()
    const win = fakeWindow({ isDestroyed: () => true, setBounds })
    expect(positionOverlayOver(win, BOUNDS)).toBe(false)
    expect(setBounds).not.toHaveBeenCalled()
  })
})
