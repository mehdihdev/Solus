// SOLUSDEV-319 drive slice 3: an outline strip must be inert — never focus,
// never take a click, never load content, never show in the Dock/Mission Control.
import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ BrowserWindow: vi.fn() }))

import { DRIVE_OUTLINE_COLOR, DRIVE_STRIP_OPTIONS, applyStripPosture } from './driveOutlineWindow'

describe('DRIVE_STRIP_OPTIONS', () => {
  it('is frameless, unfocusable, out of the taskbar and Mission Control, and content-free', () => {
    expect(DRIVE_STRIP_OPTIONS).toMatchObject({
      frame: false,
      focusable: false,
      skipTaskbar: true,
      hiddenInMissionControl: true,
      show: false,
      hasShadow: false,
      resizable: false,
      movable: false,
      alwaysOnTop: true,
      backgroundColor: DRIVE_OUTLINE_COLOR,
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false }
    })
    expect('preload' in DRIVE_STRIP_OPTIONS.webPreferences).toBe(false)
  })

  it('uses the amber accent token', () => {
    expect(DRIVE_OUTLINE_COLOR).toBe('#E5A43B')
  })
})

describe('applyStripPosture', () => {
  it('click-through, above full-screen apps, on every Space', () => {
    const win = {
      setIgnoreMouseEvents: vi.fn(),
      setAlwaysOnTop: vi.fn(),
      setVisibleOnAllWorkspaces: vi.fn()
    }
    applyStripPosture(win)
    expect(win.setIgnoreMouseEvents).toHaveBeenCalledWith(true)
    expect(win.setAlwaysOnTop).toHaveBeenCalledWith(true, 'screen-saver')
    expect(win.setVisibleOnAllWorkspaces).toHaveBeenCalledWith(true, { visibleOnFullScreen: true })
  })
})
