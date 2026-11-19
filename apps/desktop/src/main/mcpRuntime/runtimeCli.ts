// SOLUSDEV-329 — run `solus-companion runtime <subcommand>` from desktop main
// (docs/architecture/mcp-fork-runtime.md §6, §9).
//
// The command is the companion's own (resolveCompanionCommand: the packaged
// binary, or the dev command line), with the subcommand appended as argv —
// never a shell, never a string. Stdout goes through the bounded, validating
// line reader; stderr is drained and discarded (it may carry paths). Every
// run settles exactly once with a `done`: the CLI's own, or one synthesized
// here when the child was cancelled, timed out, overflowed or died first.
import type { SpawnOptions } from 'node:child_process'
import type { Readable } from 'node:stream'
import {
  createRuntimeLineReader,
  isAbsolutePathString,
  isForkName,
  type DoneEvent,
  type RuntimeErrorCode,
  type RuntimeEvent
} from './protocol'
import type { RuntimeChoice } from './runtimeSettings'

/** SIGTERM → SIGKILL grace (the CLI discards the env it was building). */
export const CANCEL_GRACE_MS = 5_000

export type RuntimeCommand =
  | { command: 'detect' }
  | { command: 'status' }
  | { command: 'install-managed' }
  | { command: 'provision'; forks?: readonly string[]; python: RuntimeChoice }

export interface CommandLine {
  command: string
  args: string[]
}

function provisionArgs(cmd: Extract<RuntimeCommand, { command: 'provision' }>): string[] {
  const forks = cmd.forks ?? []
  if (!forks.every(isForkName)) throw new Error('invalid fork name')
  const out = forks.length > 0 ? forks.flatMap((f) => ['--fork', f]) : ['--all']
  if (cmd.python.mode === 'managed') return [...out, '--managed']
  if (cmd.python.mode === 'auto') return out
  if (!isAbsolutePathString(cmd.python.path)) throw new Error('invalid interpreter path')
  return [...out, '--python', cmd.python.path]
}

/** The companion command line plus `runtime <subcommand> …`. Throws on any
 *  argument that is not a valid fork name or absolute path, so nothing
 *  flag-shaped can be smuggled in. */
export function runtimeArgv(base: CommandLine, cmd: RuntimeCommand): CommandLine {
  const tail = cmd.command === 'provision' ? provisionArgs(cmd) : []
  return { command: base.command, args: [...base.args, 'runtime', cmd.command, ...tail] }
}

/** Structural slice of a ChildProcess — what a run needs (fakeable in tests). */
export interface RuntimeChild {
  readonly pid?: number
  readonly stdout: Readable | null
  readonly stderr: Readable | null
  on(event: 'close', listener: (code: number | null) => void): unknown
  on(event: 'error', listener: (error: Error) => void): unknown
}

export type RuntimeSpawn = (command: string, args: string[], options: SpawnOptions) => RuntimeChild

export interface RuntimeRunDeps {
  spawn: RuntimeSpawn
  /** Signal the child's process tree (main passes the companion's killTree). */
  kill: (pid: number, signal: 'SIGTERM' | 'SIGKILL') => void
}

export interface RuntimeRunOptions {
  onEvent: (event: RuntimeEvent) => void
  timeoutMs: number
  deps: RuntimeRunDeps
}

export interface RuntimeRunResult {
  exitCode: number | null
  done: DoneEvent
  dropped: number
  /** True when `done` was made here, not read from the CLI. */
  synthesized: boolean
}

export interface RuntimeRun {
  cancel(): void
  result: Promise<RuntimeRunResult>
}

const MESSAGES: Readonly<Partial<Record<RuntimeErrorCode, string>>> = {
  cancelled: 'Setup was cancelled.',
  timeout: 'Setup took too long and was stopped.',
  internal: 'The local tools helper stopped unexpectedly.'
}

const syntheticDone = (outcome: DoneEvent['outcome']): DoneEvent => ({
  type: 'done',
  outcome,
  ok: 0,
  failed: 0,
  skipped: 0
})

export function startRuntimeRun(
  line: CommandLine,
  env: Record<string, string | undefined>,
  options: RuntimeRunOptions
): RuntimeRun {
  const { deps } = options
  let done: DoneEvent | null = null
  let stopReason: RuntimeErrorCode | null = null
  let settle: (r: RuntimeRunResult) => void = () => undefined
  const result = new Promise<RuntimeRunResult>((resolve) => (settle = resolve))

  const deliver = (event: RuntimeEvent): void => {
    if (done !== null) return // `done` is the last line (§6)
    if (event.type === 'done') done = event
    options.onEvent(event)
  }

  const finish = (exitCode: number | null, dropped: number): void => {
    if (done !== null) return settle({ exitCode, done, dropped, synthesized: false })
    const code = stopReason ?? 'internal'
    deliver({ type: 'error', error_code: code, message: MESSAGES[code] ?? '' })
    const synthetic = syntheticDone(code === 'cancelled' ? 'cancelled' : 'failed')
    deliver(synthetic)
    settle({ exitCode, done: synthetic, dropped, synthesized: true })
  }

  let child: RuntimeChild
  try {
    child = deps.spawn(line.command, line.args, {
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      env,
      windowsHide: true,
      detached: process.platform !== 'win32' // own group ⇒ the tree kill reaches uv's child
    })
  } catch {
    finish(null, 0)
    return { cancel: () => undefined, result }
  }

  let exited = false
  let killTimer: NodeJS.Timeout | null = null
  const stop = (reason: RuntimeErrorCode): void => {
    if (exited || stopReason !== null || child.pid === undefined) return
    stopReason = reason
    const pid = child.pid
    deps.kill(pid, 'SIGTERM')
    killTimer = setTimeout(() => {
      if (!exited) deps.kill(pid, 'SIGKILL')
    }, CANCEL_GRACE_MS)
  }

  const reader = createRuntimeLineReader({
    onEvent: deliver,
    onOverflow: () => stop('internal')
  })
  const timeout = setTimeout(() => stop('timeout'), options.timeoutMs)
  child.stdout?.on('data', (chunk: Buffer) => reader.push(chunk))
  child.stderr?.on('data', () => undefined) // drained, never logged: it may carry paths

  let closed = false
  const onEnd = (code: number | null): void => {
    if (closed) return
    closed = true
    exited = true
    clearTimeout(timeout)
    if (killTimer) clearTimeout(killTimer)
    reader.end()
    finish(code, reader.stats().dropped)
  }
  child.on('close', onEnd)
  child.on('error', () => onEnd(null))

  return { cancel: () => stop('cancelled'), result }
}
