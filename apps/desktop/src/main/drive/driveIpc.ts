// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the drive
// invokes. Channel names from SOL_WINDOW_CHANNELS only (the ratchet); every
// handler answers an allowed sender (main.isSolSender — the main renderer or
// the SOL window) and null to anything else; arguments are validated here.
import type { IpcMainInvokeEvent } from 'electron'
import type { SolWindowIpc } from '../sol-window/solWindow'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import type { DriveStatus } from './driveStatus'

export interface DriveIpcDeps {
  status(): Promise<DriveStatus>
  setDrive(on: boolean): Promise<DriveStatus>
  requestPermissions(): Promise<DriveStatus>
  setDriving(active: boolean): void
}

export function registerDriveIpcHandlers(
  ipc: SolWindowIpc,
  deps: DriveIpcDeps,
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean
): void {
  const c = SOL_WINDOW_CHANNELS
  ipc.handle(c.getDriveStatus, (event) => (isAllowedSender(event) ? deps.status() : null))
  ipc.handle(c.setDrive, (event, on) =>
    isAllowedSender(event) && typeof on === 'boolean' ? deps.setDrive(on) : null
  )
  // No renderer argument: the helper path and the command are main's.
  ipc.handle(c.requestDrivePermissions, (event) =>
    isAllowedSender(event) ? deps.requestPermissions() : null
  )
  ipc.handle(c.setDriving, (event, active) => {
    if (isAllowedSender(event) && typeof active === 'boolean') deps.setDriving(active)
    return null
  })
}
