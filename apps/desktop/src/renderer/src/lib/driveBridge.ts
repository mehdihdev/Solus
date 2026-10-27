// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the drive
// members of `window.solus.sol`, typed structurally in this one place until the
// preload SolBridge carries them. Feature-detected: null unless every member
// is present, so the renderer works against a preload without them.
import type { DriveStatus } from '../../../main/drive/driveStatus'
import { getDesktopSolBridge } from './desktopBridge'

export type { DriveStatus }

export interface DriveBridge {
  getDriveStatus: () => Promise<DriveStatus | null>
  setDrive: (on: boolean) => Promise<DriveStatus | null>
  /** Runs the helper's `trust --prompt`. */
  requestDrivePermissions: () => Promise<DriveStatus | null>
  /** Tell main a drive.step is running (outline on) or ended (outline off). */
  setDriving: (active: boolean) => Promise<void>
  onDriveStatus: (handler: (status: DriveStatus) => void) => () => void
}

const MEMBERS: readonly (keyof DriveBridge)[] = [
  'getDriveStatus',
  'setDrive',
  'requestDrivePermissions',
  'setDriving',
  'onDriveStatus'
]

export function getDriveBridge(): DriveBridge | null {
  const sol = getDesktopSolBridge() as unknown as Partial<DriveBridge> | null
  if (!sol || !MEMBERS.every((m) => typeof sol[m] === 'function')) return null
  return sol as DriveBridge
}
