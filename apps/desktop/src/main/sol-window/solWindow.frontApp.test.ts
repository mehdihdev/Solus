// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2; wireflow
// sol-window.md "slice 4" step 1): the summon gate runs BEFORE the pill is
// shown or focused, and the front-app snapshot reaches the SOL window only
// (SOL_WINDOW_CHANNELS.frontApp), queued until its renderer is mounted.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'
import { createSolWindowManager, type Rect, type SolWindowHandle } from './solWindow'
import type { SolFrontApp } from '../drive/frontAppShape'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

const WA = { x: 0, y: 0, width: 1920, height: 1040 }
const FRONT: SolFrontApp = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd'
}

interface Fake {
  handle: SolWindowHandle
  log: string[]
  sent: Array<{ channel: string; payload: unknown }>
}

function fakeWindow(bounds: Rect, log: string[]): Fake {
  let visible = true
  let rect = bounds
  const sent: Fake['sent'] = []
  return {
    log,
    sent,
    handle: {
      isDestroyed: () => false,
      on: () => undefined,
      focus: () => void log.push('focus'),
      show: () => {
        visible = true
        log.push('show')
      },
      hide: () => void (visible = false),
      isVisible: () => visible,
      close: () => undefined,
      getBounds: () => rect,
      setBounds: (r) => void (rect = r),
      webContents: { send: (channel, payload) => void sent.push({ channel, payload }) }
    }
  }
}

function harness(): {
  manager: ReturnType<typeof createSolWindowManager>
  windows: Fake[]
  log: string[]
  main: Fake
} {
  const log: string[] = []
  const windows: Fake[] = []
  const main = fakeWindow(WA, [])
  const manager = createSolWindowManager({
    createWindow: (bounds) => {
      log.push('create')
      const w = fakeWindow(bounds, log)
      windows.push(w)
      return w.handle
    },
    screen: {
      getCursorScreenPoint: () => ({ x: 10, y: 10 }),
      getDisplayNearestPoint: () => ({ id: 1, workArea: WA })
    },
    allWindows: () => [main.handle]
  })
  return { manager, windows, log, main }
}

const frontPushes = (w: Fake): unknown[] =>
  w.sent.filter((m) => m.channel === SOL_WINDOW_CHANNELS.frontApp).map((m) => m.payload)

beforeEach(() => void vi.useFakeTimers())
afterEach(() => void vi.useRealTimers())

describe('summon gate', () => {
  it('creates nothing and focuses nothing until the gate resolves', async () => {
    const h = harness()
    let release: () => void = () => undefined
    h.manager.setSummonGate(() => new Promise<void>((r) => (release = r)))
    h.manager.open()
    expect(h.log).toEqual([])
    release()
    await vi.advanceTimersByTimeAsync(0)
    expect(h.log).toEqual(['create']) // a new window shows itself on ready-to-show
  })

  it('re-summoning a hidden pill shows and focuses it only after the gate', async () => {
    const h = harness()
    h.manager.open() // no gate yet: synchronous, as before
    h.manager.hide()
    await vi.advanceTimersByTimeAsync(1000)
    h.log.length = 0
    let release: () => void = () => undefined
    h.manager.setSummonGate(() => new Promise<void>((r) => (release = r)))
    h.manager.open()
    expect(h.log).toEqual([])
    release()
    await vi.advanceTimersByTimeAsync(0)
    expect(h.log).toEqual(['show', 'focus'])
  })

  it('a second summon while the gate runs is coalesced; a failing gate still opens', async () => {
    const h = harness()
    const gate = vi.fn(() => Promise.reject(new Error('x')))
    h.manager.setSummonGate(gate)
    h.manager.open()
    h.manager.toggle()
    await vi.advanceTimersByTimeAsync(0)
    expect(gate).toHaveBeenCalledTimes(1)
    expect(h.windows).toHaveLength(1)
  })

  it('setSummonGate(null) restores the synchronous open', () => {
    const h = harness()
    h.manager.setSummonGate(async () => undefined)
    h.manager.setSummonGate(null)
    h.manager.open()
    expect(h.log).toEqual(['create']) // a new window shows itself on ready-to-show
  })
})

describe('pushFrontApp', () => {
  it('goes to the SOL window only, queued until its renderer is mounted', () => {
    const h = harness()
    h.manager.open()
    const w = h.windows[0]
    h.manager.pushFrontApp(FRONT)
    expect(frontPushes(w)).toEqual([])
    h.manager.markReady(w.handle.webContents)
    expect(frontPushes(w)).toEqual([FRONT])
    h.manager.pushFrontApp(null)
    expect(frontPushes(w)).toEqual([FRONT, null])
    h.manager.markReady(w.handle.webContents) // already ready: no repeat
    expect(frontPushes(w)).toHaveLength(2)
    expect(frontPushes(h.main)).toEqual([])
  })

  it('a snapshot pushed before any window exists reaches the first one when it mounts', () => {
    const h = harness()
    h.manager.pushFrontApp(FRONT)
    h.manager.open()
    h.manager.markReady(h.windows[0].handle.webContents)
    expect(frontPushes(h.windows[0])).toEqual([FRONT])
  })

  it('nothing is sent at mount when no snapshot was ever pushed', () => {
    const h = harness()
    h.manager.open()
    h.manager.markReady(h.windows[0].handle.webContents)
    expect(frontPushes(h.windows[0])).toEqual([])
  })
})
