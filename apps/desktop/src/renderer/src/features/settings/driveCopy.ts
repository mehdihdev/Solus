// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the words
// Settings uses for "SOL can use your mouse and keyboard", and the pure reads
// of a DriveStatus that the row and Needs attention share.
import type { DriveStatus } from '../../lib/driveBridge'
import type { DriveTrust, DriveUnavailable } from '../../../../main/drive/driveStatus'

export const DRIVE_LABEL = 'SOL can use your mouse and keyboard'

export const DRIVE_COPY =
  'When on, SOL can click and type in KiCad for a step you approve. Moving the mouse or pressing Esc stops it.'

/** One sentence per reason driving cannot be turned on. */
export const DRIVE_REASON_COPY: Readonly<Record<DriveUnavailable, string>> = {
  not_macos: 'Only on macOS for now.',
  no_helper: 'The input helper is missing from this install.',
  no_folder: 'Link this project to a folder on this computer first.',
  nested_folder:
    "This project's folder is inside, or contains, another linked project's folder. Move one of them so SOL can't act on the other project's files."
}

/** The helper bundle the grants belong to (never Solus.app). */
export const DRIVE_HELPER_NAME = 'SolusInput'

export type DriveGrant = 'Accessibility' | 'Screen Recording'

export function missingGrants(trust: DriveTrust | null): DriveGrant[] {
  if (!trust) return []
  const missing: DriveGrant[] = []
  if (!trust.accessibility) missing.push('Accessibility')
  if (!trust.screenRecording) missing.push('Screen Recording')
  return missing
}

/** On, available, and the helper lacks a grant — off is not the user's problem. */
export function driveBlocked(status: DriveStatus | null): boolean {
  return !!status?.enabled && status.available && missingGrants(status.trust).length > 0
}
