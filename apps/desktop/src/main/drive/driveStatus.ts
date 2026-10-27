// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the shape
// main hands the renderer for Settings › SOL "SOL can use your mouse and
// keyboard". Shared by main (producer), preload (validator) and renderer.

/** Why driving cannot be turned on for the active project. */
export type DriveUnavailable = 'not_macos' | 'no_helper' | 'no_folder' | 'nested_folder'

export const DRIVE_UNAVAILABLE: readonly DriveUnavailable[] = [
  'not_macos',
  'no_helper',
  'no_folder',
  'nested_folder'
]

/** The helper's OS grants, from `solus-input trust`. */
export interface DriveTrust {
  accessibility: boolean
  screenRecording: boolean
}

export interface DriveStatus {
  /** The user's setting (`sol.drive`). */
  enabled: boolean
  /** Driving may run for the active project right now. */
  available: boolean
  /** Null exactly when `available`. */
  reason: DriveUnavailable | null
  /** Null when the helper could not be asked (unavailable, or it failed). */
  trust: DriveTrust | null
  /** The helper is a debug build that skips the caller check. */
  unsignedDev: boolean
}
