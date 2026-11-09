// SOLUSDEV-319 drive slice 3b, XPC (docs/architecture/sol-drive.md §3 relay,
// §5 "Main and the agent"; ADR-041 amendment 2026-10-28) and slice 4 (§2.2
// "Relay rule", ADR-041 2026-10-31): the companion never reaches the helper; it
// relays each call to main over the pipes main created. Main answers only the
// CURRENT child it spawned with drive on, and only for identify/capture/act:
//   - `--within`: at most once and equal to the workspace main checked for that
//     child (nested-folder rule); absent when the child has none.
//   - project-bound (KiCad) capture/act need `--within`.
//   - every other capture/act is window-bound: exactly one `--pid`, and
//     (--bundle, --pid, --window) equal to the summon snapshot — else
//     `window_mismatch`.
// Anything else gets a refusal and nothing reaches the agent. drive_cancel, or
// the child going away, aborts the call in flight.
import type { DriveTransport } from './driveTransport'
import { frontAppLink, type FrontAppContext, type FrontAppLink } from './frontApp'
import { isProjectBoundBundle, type SolFrontApp } from './frontAppShape'

const RELAYED_COMMANDS: ReadonlySet<string> = new Set(['identify', 'capture', 'act'])
/** argv as JSON, so the whole XPC request (`{"v":1,"op":"run","argv":…}`)
 *  stays under the agent's 64 KiB request cap (L3). */
export const MAX_RELAY_ARGV_BYTES = 60 * 1024
/** The companion refuses a reply over 24 MiB as JSON; main says so instead (L4). */
export const MAX_RELAY_REPLY_BYTES = 24 * 1024 * 1024

export interface RelayRefusal {
  code: 'usage' | 'window_mismatch'
  message: string
}

const usage = (message: string): RelayRefusal => ({ code: 'usage', message })
const mismatch = (message: string): RelayRefusal => ({ code: 'window_mismatch', message })

/** The flags the relay checks; their `--flag=value` form would slip past it. */
const BOUND_FLAGS = ['--within', '--bundle', '--pid', '--window'] as const

const positions = (argv: readonly string[], flag: string): number[] =>
  argv.flatMap((arg, i) => (arg === flag ? [i] : []))

/** The value of a flag that appears exactly once, else undefined. */
function single(argv: readonly string[], flag: string): string | undefined {
  const at = positions(argv, flag)
  return at.length === 1 ? argv[at[0] + 1] : undefined
}

function withinRefusal(argv: readonly string[], workspace: string | null): RelayRefusal | null {
  const at = positions(argv, '--within')
  if (workspace === null) {
    return at.length === 0
      ? null
      : usage('this companion has no workspace: --within must be absent')
  }
  if (at.length > 1) return usage('--within may appear at most once')
  if (at.length === 1 && argv[at[0] + 1] !== workspace) {
    return usage("--within is not this companion's workspace")
  }
  return null
}

/** A window-bound capture/act must aim at exactly the summoned window. */
function windowRefusal(
  argv: readonly string[],
  bundle: string,
  front: SolFrontApp | null
): RelayRefusal | null {
  const window = single(argv, '--window')
  if (window === undefined) return usage('--window must appear exactly once')
  const pid = positions(argv, '--pid')
  if (pid.length !== 1) return mismatch('a window-bound call needs exactly one --pid')
  if (front === null || !front.drivable || front.binding !== 'window' || front.windowId === null) {
    return mismatch('SOL was not summoned over a drivable window')
  }
  const same =
    bundle === front.bundleId &&
    argv[pid[0] + 1] === String(front.pid) &&
    window === String(front.windowId)
  return same ? null : mismatch('not the window SOL was summoned over')
}

/** Why `argv` may not be relayed for a child with `workspace` (null: none)
 *  given the summon snapshot `front`, or null when it may. */
export function relayRefusal(
  argv: readonly string[],
  workspace: string | null,
  front: SolFrontApp | null
): RelayRefusal | null {
  const command = argv[0] ?? ''
  if (!RELAYED_COMMANDS.has(command)) return usage('only identify, capture and act are relayed')
  if (Buffer.byteLength(JSON.stringify(argv)) > MAX_RELAY_ARGV_BYTES) {
    return usage('argv is too large')
  }
  if (argv.some((arg) => BOUND_FLAGS.some((flag) => arg.startsWith(`${flag}=`)))) {
    return usage('binding flags take their value as the next argument')
  }
  const within = withinRefusal(argv, workspace)
  if (within !== null || command === 'identify') return within
  const bundle = single(argv, '--bundle')
  if (bundle === undefined) return usage('--bundle must appear exactly once')
  if (!isProjectBoundBundle(bundle)) return windowRefusal(argv, bundle, front)
  return positions(argv, '--within').length === 1
    ? null
    : usage('a project-bound app needs --within')
}

