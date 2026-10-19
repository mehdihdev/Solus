// SOLUSDEV-317: an approved command's output, polled while the approve request
// is pending and kept — bounded, plain text — under the resulting message until
// the conversation is closed (sol-page.md "Output stays"). Progress grants no
// authority and never decides the outcome: the exit status comes from the
// decide response, not from these chunks.
import type { ConfirmationOutput } from '../../lib/api/resources.commands'
import { joinTails } from '../../lib/api/solStream'

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

/** Fold one poll answer into the run. Pure; returns new objects. `truncated`
 *  is set only by a real loss: the route's flag or one of the caps above
 *  biting — never by completion (§10.3). */
export function appendRunOutput(state: RunCursor, output: ConfirmationOutput): RunCursor {
  const fresh = output.chunks.filter((chunk) => chunk.sequence > state.cursor)
  const kept = fresh.slice(0, MAX_RUN_CHUNKS)
  const next = kept.map((chunk) => chunk.text.slice(0, MAX_CHUNK_CHARS)).join('')
  const joined = state.run.text + next
  const capped =
    kept.length < fresh.length ||
    kept.some((chunk) => chunk.text.length > MAX_CHUNK_CHARS) ||
    joined.length > MAX_RUN_CHARS
  return {
    run: {
      ...state.run,
      text: joined.slice(0, MAX_RUN_CHARS),
      truncated: state.run.truncated || output.truncated || capped,
      unavailable: false
    },
    cursor: Math.min(MAX_RUN_CHUNKS, Math.max(state.cursor, output.cursor))
  }
}

/** The per-stream tail window of a command result (code server execute.py
 *  MAX_TAIL_BYTES). A tail this long may have lost its beginning. */
export const FINAL_TAIL_BYTES = 16 * 1024
// A tail cut mid-character decodes with a replacement char (3 bytes for 1–3).
const TAIL_SLACK_BYTES = 3

/** The command's own output from its result — stdout then stderr tails. */
export interface FinalOutput {
  readonly text: string
  /** A tail filled its window, so the start of that stream may be missing. */
  readonly clipped: boolean
}

const byteLength = (text: string): number => new TextEncoder().encode(text).length

/** Read `stdout_tail`/`stderr_tail` from an untrusted result value; null when
 *  neither is a string. */
export function finalOutputOf(
  value: Readonly<Record<string, unknown>> | null | undefined
): FinalOutput | null {
  const out = value?.stdout_tail
  const err = value?.stderr_tail
  if (typeof out !== 'string' && typeof err !== 'string') return null
  const tails = [out, err].map((tail) => (typeof tail === 'string' ? tail : ''))
  return {
    text: joinTails(tails[0], tails[1]).slice(0, MAX_RUN_CHARS),
    clipped: tails.some((tail) => byteLength(tail) >= FINAL_TAIL_BYTES - TAIL_SLACK_BYTES)
  }
}

/** A finished run with its result's output folded in. The live view is a
 *  lossy observation (the code server drops lines when its progress queue
 *  overflows); complete result tails replace it when it was truncated or
 *  missed lines, and never shorten complete live output. Pure. */
export function settleRun(run: CommandRun, final: FinalOutput | null): CommandRun {
  if (final === null || final.clipped) return run
  if (!run.truncated && final.text.length <= run.text.length) return run
  return { ...run, text: final.text, truncated: false }
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
