// SOLUSDEV-252 S3: the renderer-facing `window.solus.sol` surface — a pure
// factory over an injected ipcRenderer (the orbOverlayBridge.test.ts pattern).
import { describe, it, expect, vi } from 'vitest'
import type { IpcRenderer } from 'electron'
import { SOL_WINDOW_CHANNELS } from '../main/sol-window/solWindow.constants'
import { createSolBridge, isSolState, type SolBridge, type SolBridgeIpc } from './solBridge'
import type { SolRegionPayload, SolState } from '../main/sol-window/solWindow'

const STATE: SolState = {
  actionMode: 'do',
  screenIntelligence: true,
  hotkeysEnabled: false,
  alwaysOnTop: false,
  capture: { mode: 'available', message: '' },
  hotkeys: null,
  lastRegionRefused: false
}
const REGION: SolRegionPayload = {
  pngBase64: 'AA==',
  contextPngBase64: 'AA==',
  width: 10,
  height: 5,
  source: { app: 'kicad', title: 'x' },
  capturedAt: 1
}

type Listener = (event: unknown, raw: unknown) => void

function fakeIpc(): {
  ipc: SolBridgeIpc
  invoked: Array<{ channel: string; args: unknown[] }>
  emit: (channel: string, raw: unknown) => void
  count: (channel: string) => number
} {
  const invoked: Array<{ channel: string; args: unknown[] }> = []
  const listeners = new Map<string, Set<Listener>>()
  return {
    ipc: {
      invoke: async (channel, ...args) => {
        invoked.push({ channel, args })
        return STATE
      },
      on: (channel, listener) => {
        const set = listeners.get(channel) ?? new Set()
        set.add(listener)
        listeners.set(channel, set)
      },
      removeListener: (channel, listener) => void listeners.get(channel)?.delete(listener)
    },
    invoked,
    emit: (channel, raw) => {
      for (const l of [...(listeners.get(channel) ?? [])]) l({}, raw)
    },
    count: (channel) => listeners.get(channel)?.size ?? 0
  }
}

describe('invokes', () => {
  it('maps each method onto its shared channel constant with its argument', async () => {
    const f = fakeIpc()
    const b = createSolBridge(f.ipc)
    await expect(b.getState()).resolves.toEqual(STATE)
    await b.setMode('guide')
    await b.setScreenIntelligence(true)
    await b.setAlwaysOnTop(false)
    await b.setHotkeys(false)
    await b.open()
    const c = SOL_WINDOW_CHANNELS
    expect(f.invoked).toEqual([
      { channel: c.getState, args: [] },
      { channel: c.setMode, args: ['guide'] },
      { channel: c.setScreenIntelligence, args: [true] },
      { channel: c.setAlwaysOnTop, args: [false] },
      { channel: c.setHotkeys, args: [false] },
      { channel: c.open, args: [] }
    ])
  })
})

describe('pushes', () => {
  it('delivers a well-formed state / region; unsubscribe removes the listener', () => {
    const f = fakeIpc()
    const b = createSolBridge(f.ipc)
    const states: SolState[] = []
    const regions: SolRegionPayload[] = []
    const offState = b.onState((s) => states.push(s))
    const offRegion = b.onRegion((r) => regions.push(r))
    f.emit(SOL_WINDOW_CHANNELS.state, STATE)
    f.emit(SOL_WINDOW_CHANNELS.region, REGION)
    expect(states).toEqual([STATE])
    expect(regions).toEqual([REGION])
    offState()
    offRegion()
    expect(f.count(SOL_WINDOW_CHANNELS.state)).toBe(0)
    expect(f.count(SOL_WINDOW_CHANNELS.region)).toBe(0)
  })

  it('drops malformed pushes at the boundary (IPC is untrusted input)', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const f = fakeIpc()
      const b = createSolBridge(f.ipc)
      const onState = vi.fn()
      const onRegion = vi.fn()
      b.onState(onState)
      b.onRegion(onRegion)
      f.emit(SOL_WINDOW_CHANNELS.state, { ...STATE, actionMode: 'expert' })
      f.emit(SOL_WINDOW_CHANNELS.state, null)
      f.emit(SOL_WINDOW_CHANNELS.region, { ...REGION, pngBase64: 42 })
      f.emit(SOL_WINDOW_CHANNELS.region, { ...REGION, source: 'kicad' })
      expect(onState).not.toHaveBeenCalled()
      expect(onRegion).not.toHaveBeenCalled()
      expect(spy).toHaveBeenCalledTimes(4)
    } finally {
      spy.mockRestore()
    }
  })
})

it('isSolState rejects a state missing hotkeysEnabled', () => {
  expect(isSolState(STATE)).toBe(true)
  expect(isSolState({ ...STATE, hotkeysEnabled: undefined })).toBe(false)
})

it('the structural slice accepts the real ipcRenderer shape', () => {
  const create: (ipc: IpcRenderer) => SolBridge = createSolBridge
  expect(create).toBe(createSolBridge)
})

it('validates native target geometry and uses an argument-free trusted discovery channel', async () => {
  const target = {
    tool: 'kicad',
    windowTitle: 'Board',
    displayId: '1',
    bounds: { x: 0, y: 0, width: 800, height: 600 }
  }
  const invoke = vi.fn().mockResolvedValue(target)
  const bridge = createSolBridge({ ...fakeIpc().ipc, invoke })
  expect(await bridge.getGuideTarget?.()).toEqual(target)
  expect(invoke).toHaveBeenCalledWith(SOL_WINDOW_CHANNELS.guideTarget)
  for (const raw of [
    null,
    { ...target, tool: 'arbitrary' },
    { ...target, bounds: { ...target.bounds, width: -1 } },
    { ...target, bounds: { ...target.bounds, x: NaN } }
  ]) {
    invoke.mockResolvedValue(raw)
    expect(await bridge.getGuideTarget?.()).toBeNull()
  }
})
