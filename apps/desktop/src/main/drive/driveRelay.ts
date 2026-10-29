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

/** Why `argv` may not be relayed for `workspace`, or null when it may. */
export function relayRefusal(argv: readonly string[], workspace: string): string | null {
  if (!RELAYED_COMMANDS.has(argv[0] ?? '')) return 'only identify, capture and act are relayed'
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

export interface DriveRelayDeps {
  /** The transport now (null: the native module did not load). */
  transport(): DriveTransport | null
  /** Write one line to that child's stdin. */
  write(child: object, line: string): void
}

export interface DriveRelay {
  /** A child was spawned; `workspace` is the checked folder when drive is on, else null. */
  attach(child: object, workspace: string | null): void
  /** The child exited, was replaced or stopped. */
  detach(child: object): void
  request(child: object, request: { id: number; argv: string[] }): void
  cancel(child: object, id: number): void
}

export function createDriveRelay(deps: DriveRelayDeps): DriveRelay {
  let current: { child: object; workspace: string } | null = null
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
    const transport = deps.transport()
    const reply =
      transport === null
        ? null
        : await transport.request({ op: 'run', argv }, controller.signal).catch(() => null)
    if (controller.signal.aborted || current?.child !== child) return
    inflight.delete(id)
    deps.write(
      child,
      driveReplyLine(id, reply ?? refusal('agent_unavailable', 'the drive agent is not reachable'))
    )
  }

  return {
    attach(child, workspace) {
      abortAll()
      current = workspace === null ? null : { child, workspace }
    },
    detach(child) {
      if (current?.child !== child) return
      abortAll()
      current = null
    },
    request(child, { id, argv }) {
      if (current?.child !== child) return // not the drive child: ignored
      const refused = inflight.has(id)
        ? 'a call with this id is already running'
        : relayRefusal(argv, current.workspace)
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
