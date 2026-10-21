// SOLUSDEV-317: pure presentation helpers for the Running processes strip.
import { ApiError } from '../../lib/api/envelope.types'
import type { CodeProcess } from '../../lib/api/resources.commands'

export const OUTPUT_POLL_MS = 1_000
/** Client ceiling on retained process output (the server ring is 256 KiB). */
export const MAX_PROCESS_OUTPUT_CHARS = 262_144
export const MAX_CHUNK_CHARS = 2048
export const STOP_ERROR = 'That process could not be stopped.'
export const INPUT_ERROR = 'That input could not be sent.'
export const NOT_WAITING = 'No longer waiting'
export const INPUT_OFFLINE = 'This computer’s Solus connection is offline — reconnect to answer.'
export const INPUT_GONE = 'That process is no longer running.'

/** Why the person's input did not reach the process (§11.2 route errors).
 *  Server text is never shown; a local validation message is. */
export function inputErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error && error.message ? error.message : INPUT_ERROR
  }
  if (error.status === 404) return INPUT_GONE
  if (error.status !== 409) return INPUT_ERROR
  if (error.code === 'not_waiting') return NOT_WAITING
  return error.code === 'bridge_offline' ? INPUT_OFFLINE : INPUT_ERROR
}

export function programName(process: CodeProcess): string {
  return process.name ?? process.argv[0]?.split('/').filter(Boolean).pop() ?? process.process_id
}

export function stateLabel(process: CodeProcess): string {
  switch (process.state) {
    case 'running':
      return 'running'
    case 'exited':
      return process.exit_code === null ? 'exited' : `exited ${process.exit_code}`
    case 'stopped':
      return 'stopped'
    case 'timed_out':
      return 'timed out'
    case 'failed_to_start':
      return 'failed to start'
  }
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  const pad = (n: number): string => String(n).padStart(2, '0')
  if (s < 3600) return `${Math.floor(s / 60)}m ${pad(s % 60)}s`
  return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`
}

export function elapsed(process: CodeProcess, readAt: number): string {
  const start = Date.parse(process.started_at)
  const end = process.ended_at ? Date.parse(process.ended_at) : readAt
  return Number.isNaN(start) || Number.isNaN(end) ? '' : formatElapsed((end - start) / 1000)
}
