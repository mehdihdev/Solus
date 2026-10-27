// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5), review M3:
// the companion supervisor's drive decisions, pure so they are tested without
// spawning a process. companion.ts holds the state and calls these.
import type { Rect } from '../capture/screenCapture'

/** Respawn the RUNNING child only when the helper baked into it differs from
 *  the current decision. With no child (or none spawned yet) the next spawn
 *  reads the fresh decision, so nothing is needed. */
export function driveRespawnNeeded(
  state: { hasChild: boolean; bakedHelper: string | null | undefined },
  nextHelper: string | null
): boolean {
  if (!state.hasChild || state.bakedHelper === undefined) return false
  return state.bakedHelper !== nextHelper
}

export type FolderChangeAction = 'respawn' | 'recheck_drive' | 'none'

/** A folder link changed: the active project's own workspace change needs a
 *  respawn; any other link change can still flip drive availability (the
 *  nested-folder rule), so drive is re-checked. */
export function folderChangeAction(input: {
  changedProjectId: string
  activeProjectId: string | null
  workspaceNow: string | null
  workspaceBaked: string | null | undefined
}): FolderChangeAction {
  if (input.activeProjectId === null) return 'none'
  const ownWorkspaceMoved =
    input.changedProjectId === input.activeProjectId && input.workspaceNow !== input.workspaceBaked
  return ownWorkspaceMoved ? 'respawn' : 'recheck_drive'
}

export interface DriveGeometryRelay {
  setListener(listener: ((bounds: Rect | null) => void) | null): void
  /** A child was spawned; its stdout reader forwards through the returned fn. */
  attach(child: object, spawnedWithDrive: boolean): (bounds: Rect) => void
  /** The child exited, was replaced or stopped: the outline loses its bounds. */
  detach(child: object): void
}

/** Geometry reaches main only from the current child, and only one spawned
 *  with drive on; a detached child's late output is dropped. */
export function createDriveGeometryRelay(): DriveGeometryRelay {
  let current: object | null = null
  let listener: ((bounds: Rect | null) => void) | null = null
  return {
    setListener: (next) => void (listener = next),
    attach(child, spawnedWithDrive) {
      current = child
      return (bounds) => {
        if (spawnedWithDrive && current === child) listener?.(bounds)
      }
    },
    detach(child) {
      if (current !== child) return
      current = null
      listener?.(null)
    }
  }
}
