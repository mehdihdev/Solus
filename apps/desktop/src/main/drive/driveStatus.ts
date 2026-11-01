// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5): the shape
// main hands the renderer for Settings › SOL "SOL can use your mouse and
// keyboard". Shared by main (producer), preload (validator) and renderer.

/** Why driving cannot be turned on for the active project. `no_folder` is
 *  no longer produced (sol-drive.md §2.2: no folder only means KiCad is not
 *  drivable); it stays in the union for older renderer copy. `bundle_modified`
 *  (review HIGH-1): a packaged Solus.app whose own signature — nested code and
 *  resources included — does not validate (a relocated copy with swapped files). */
export type DriveUnavailable =
  | 'not_macos'
  | 'no_helper'
  | 'bundle_modified'
  | 'no_folder'
  | 'nested_folder'

export const DRIVE_UNAVAILABLE: readonly DriveUnavailable[] = [
  'not_macos',
  'no_helper',
  'bundle_modified',
  'no_folder',
  'nested_folder'
]

/** The helper's OS grants, from `solus-input trust`. */
export interface DriveTrust {
  accessibility: boolean
  screenRecording: boolean
}

/** The launchd agent's registration (slice 3b, sol-drive.md §2.1/§5). */
export type DriveAgentState = 'enabled' | 'requires_approval' | 'not_registered' | 'not_found'

export const DRIVE_AGENT_STATES: readonly DriveAgentState[] = [
  'enabled',
  'requires_approval',
  'not_registered',
  'not_found'
]

export interface DriveStatus {
  /** The user's setting (`sol.drive`). */
  enabled: boolean
  /** Driving may run for the active project right now. */
  available: boolean
  /** Null exactly when `available`. */
  reason: DriveUnavailable | null
  /** Null when the helper could not be asked (unavailable, or it failed). */
  trust: DriveTrust | null
  /** The helper is a debug build that skips the code-requirement checks. */
  unsignedDev: boolean
  /** The agent's registration; null when unknown (unavailable, or dev, where main runs it). */
  agent: DriveAgentState | null
}
