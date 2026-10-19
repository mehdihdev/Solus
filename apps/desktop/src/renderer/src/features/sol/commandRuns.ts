// SOLUSDEV-317: an approved command's output, polled while the approve request
// is pending and kept — bounded, plain text — under the resulting message until
// the conversation is closed (sol-page.md "Output stays"). Progress grants no
// authority and never decides the outcome: the exit status comes from the
// decide response, not from these chunks.
import type { ConfirmationOutput } from '../../lib/api/resources.commands'

/** The SOLUSDEV-261 caps, unchanged: ≤256 chunks, ≤2048 chars each, ≤256 KiB. */
export const MAX_RUN_CHUNKS = 256
export const MAX_CHUNK_CHARS = 2048
export const MAX_RUN_CHARS = 262_144
export const RUN_POLL_MS = 750

export interface CommandRun {
  readonly confirmationId: string
  readonly tool: string
  readonly text: string
  readonly truncated: boolean
  /** The last progress poll failed — says nothing about the command itself. */
  readonly unavailable: boolean
  /** Null while running; `exited 0`, `timed out`, `refused: …` once finished. */
  readonly status: string | null
}

export function newCommandRun(confirmationId: string, tool: string): CommandRun {
  return { confirmationId, tool, text: '', truncated: false, unavailable: false, status: null }
}

interface RunCursor {
  readonly run: CommandRun
  readonly cursor: number
}

/** Fold one poll answer into the run. Pure; returns new objects. */
export function appendRunOutput(state: RunCursor, output: ConfirmationOutput): RunCursor {
  const next = output.chunks
    .filter((chunk) => chunk.sequence > state.cursor)
    .slice(0, MAX_RUN_CHUNKS)
    .map((chunk) => chunk.text.slice(0, MAX_CHUNK_CHARS))
    .join('')
  return {
    run: {
      ...state.run,
      text: (state.run.text + next).slice(0, MAX_RUN_CHARS),
      truncated: state.run.truncated || output.truncated,
      unavailable: false
    },
    cursor: Math.min(MAX_RUN_CHUNKS, Math.max(state.cursor, output.cursor))
  }
}

export interface RunPoller {
  /** Stop the timer and read whatever output is still unread, once. */
  finish: () => Promise<void>
  /** Stop without reading again (teardown). */
  stop: () => void
}

/** Poll `fetchOutput(cursor)` every RUN_POLL_MS until complete or stopped,
 *  reporting each new run state through `onUpdate`. */
export function startRunPoller(
  initial: CommandRun,
  fetchOutput: (cursor: number) => Promise<ConfirmationOutput>,
  onUpdate: (run: CommandRun) => void
): RunPoller {
  let state: RunCursor = { run: initial, cursor: 0 }
  let stopped = false
  let complete = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<void> = Promise.resolve()

  const read = async (): Promise<void> => {
    try {
      const output = await fetchOutput(state.cursor)
      state = appendRunOutput(state, output)
      complete = output.complete
    } catch {
      state = { ...state, run: { ...state.run, unavailable: true } }
    }
    onUpdate(state.run)
  }

  const tick = (): void => {
    inFlight = read().then(() => {
      if (!stopped && !complete) timer = setTimeout(tick, RUN_POLL_MS)
    })
  }

  const stop = (): void => {
    stopped = true
    if (timer !== undefined) clearTimeout(timer)
  }

  timer = setTimeout(tick, 0)
  return {
    stop,
    finish: async () => {
      stop()
      await inFlight
      if (!complete) await read()
    }
  }
}
