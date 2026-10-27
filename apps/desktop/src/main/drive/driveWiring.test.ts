// SOLUSDEV-319 drive slice 3: the glue installs the companion's drive
// resolver, routes its geometry to the outline, and registers the invokes.
import { describe, expect, it, vi } from 'vitest'

const companion = vi.hoisted(() => ({
  resolver: null as ((id: string | null) => unknown) | null,
  window: null as ((b: unknown) => void) | null,
  notify: vi.fn()
}))

vi.mock('electron', () => ({
  app: { isPackaged: false, getAppPath: () => '/nowhere', getPath: () => '/tmp' },
  BrowserWindow: vi.fn()
}))
vi.mock('../companion', () => ({
  notifyCompanionDriveChanged: companion.notify,
  setCompanionDriveResolver: (r: (id: string | null) => unknown) => void (companion.resolver = r),
  onCompanionDriveWindow: (l: (b: unknown) => void) => void (companion.window = l)
}))

import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import type { SolSettings } from '../solSettings'
import { startDrive } from './driveWiring'

function settings(): SolSettings {
  const listeners = new Set<(s: ReturnType<SolSettings['get']>) => void>()
  let state = {
    actionMode: 'guide' as const,
    screenIntelligence: false,
    hotkeys: true,
    drive: true
  }
  return {
    get: () => state,
    setMode: () => undefined,
    toggleMode: () => 'guide',
    setScreenIntelligence: () => undefined,
    setHotkeys: () => undefined,
    setDrive: (drive) => {
      state = { ...state, drive }
      for (const l of listeners) l(state)
    },
    onChange: (cb) => {
      listeners.add(cb)
      return () => void listeners.delete(cb)
    }
  }
}

describe('startDrive', () => {
  it('wires the resolver, the invokes and the quiet period', async () => {
    const handlers = new Map<string, (...args: unknown[]) => unknown>()
    const broadcast = vi.fn()
    const drive = startDrive({
      ipc: { handle: (c, l) => void handlers.set(c, l as (...args: unknown[]) => unknown) },
      settings: settings(),
      windows: { broadcast },
      isAllowedSender: () => true
    })
    // No dev helper under /nowhere (and not macOS on CI): never drive.
    expect(companion.resolver?.('p')).toBeNull()
    expect(handlers.has(SOL_WINDOW_CHANNELS.getDriveStatus)).toBe(true)
    const status = (await handlers.get(SOL_WINDOW_CHANNELS.getDriveStatus)?.({})) as {
      available: boolean
    }
    expect(status.available).toBe(false)
    expect(broadcast).toHaveBeenCalledWith(SOL_WINDOW_CHANNELS.driveStatus, status)

    expect(drive.isQuiet()).toBe(false)
    handlers.get(SOL_WINDOW_CHANNELS.setDriving)?.({}, true)
    expect(drive.isQuiet()).toBe(true)
    handlers.get(SOL_WINDOW_CHANNELS.setDriving)?.({}, false)
    drive.dispose()
  })
})
