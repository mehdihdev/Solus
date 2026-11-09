// SOLUSDEV-319 drive slice 3: the real outline strip — a solid amber,
// content-free BrowserWindow (no page, no preload) that never focuses and lets
// every click through. Thin glue over driveOutline's OutlineStrip.
import { BrowserWindow } from 'electron'
import { SOLUS_ACCENTS } from '../../renderer/src/theme/tokens.constants'
import type { OutlineStrip } from './driveOutline'

/** The amber/ember accent from the design tokens. */
export const DRIVE_OUTLINE_COLOR = SOLUS_ACCENTS.amber.c

export const DRIVE_STRIP_OPTIONS = {
  frame: false,
  show: false,
  focusable: false,
  skipTaskbar: true,
  hiddenInMissionControl: true,
  hasShadow: false,
  resizable: false,
  movable: false,
  minimizable: false,
  maximizable: false,
  fullscreenable: false,
  alwaysOnTop: true,
  enableLargerThanScreen: true,
  acceptFirstMouse: false,
  backgroundColor: DRIVE_OUTLINE_COLOR,
  title: 'SOL outline',
  webPreferences: {
    sandbox: true,
    contextIsolation: true,
    nodeIntegration: false,
    webviewTag: false,
    javascript: false
  }
} as const

export interface StripPostureHandle {
  setIgnoreMouseEvents(ignore: boolean): void
  setAlwaysOnTop(flag: boolean, level: 'screen-saver'): void
  setVisibleOnAllWorkspaces(visible: boolean, options: { visibleOnFullScreen: boolean }): void
}

export function applyStripPosture(win: StripPostureHandle): void {
  win.setIgnoreMouseEvents(true)
  // 'screen-saver' floats above a full-screen KiCad, as the overlay does.
  win.setAlwaysOnTop(true, 'screen-saver')
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
}

export function createOutlineStrip(): OutlineStrip {
  const win = new BrowserWindow({ ...DRIVE_STRIP_OPTIONS, width: 1, height: 1 })
  applyStripPosture(win)
  return win
}
