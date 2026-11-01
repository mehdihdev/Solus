// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2 "Main: summon
// snapshot and relay"; ADR-041 2026-10-31): the front-app snapshot. On every
// pill summon, while driving is on and available, main sends ONE `identify`
// through the drive transport (XPC packaged, debug helper in dev) BEFORE the
// pill takes focus, and lets the pill show when it answers or after 250 ms; a
// later reply is discarded. The snapshot is what a window-bound step may be
// aimed at (driveRelay checks every capture/act against it) and what the turn's
// `front_app` is built from. Nothing is captured — identity and title only.
import { frontFromIdentify, isSolusFront, type SolFrontApp } from './frontAppShape'
import type { DriveTransport } from './driveTransport'

export const FRONT_APP_SUMMON_WAIT_MS = 250

/** The drive child's context: driving is on and available, with or without a
 *  linked workspace (window-bound apps need none). */
export interface FrontAppContext {
  workspace: string | null
}

export interface FrontAppTrackerDeps {
  /** Null while driving is off or unavailable (⇒ no identify, snapshot null). */
  context(): FrontAppContext | null
  transport(): DriveTransport | null
  /** Push to the SOL window (SOL_WINDOW_CHANNELS.frontApp) — on change only. */
  publish(front: SolFrontApp | null): void
  setTimeout(cb: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}

export interface FrontAppTracker {
  /** Run before the pill shows; resolves within FRONT_APP_SUMMON_WAIT_MS. */
  beforeSummon(): Promise<void>
  snapshot(): SolFrontApp | null
  /** Drive off, project switch, companion restart or exit. */
  clear(): void
}

const TIMED_OUT = Symbol('timed-out')

const identifyArgv = (context: FrontAppContext): string[] =>
  context.workspace === null ? ['identify'] : ['identify', '--within', context.workspace]

/** The reply's front, null for nothing in front, undefined when unusable. */
function frontOf(reply: Record<string, unknown> | null): SolFrontApp | null | undefined {
  if (reply === null || reply.ok !== true || !('front' in reply)) return undefined
  return frontFromIdentify(reply.front)
}

export function createFrontAppTracker(deps: FrontAppTrackerDeps): FrontAppTracker {
  let current: SolFrontApp | null = null
  let key = JSON.stringify(null)
  /** Bumped by every summon and clear: a stale reply never lands. */
  let generation = 0

  const set = (front: SolFrontApp | null): void => {
    current = front
    const next = JSON.stringify(front)
    if (next === key) return
    key = next
    deps.publish(front)
  }

  const identify = async (
    transport: DriveTransport,
    context: FrontAppContext
  ): Promise<Record<string, unknown> | null | typeof TIMED_OUT> => {
    const controller = new AbortController()
    let timer: unknown
    const timeout = new Promise<typeof TIMED_OUT>((resolve) => {
      timer = deps.setTimeout(() => resolve(TIMED_OUT), FRONT_APP_SUMMON_WAIT_MS)
    })
    const reply = transport
      .request({ op: 'run', argv: identifyArgv(context) }, controller.signal)
      .catch(() => null)
    const result = await Promise.race([reply, timeout])
    deps.clearTimeout(timer)
    if (result === TIMED_OUT) controller.abort()
    return result
  }

  return {
    async beforeSummon() {
      const mine = ++generation
      const context = deps.context()
      const transport = context === null ? null : deps.transport()
      if (context === null || transport === null) return set(null)
      const result = await identify(transport, context)
      if (mine !== generation) return // cleared (or re-summoned) meanwhile
      // Timed out: the pill now takes focus, so a later reply would only see
      // Solus; an unknown front is not bound to anything.
      const front = result === TIMED_OUT ? undefined : frontOf(result)
      if (front !== undefined && isSolusFront(front)) return // keep the previous snapshot
      set(front ?? null)
    },
    snapshot: () => current,
    clear() {
      generation += 1
      set(null)
    }
  }
}

/** Process-wide seam between the relay (owned by the companion supervisor)
 *  and the tracker (owned by the drive wiring): the relay reads the snapshot
 *  and reports its drive child; a new or exited child clears the snapshot. */
export interface FrontAppLink {
  setTracker(tracker: FrontAppTracker | null): void
  snapshot(): SolFrontApp | null
  setDriveChild(context: FrontAppContext | null): void
  driveChild(): FrontAppContext | null
}

export function createFrontAppLink(): FrontAppLink {
  let tracker: FrontAppTracker | null = null
  let child: FrontAppContext | null = null
  return {
    setTracker: (next) => void (tracker = next),
    snapshot: () => tracker?.snapshot() ?? null,
    setDriveChild(context) {
      child = context
      tracker?.clear()
    },
    driveChild: () => child
  }
}

export const frontAppLink: FrontAppLink = createFrontAppLink()
