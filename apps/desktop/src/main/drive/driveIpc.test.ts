// SOLUSDEV-319 drive slice 3: the drive invokes answer only an allowed sender
// and validate their argument before acting. Turning drive ON and asking macOS
// for the grants are consent actions: the main window only (Phase 4 review).
import { describe, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import { registerDriveIpcHandlers, type DriveIpcDeps } from './driveIpc'
import type { DriveStatus } from './driveStatus'

const STATUS: DriveStatus = {
  enabled: false,
  available: false,
  reason: 'no_folder',
  trust: null,
  unsignedDev: false
}
type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown

function sender(id: number): {
  event: IpcMainInvokeEvent
  destroy: () => void
  listeners: () => number
} {
  const destroyed: Array<() => void> = []
  const contents = { id, once: (_e: 'destroyed', cb: () => void) => void destroyed.push(cb) }
  return {
    event: { sender: contents } as unknown as IpcMainInvokeEvent,
    destroy: () => destroyed.splice(0).forEach((cb) => cb()),
    listeners: () => destroyed.length
  }
}

const MAIN = sender(1)
const PILL = sender(2)

function register(allowed = true): {
  handlers: Map<string, Handler>
  deps: { [K in keyof DriveIpcDeps]: ReturnType<typeof vi.fn> }
} {
  const handlers = new Map<string, Handler>()
  const deps = {
    status: vi.fn(async () => STATUS),
    setDrive: vi.fn(async () => STATUS),
    requestPermissions: vi.fn(async () => STATUS),
    setDriving: vi.fn(),
    releaseSender: vi.fn()
  }
  registerDriveIpcHandlers({ handle: (c, l) => void handlers.set(c, l) }, deps, {
    isAllowedSender: () => allowed,
    isMainSender: (event) => allowed && event.sender === MAIN.event.sender
  })
  return { handlers, deps }
}

describe('registerDriveIpcHandlers', () => {
  const c = SOL_WINDOW_CHANNELS

  it('registers the four invokes on the shared constants', () => {
    const { handlers } = register()
    expect([...handlers.keys()].sort()).toEqual(
      [c.getDriveStatus, c.setDrive, c.requestDrivePermissions, c.setDriving].sort()
    )
  })

  it('answers the status and validates booleans', async () => {
    const { handlers, deps } = register()
    expect(await handlers.get(c.getDriveStatus)?.(MAIN.event)).toEqual(STATUS)
    expect(await handlers.get(c.setDrive)?.(MAIN.event, true)).toEqual(STATUS)
    expect(await handlers.get(c.setDrive)?.(MAIN.event, 'yes')).toBeNull()
    expect(await handlers.get(c.requestDrivePermissions)?.(MAIN.event, 'ignored')).toEqual(STATUS)
    await handlers.get(c.setDriving)?.(MAIN.event, 1)
    expect(deps.setDrive.mock.calls).toEqual([[true]])
    expect(deps.requestPermissions).toHaveBeenCalledWith()
    expect(deps.setDriving).not.toHaveBeenCalled()
  })

  it('the SOL window may read, turn drive OFF and report driving — never turn it on or prompt', async () => {
    const { handlers, deps } = register()
    expect(await handlers.get(c.getDriveStatus)?.(PILL.event)).toEqual(STATUS)
    expect(await handlers.get(c.setDrive)?.(PILL.event, true)).toBeNull()
    expect(await handlers.get(c.requestDrivePermissions)?.(PILL.event)).toBeNull()
    expect(await handlers.get(c.setDrive)?.(PILL.event, false)).toEqual(STATUS)
    await handlers.get(c.setDriving)?.(PILL.event, true)
    expect(deps.setDrive.mock.calls).toEqual([[false]])
    expect(deps.requestPermissions).not.toHaveBeenCalled()
    expect(deps.setDriving.mock.calls).toEqual([[2, true]])
  })

  it('a driving sender whose window closes is released, once', async () => {
    const { handlers, deps } = register()
    const s = sender(7)
    await handlers.get(c.setDriving)?.(s.event, true)
    await handlers.get(c.setDriving)?.(s.event, true)
    expect(s.listeners()).toBe(1)
    s.destroy()
    expect(deps.releaseSender.mock.calls).toEqual([[7]])
    await handlers.get(c.setDriving)?.(s.event, true) // a new step re-arms the release
    expect(s.listeners()).toBe(1)
  })

  it('a foreign sender gets null and nothing runs', async () => {
    const { handlers, deps } = register(false)
    for (const handler of handlers.values()) {
      expect((await handler(MAIN.event, true)) ?? null).toBeNull()
    }
    for (const fn of Object.values(deps)) expect(fn).not.toHaveBeenCalled()
  })
})
