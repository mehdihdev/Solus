// SOLUSDEV-319 drive slice 3b, XPC (docs/architecture/sol-drive.md §2.1, §5
// "Main and the agent"; ADR-041 amendment 2026-10-28): how main reaches the
// helper. Main is the agent's only client.
//   - Packaged: the native XPC module inside the app bundle (the listener
//     checks Solus.app's code requirement on every message; the module checks
//     the agent's).
//   - Dev: the resolved debug helper, run once per call with the argv —
//     argument list, no shell, PATH-only env, one deadline, a stdout cap; its
//     stderr is logged, bounded.
// Either answers ONE reply object or null (the relay turns null into
// `agent_unavailable`). An AbortSignal cancels the call in flight.

export type DriveOp = { op: 'trust'; prompt: boolean } | { op: 'run'; argv: string[] }

export interface DriveTransport {
  request(op: DriveOp, signal: AbortSignal): Promise<Record<string, unknown> | null>
}

/** `trust` is quick; a `run` (capture, act with a ≤ 2 s wait) has headroom. */
export const DRIVE_TRUST_TIMEOUT_MS = 5_000
export const DRIVE_RUN_TIMEOUT_MS = 30_000
export const DRIVE_KILL_GRACE_MS = 1_000
/** An incompressible 2048-px capture as base64 JSON fits under 24 MiB. */
export const DEV_STDOUT_CAP_BYTES = 25 * 1024 * 1024
export const DEV_STDERR_LOG_BYTES = 2 * 1024
const HELPER_ENV = { PATH: '/usr/bin:/bin' } as const

const timeoutFor = (op: DriveOp): number =>
  op.op === 'trust' ? DRIVE_TRUST_TIMEOUT_MS : DRIVE_RUN_TIMEOUT_MS

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/** Exactly one JSON object (split on `\n` only), else null. */
export function parseReplyObject(raw: string): Record<string, unknown> | null {
  const lines = raw.split('\n').filter((line) => line.trim().length > 0)
  if (lines.length !== 1) return null
  try {
    const value: unknown = JSON.parse(lines[0])
    return isRecord(value) ? value : null
  } catch {
    return null
  }
}

// --- packaged: the native XPC module ----------------------------------------

/** `@solus/solus-input-xpc` (apps/desktop/native/solus-input-xpc). */
export interface XpcModule {
  /** Starts one request; throws synchronously only for bad arguments. */
  request(json: string, timeoutMs: number): { id: number; promise: Promise<string> }
  /** Cancels THAT request only; an unknown or finished id is a no-op. */
  cancel(id: number): void
  /** Review HIGH-1: SecStaticCodeCheckValidity over main's own bundle. */
  checkOwnBundle?(): Promise<boolean>
}

/** Load the module; null (⇒ every call answers agent_unavailable) when it is
 *  missing or not the expected shape. */
export function loadXpcModule(
  load: () => unknown,
  warn: (message: string) => void = () => undefined
): XpcModule | null {
  try {
    const m = load()
    if (isRecord(m) && typeof m.request === 'function' && typeof m.cancel === 'function') {
      return m as unknown as XpcModule
    }
    warn('[drive] the XPC module does not export request/cancel')
  } catch (error) {
    warn(
      `[drive] the XPC module failed to load: ${error instanceof Error ? error.message : 'unknown'}`
    )
  }
  return null
}

export function createXpcTransport(module: XpcModule): DriveTransport {
  return {
    async request(op, signal) {
      if (signal.aborted) return null
      let started: { id: number; promise: Promise<string> }
      try {
        started = module.request(JSON.stringify({ v: 1, ...op }), timeoutFor(op))
      } catch {
        return null
      }
      // Per-request cancel (LOW-B): aborting a relayed run never touches a
      // concurrent trust request.
      const onAbort = (): void => {
        try {
          module.cancel(started.id)
        } catch {
          /* a cancel that throws must not escape the abort */
        }
      }
      signal.addEventListener('abort', onAbort, { once: true })
      try {
        const raw = await started.promise
        return signal.aborted ? null : parseReplyObject(raw)
      } catch {
        return null // a rejection (cancelled, timed out, an interrupted act) is agent_unavailable upstream
      } finally {
        signal.removeEventListener('abort', onAbort)
      }
    }
  }
}

// --- dev: the debug helper, once per call ------------------------------------

interface Readable {
  on(event: 'data', listener: (chunk: Buffer) => void): unknown
}

/** The slice of a ChildProcess the dev transport needs. */
export interface DevChild {
  stdout: Readable | null
  stderr: Readable | null
  on(event: 'close', listener: (code: number | null, signal: string | null) => void): unknown
  on(event: 'error', listener: (error: Error) => void): unknown
  kill(signal: 'SIGTERM' | 'SIGKILL'): boolean
}

export type DevSpawn = (
  command: string,
  args: string[],
  options: {
    env: Record<string, string>
    stdio: ['ignore', 'pipe', 'pipe']
    shell: false
  }
) => DevChild

export interface DevTransportDeps {
  /** The resolved, rule-checked debug helper, or null. */
  helper(): string | null
  spawn: DevSpawn
  warn(message: string): void
  setTimeout(cb: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}

const devArgv = (op: DriveOp): string[] =>
  op.op === 'trust' ? (op.prompt ? ['trust', '--prompt'] : ['trust']) : op.argv

export function createDevTransport(deps: DevTransportDeps): DriveTransport {
  const run = (helper: string, op: DriveOp, signal: AbortSignal): Promise<string | null> =>
    new Promise((resolve) => {
      let child: DevChild
      try {
        child = deps.spawn(helper, devArgv(op), {
          env: { ...HELPER_ENV },
          stdio: ['ignore', 'pipe', 'pipe'],
          shell: false
        })
      } catch {
        return resolve(null)
      }
      const out: Buffer[] = []
      let outBytes = 0
      let err = ''
      let killed = false
      let settled = false
      const timers: unknown[] = []
      const stop = (): void => {
        if (killed) return
        killed = true
        child.kill('SIGTERM')
        timers.push(deps.setTimeout(() => child.kill('SIGKILL'), DRIVE_KILL_GRACE_MS))
      }
      const finish = (value: string | null): void => {
        if (settled) return
        settled = true
        for (const t of timers) deps.clearTimeout(t)
        signal.removeEventListener('abort', stop)
        if (err.length > 0) deps.warn(`[drive] helper stderr: ${err.trimEnd()}`)
        resolve(value)
      }
      timers.push(deps.setTimeout(stop, timeoutFor(op)))
      signal.addEventListener('abort', stop, { once: true })
      child.stdout?.on('data', (chunk) => {
        outBytes += chunk.length
        if (outBytes > DEV_STDOUT_CAP_BYTES) return stop()
        out.push(chunk)
      })
      child.stderr?.on('data', (chunk) => {
        if (err.length < DEV_STDERR_LOG_BYTES) {
          err = (err + chunk.toString('utf8')).slice(0, DEV_STDERR_LOG_BYTES)
        }
      })
      child.on('error', () => finish(null))
      // A refusal exits non-zero but still prints its reply; only our own kill voids it.
      child.on('close', () => finish(killed ? null : Buffer.concat(out).toString('utf8')))
      if (signal.aborted) stop()
    })

  return {
    async request(op, signal) {
      const helper = deps.helper()
      if (helper === null || signal.aborted) return null
      const raw = await run(helper, op, signal)
      return raw === null ? null : parseReplyObject(raw)
    }
  }
}
