// SOLUSDEV-319 drive slice 3: the drive invokes answer only an allowed sender
// and validate their argument before acting.
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
const EVENT = {} as IpcMainInvokeEvent
type Handler = (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown

function register(allowed: boolean): {
  handlers: Map<string, Handler>
  deps: DriveIpcDeps & { [K in keyof DriveIpcDeps]: ReturnType<typeof vi.fn> }
} {
  const handlers = new Map<string, Handler>()
  const deps = {
    status: vi.fn(async () => STATUS),
    setDrive: vi.fn(async () => STATUS),
    requestPermissions: vi.fn(async () => STATUS),
    setDriving: vi.fn()
  }
  registerDriveIpcHandlers({ handle: (c, l) => void handlers.set(c, l) }, deps, () => allowed)
  return { handlers, deps }
}

describe('registerDriveIpcHandlers', () => {
  const c = SOL_WINDOW_CHANNELS

  it('registers the four invokes on the shared constants', () => {
    const { handlers } = register(true)
    expect([...handlers.keys()].sort()).toEqual(
      [c.getDriveStatus, c.setDrive, c.requestDrivePermissions, c.setDriving].sort()
    )
  })

  it('answers the status and validates booleans', async () => {
    const { handlers, deps } = register(true)
    expect(await handlers.get(c.getDriveStatus)?.(EVENT)).toEqual(STATUS)
    expect(await handlers.get(c.setDrive)?.(EVENT, true)).toEqual(STATUS)
    expect(await handlers.get(c.setDrive)?.(EVENT, 'yes')).toBeNull()
    expect(await handlers.get(c.requestDrivePermissions)?.(EVENT, 'ignored')).toEqual(STATUS)
    await handlers.get(c.setDriving)?.(EVENT, true)
    await handlers.get(c.setDriving)?.(EVENT, 1)
    expect(deps.setDrive).toHaveBeenCalledTimes(1)
    expect(deps.setDrive).toHaveBeenCalledWith(true)
    expect(deps.requestPermissions).toHaveBeenCalledWith()
    expect(deps.setDriving.mock.calls).toEqual([[true]])
  })

  it('a foreign sender gets null and nothing runs', async () => {
    const { handlers, deps } = register(false)
    for (const handler of handlers.values()) expect((await handler(EVENT, true)) ?? null).toBeNull()
    for (const fn of Object.values(deps)) expect(fn).not.toHaveBeenCalled()
  })
})
