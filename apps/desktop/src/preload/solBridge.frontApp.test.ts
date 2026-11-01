// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2): the preload end
// of the front-app snapshot — window.solus.sol.onFrontApp delivers exactly the
// SolFrontApp shape main produces (or null) and drops anything else, so a
// payload carrying bounds, documentDir or a denied app's title never reaches
// the renderer.
import { describe, expect, it, vi } from 'vitest'
import { createSolBridge, type SolBridgeIpc } from './solBridge'
import { SOL_WINDOW_CHANNELS } from '../main/sol-window/solWindow.constants'
import type { SolFrontApp } from '../main/drive/frontAppShape'

type Listener = (event: unknown, raw: unknown) => void

function fakeIpc(): {
  ipc: SolBridgeIpc
  emit: (raw: unknown) => void
  count: () => number
} {
  const listeners = new Map<string, Set<Listener>>()
  return {
    ipc: {
      invoke: async () => null,
      on: (channel, listener) => {
        const set = listeners.get(channel) ?? new Set()
        set.add(listener)
        listeners.set(channel, set)
      },
      removeListener: (channel, listener) => void listeners.get(channel)?.delete(listener)
    },
    emit: (raw) => {
      for (const l of [...(listeners.get(SOL_WINDOW_CHANNELS.frontApp) ?? [])]) l({}, raw)
    },
    count: () => listeners.get(SOL_WINDOW_CHANNELS.frontApp)?.size ?? 0
  }
}

const FRONT: SolFrontApp = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd'
}
const DENIED: SolFrontApp = {
  drivable: false,
  binding: null,
  bundleId: 'com.apple.Terminal',
  name: 'Terminal'
}

describe('onFrontApp', () => {
  it('delivers valid snapshots and null, drops malformed ones, and unsubscribes', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const f = fakeIpc()
      const seen: unknown[] = []
      const off = createSolBridge(f.ipc).onFrontApp?.((front) => seen.push(front))
      f.emit(FRONT)
      f.emit(DENIED)
      f.emit(null)
      f.emit({ ...FRONT, bounds: { x: 0, y: 0, width: 1, height: 1 } })
      f.emit({ ...DENIED, title: 'secret' })
      f.emit({ ...FRONT, pid: 'x' })
      f.emit(undefined)
      expect(seen).toEqual([FRONT, DENIED, null])
      expect(spy).toHaveBeenCalledTimes(4)
      off?.()
      expect(f.count()).toBe(0)
    } finally {
      spy.mockRestore()
    }
  })
})