/** `type` MUST serialise first: the companion admits an oversize stdin line (a
 *  capture, up to 24 MiB) only when it starts with `{"type":"drive_reply",`. */
export function driveReplyLine(id: number, reply: unknown): string {
  return `${JSON.stringify({ type: 'drive_reply', id, reply })}\n`
}

const refusal = (code: string, message: string): Record<string, unknown> => ({
  ok: false,
  code,
  message
})

/** The reply line, or a helper_output refusal when the reply is over the cap. */
function boundedReplyLine(id: number, reply: Record<string, unknown>): string {
  const line = driveReplyLine(id, reply)
  return Buffer.byteLength(line) - 1 > MAX_RELAY_REPLY_BYTES
    ? driveReplyLine(id, refusal('helper_output', 'the helper reply is too large'))
    : line
}

export interface DriveRelayDeps {
  /** Packaged builds fail closed (LOW-A): a drive child attached without a
   *  bundle check never reaches the agent. */
  packaged: boolean
  /** The transport now (null: the native module did not load). */
  transport(): DriveTransport | null
  /** Write one line to that child's stdin. */
  write(child: object, line: string): void
  /** The summon snapshot and the drive-child report (default: the process link). */
  frontApp?: Pick<FrontAppLink, 'snapshot' | 'setDriveChild'>
}

/** Drive for a spawned child: off (null), or on with or without a workspace.
 *  A bare string is the slice 3b form (drive on, that workspace). */
export type RelayDrive = string | FrontAppContext | null

const driveContext = (drive: RelayDrive): FrontAppContext | null =>
  typeof drive === 'string' ? { workspace: drive } : drive

export interface DriveRelay {
  /** A child was spawned; `drive` says whether drive is on for it and with
   *  which checked workspace. `bundleOk` is the spawn-time own-bundle check
   *  (HIGH-1): calls wait for it, and a false answer reaches no agent. */
  attach(child: object, drive: RelayDrive, bundleOk?: Promise<boolean>): void
  /** The child exited, was replaced or stopped. */
  detach(child: object): void
  request(child: object, request: { id: number; argv: string[] }): void
  cancel(child: object, id: number): void
}

export function createDriveRelay(deps: DriveRelayDeps): DriveRelay {
  const front = deps.frontApp ?? frontAppLink
  let current: { child: object; workspace: string | null; bundleOk: Promise<boolean> } | null = null
  const inflight = new Map<number, AbortController>()

  const abortAll = (): void => {
    for (const controller of inflight.values()) controller.abort()
    inflight.clear()
  }

  const run = async (
    child: object,
    id: number,
    argv: string[],
    controller: AbortController
  ): Promise<void> => {
    const bundleOk = await (current?.bundleOk ?? Promise.resolve(false)).catch(() => false)
    const reply = bundleOk
      ? await call(argv, controller.signal)
      : refusal('agent_unavailable', 'Solus.app failed its own signature check')
    if (controller.signal.aborted || current?.child !== child) return
    inflight.delete(id)
    deps.write(child, boundedReplyLine(id, reply))
  }

  const call = async (argv: string[], signal: AbortSignal): Promise<Record<string, unknown>> => {
    const transport = deps.transport()
    const reply =
      transport === null
        ? null
        : await transport.request({ op: 'run', argv }, signal).catch(() => null)
    return reply ?? refusal('agent_unavailable', 'the drive agent is not reachable')
  }

  return {
    attach(child, drive, bundleOk = Promise.resolve(!deps.packaged)) {
      abortAll()
      const context = driveContext(drive)
      current = context === null ? null : { child, workspace: context.workspace, bundleOk }
      front.setDriveChild(context) // a new child: the old snapshot is gone
    },
    detach(child) {
      if (current?.child !== child) return
      abortAll()
      current = null
      front.setDriveChild(null)
    },
    request(child, { id, argv }) {
      if (current?.child !== child) return // not the drive child: ignored
      const refused =
        inflight.size > 0
          ? usage('one drive call at a time')
          : relayRefusal(argv, current.workspace, front.snapshot())
      if (refused !== null) {
        return deps.write(child, driveReplyLine(id, refusal(refused.code, refused.message)))
      }
      const controller = new AbortController()
      inflight.set(id, controller)
      void run(child, id, argv, controller)
    },
    cancel(child, id) {
      if (current?.child !== child) return
      inflight.get(id)?.abort()
      inflight.delete(id)
    }
  }
}
