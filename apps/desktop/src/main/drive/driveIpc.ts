// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the drive
// invokes. Channel names from SOL_WINDOW_CHANNELS only (the ratchet); every
// handler answers an allowed sender (the main renderer or the SOL window) and
// null to anything else; arguments are validated here.
//
// Consent actions — turning drive ON, asking macOS for the grants, opening the
// Login Items approval pane — are the
// MAIN window's alone (Settings): the SOL window renders model output, so it
// may read the status, turn drive OFF and report a running step, never more.
import type { IpcMainInvokeEvent } from 'electron'
import type { SolWindowIpc } from '../sol-window/solWindow'
import { SOL_WINDOW_CHANNELS } from '../sol-window/solWindow.constants'
import type { DriveStatus } from './driveStatus'

export interface DriveIpcDeps {
  status(): Promise<DriveStatus>
  setDrive(on: boolean): Promise<DriveStatus>
  requestPermissions(): Promise<DriveStatus>
  /** Keyed by the sender's webContents id (ref-counted by the session). */
  setDriving(senderId: number, active: boolean): void
  /** That sender's window went away. */
  releaseSender(senderId: number): void
  /** Open System Settings › Login Items (agent `requires_approval`). */
  openApproval(): void
}

export interface DriveIpcGates {
  /** Main renderer or SOL window. */
  isAllowedSender(event: IpcMainInvokeEvent): boolean
  /** The main renderer only. */
  isMainSender(event: IpcMainInvokeEvent): boolean
}

/** The slice of webContents a driving sender needs. */
interface DrivingSender {
  id: number
  once(event: 'destroyed', listener: () => void): void
}

export function registerDriveIpcHandlers(
  ipc: SolWindowIpc,
  deps: DriveIpcDeps,
  gates: DriveIpcGates
): void {
  const c = SOL_WINDOW_CHANNELS
  const { isAllowedSender, isMainSender } = gates
  ipc.handle(c.getDriveStatus, (event) => (isAllowedSender(event) ? deps.status() : null))
  ipc.handle(c.setDrive, (event, on) => {
    if (typeof on !== 'boolean' || !isAllowedSender(event)) return null
    if (on && !isMainSender(event)) return null
    return deps.setDrive(on)
  })
  // No renderer argument: the helper path and the command are main's.
  ipc.handle(c.requestDrivePermissions, (event) =>
    isAllowedSender(event) && isMainSender(event) ? deps.requestPermissions() : null
  )
  // No renderer argument: main opens its own pane URL, never a supplied one.
  ipc.handle(c.openDriveApproval, (event) => {
    if (isAllowedSender(event) && isMainSender(event)) deps.openApproval()
    return null
  })
  const watched = new Set<number>()
  ipc.handle(c.setDriving, (event, active) => {
    if (!isAllowedSender(event) || typeof active !== 'boolean') return null
    const sender = event.sender as unknown as DrivingSender
    if (active && !watched.has(sender.id)) {
      watched.add(sender.id)
      // A window that closes mid-step counts as its false.
      sender.once('destroyed', () => {
        watched.delete(sender.id)
        deps.releaseSender(sender.id)
      })
    }
    deps.setDriving(sender.id, active)
    return null
  })
}
