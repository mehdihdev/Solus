// SOLUSDEV-319 drive slices 3/3b (docs/architecture/sol-drive.md §3): the
// companion's stdout carries `drive_window` geometry after each ok
// identify/capture/act, and (3b, XPC) the relay's `drive_request` /
// `drive_cancel` lines. The child is untrusted input to
// main: lines are bounded, parsed defensively, and anything that is not
// exactly that shape is ignored without logging its content.
import type { Rect } from '../capture/screenCapture'

/** A line longer than this is dropped whole. A drive_window line is ~90 bytes;
 *  a drive_request (an act `type --text`) stays far below this. */
export const MAX_STDOUT_LINE_BYTES = 64 * 1024
/** argv entries in one drive_request. */
export const MAX_DRIVE_ARGS = 64
/** Global points: beyond any real display arrangement. */
const MAX_COORD = 100_000
const MAX_SIZE = 32_768

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const coord = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= MAX_COORD

const size = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v > 0 && v <= MAX_SIZE

function parseJson(line: string): unknown {
  try {
    return JSON.parse(line)
  } catch {
    return null
  }
}

/** The window bounds from one stdout line, or null. */
export function parseDriveWindowLine(line: string): Rect | null {
  const value = parseJson(line)
  if (!isRecord(value) || value.type !== 'drive_window' || !isRecord(value.bounds)) return null
  const { x, y, width, height } = value.bounds
  return coord(x) && coord(y) && size(width) && size(height) ? { x, y, width, height } : null
}

export interface LineSplitter {
  push(chunk: Buffer): void
}

/** Newline-delimited lines from a byte stream with a bounded buffer: an
 *  over-long line is discarded up to its newline, never accumulated. */
export function createLineSplitter(onLine: (line: string) => void): LineSplitter {
  let pending = ''
  let discarding = false
  return {
    push(chunk) {
      const parts = (pending + chunk.toString('utf8')).split('\n')
      pending = parts.pop() ?? ''
      for (const part of parts) {
        if (!discarding && part.length > 0 && Buffer.byteLength(part) <= MAX_STDOUT_LINE_BYTES) {
          onLine(part)
        }
        discarding = false
      }
      if (Buffer.byteLength(pending) >= MAX_STDOUT_LINE_BYTES) {
        pending = ''
        discarding = true
      }
    }
  }
}

const hasExactKeys = (value: Record<string, unknown>, keys: readonly string[]): boolean => {
  const own = Object.keys(value)
  return own.length === keys.length && keys.every((k) => Object.hasOwn(value, k))
}

const positiveId = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) > 0

const isArgv = (v: unknown): v is string[] =>
  Array.isArray(v) &&
  v.length > 0 &&
  v.length <= MAX_DRIVE_ARGS &&
  v.every((a) => typeof a === 'string' && !a.includes('\0'))

export interface DriveRequestLine {
  id: number
  argv: string[]
}

/** Exactly `{"type":"drive_request","id":N,"argv":[…]}` (sol-drive.md §3). */
export function parseDriveRequest(line: string): DriveRequestLine | null {
  const value = parseJson(line)
  if (!isRecord(value) || value.type !== 'drive_request') return null
  if (!hasExactKeys(value, ['type', 'id', 'argv'])) return null
  return positiveId(value.id) && isArgv(value.argv) ? { id: value.id, argv: value.argv } : null
}

/** Exactly `{"type":"drive_cancel","id":N}`; the id, or null. */
export function parseDriveCancel(line: string): number | null {
  const value = parseJson(line)
  if (!isRecord(value) || value.type !== 'drive_cancel') return null
  return hasExactKeys(value, ['type', 'id']) && positiveId(value.id) ? value.id : null
}

export interface CompanionStdoutHandlers {
  onBounds(bounds: Rect): void
  onRequest(request: DriveRequestLine): void
  onCancel(id: number): void
}

/** The companion stdout reader: valid drive lines only; everything else is ignored. */
export function createCompanionStdoutReader(handlers: CompanionStdoutHandlers): LineSplitter {
  return createLineSplitter((line) => {
    const bounds = parseDriveWindowLine(line)
    if (bounds !== null) return handlers.onBounds(bounds)
    const request = parseDriveRequest(line)
    if (request !== null) return handlers.onRequest(request)
    const cancel = parseDriveCancel(line)
    if (cancel !== null) handlers.onCancel(cancel)
  })
}
