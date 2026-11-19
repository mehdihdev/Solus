// SOLUSDEV-329 — one provision / install-managed run as the Settings section
// sees it, folded from mcpRuntime:progress pushes (mcp-fork-runtime.md §6, §9).
// Pure: event in, new run out — never mutated.
import type { ProvisionTrigger } from '../../../../../main/mcpRuntime/channels'
import type {
  DoneEvent,
  ForkResult,
  ForkStatus,
  ProgressEvent,
  RuntimeErrorCode,
  RuntimeErrorEvent,
  RuntimeEvent
} from '../../../../../main/mcpRuntime/protocol'

export interface RunView {
  /** Null until main answers the invoke with the id. */
  runId: string | null
  kind: 'provision' | 'install'
  trigger: ProvisionTrigger
  progress: Readonly<Record<string, ProgressEvent>>
  /** Steps not tied to one fork (the managed download). */
  global: ProgressEvent | null
  results: readonly ForkResult[]
  error: RuntimeErrorEvent | null
  done: DoneEvent | null
}

export function newRun(kind: RunView['kind'], trigger: ProvisionTrigger): RunView {
  return {
    runId: null,
    kind,
    trigger,
    progress: {},
    global: null,
    results: [],
    error: null,
    done: null
  }
}

export const isRunning = (run: RunView | null): boolean => run !== null && run.done === null

/** Fold one event into the run (events after `done` are ignored). */
export function applyRunEvent(run: RunView, event: RuntimeEvent): RunView {
  if (run.done !== null) return run
  switch (event.type) {
    case 'progress':
      return event.fork === null
        ? { ...run, global: event }
        : { ...run, progress: { ...run.progress, [event.fork]: event } }
    case 'fork_result':
      return { ...run, results: [...run.results.filter((r) => r.fork !== event.fork), event] }
    case 'error':
      return run.error === null ? { ...run, error: event } : run
    case 'done':
      return { ...run, done: event }
    default:
      return run
  }
}

/** Accept a push for this run: its own id, or the first push while the id is pending. */
export function acceptPush(
  run: RunView | null,
  runId: string,
  event: RuntimeEvent
): RunView | null {
  if (run === null || run.done !== null) return run
  if (run.runId !== null && run.runId !== runId) return run
  return applyRunEvent({ ...run, runId }, event)
}

export function failedForks(run: RunView | null): string[] {
  return (run?.results ?? []).filter((r) => r.outcome === 'failed').map((r) => r.fork)
}

/** The first failing code: the first failed tool's, else the run-level error's. */
export function firstFailingCode(run: RunView): RuntimeErrorCode | null {
  const failed = run.results.find((r) => r.outcome === 'failed' && r.error_code !== null)
  return failed?.error_code ?? run.error?.error_code ?? null
}

/** Tools that need setup: reported so, or every OS-supported tool after a new choice. */
export function forksNeedingSetup(forks: readonly ForkStatus[], choiceChanged: boolean): string[] {
  return forks
    .filter((f) => (choiceChanged ? f.state !== 'unsupported_platform' : f.state === 'needs_setup'))
    .map((f) => f.fork)
}
