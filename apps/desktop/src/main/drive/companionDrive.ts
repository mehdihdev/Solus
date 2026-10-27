// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §5), review M3:
// the companion supervisor's drive decisions, pure so they are tested without
// spawning a process. companion.ts holds the state and calls these.
import type { Rect } from '../capture/screenCapture'

/** Respawn the RUNNING child only when the agent socket baked into it differs from
 *  the current decision. With no child (or none spawned yet) the next spawn
 *  reads the fresh decision, so nothing is needed. */
export function driveRespawnNeeded(
  state: { hasChild: boolean; bakedSocket: string | null | undefined },
  nextSocket: string | null
): boolean {
  if (!state.hasChild || state.bakedSocket === undefined) return false
  return state.bakedSocket !== nextSocket
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

/** What main hands the companion so its agent client can `run` (sol-drive.md §3). */
export interface DriveSessionGrant {
  socket: string
  token: string
}

/** One stdin frame for the companion. The token is never logged. */
export function driveSessionLine(grant: DriveSessionGrant): string {
  return `${JSON.stringify({ type: 'drive_session', socket: grant.socket, token: grant.token })}\n`
}

/** A just-registered agent may still be starting: retry this often, this many times. */
export const SESSION_RETRY_MS = 2_000
export const SESSION_MAX_ATTEMPTS = 30
/** `drive_session_needed` is honoured at most this often (a looping child cannot
 *  make main hammer the agent). */
export const SESSION_NEEDED_MIN_INTERVAL_MS = 2_000

export interface SessionCourierDeps {
  /** A fresh session from the agent (null: unreachable / refused). */
  fetch(): Promise<DriveSessionGrant | null>
  write(child: object, line: string): void
  now(): number
  setTimeout(cb: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}

export interface SessionCourier {
  /** A child was spawned with drive on: deliver it a session. */
  start(child: object): void
  /** The child said `drive_session_needed`. */
  needed(child: object): void
  /** The child is gone or replaced. */
  stop(child: object): void
}

/** Sessions reach only the CURRENT drive child; a fetch that returns after the
 *  child was stopped or replaced is dropped. */
export function createSessionCourier(deps: SessionCourierDeps): SessionCourier {
  let current: object | null = null
  let generation = 0
  let timer: unknown = null
  let lastNeededAt = Number.NEGATIVE_INFINITY

  const cancelRetry = (): void => {
    if (timer !== null) deps.clearTimeout(timer)
    timer = null
  }

  const deliver = (child: object, attempt: number): void => {
    const gen = generation
    void deps
      .fetch()
      .catch(() => null)
      .then((grant) => {
        if (gen !== generation || current !== child) return
        if (grant !== null) return deps.write(child, driveSessionLine(grant))
        if (attempt + 1 >= SESSION_MAX_ATTEMPTS) return
        timer = deps.setTimeout(() => {
          timer = null
          deliver(child, attempt + 1)
        }, SESSION_RETRY_MS)
      })
  }

  const begin = (child: object): void => {
    cancelRetry()
    generation += 1
    deliver(child, 0)
  }

  return {
    start(child) {
      current = child
      begin(child)
    },
    needed(child) {
      if (child !== current) return
      if (deps.now() - lastNeededAt < SESSION_NEEDED_MIN_INTERVAL_MS) return
      lastNeededAt = deps.now()
      begin(child)
    },
    stop(child) {
      if (child !== current) return
      current = null
      generation += 1
      cancelRetry()
    }
  }
}
