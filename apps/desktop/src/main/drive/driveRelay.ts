// SOLUSDEV-319 drive slice 3b, XPC (docs/architecture/sol-drive.md §3 relay,
// §5 "Main and the agent"; ADR-041 amendment 2026-10-28): the companion never
// reaches the helper; it relays each call to main over the pipes main created.
// Main answers only the CURRENT child it spawned with drive on, and only for
// identify/capture/act bound (`--within`, exactly once) to the workspace main
// checked for that child with the nested-folder rule. Anything else gets a
// `usage` reply and nothing reaches the agent. drive_cancel, or the child going
// away, aborts the call in flight.
import type { DriveTransport } from './driveTransport'

const RELAYED_COMMANDS: ReadonlySet<string> = new Set(['identify', 'capture', 'act'])
/** argv as JSON, so the whole XPC request (`{"v":1,"op":"run","argv":…}`)
 *  stays under the agent's 64 KiB request cap (L3). */
export const MAX_RELAY_ARGV_BYTES = 60 * 1024
/** The companion refuses a reply over 24 MiB as JSON; main says so instead (L4). */
export const MAX_RELAY_REPLY_BYTES = 24 * 1024 * 1024

/** Why `argv` may not be relayed for `workspace`, or null when it may. */
export function relayRefusal(argv: readonly string[], workspace: string): string | null {
  if (!RELAYED_COMMANDS.has(argv[0] ?? '')) return 'only identify, capture and act are relayed'
  if (Buffer.byteLength(JSON.stringify(argv)) > MAX_RELAY_ARGV_BYTES) return 'argv is too large'
  const at = argv.flatMap((arg, i) => (arg === '--within' ? [i] : []))
  if (at.length !== 1) return '--within must appear exactly once'
  if (argv[at[0] + 1] !== workspace) return "--within is not this companion's workspace"
  return null
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
  /** The transport now (null: the native module did not load). */
  transport(): DriveTransport | null
  /** Write one line to that child's stdin. */
  write(child: object, line: string): void
}

export interface DriveRelay {
  /** A child was spawned; `workspace` is the checked folder when drive is on,
   *  else null. `bundleOk` is the spawn-time own-bundle check (HIGH-1): calls
   *  wait for it, and a false answer reaches no agent. */
  attach(child: object, workspace: string | null, bundleOk?: Promise<boolean>): void
  /** The child exited, was replaced or stopped. */
  detach(child: object): void
  request(child: object, request: { id: number; argv: string[] }): void
  cancel(child: object, id: number): void
}

export function createDriveRelay(deps: DriveRelayDeps): DriveRelay {
  let current: { child: object; workspace: string; bundleOk: Promise<boolean> } | null = null
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
    attach(child, workspace, bundleOk = Promise.resolve(true)) {
      abortAll()
      current = workspace === null ? null : { child, workspace, bundleOk }
    },
    detach(child) {
      if (current?.child !== child) return
      abortAll()
      current = null
    },
    request(child, { id, argv }) {
      if (current?.child !== child) return // not the drive child: ignored
      const refused =
        inflight.size > 0 ? 'one drive call at a time' : relayRefusal(argv, current.workspace)
      if (refused !== null) return deps.write(child, driveReplyLine(id, refusal('usage', refused)))
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
