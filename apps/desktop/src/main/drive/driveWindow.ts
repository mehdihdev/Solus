// SOLUSDEV-319 drive slice 3 (docs/architecture/sol-drive.md §3 "Outline
// geometry"): the companion writes `{"type":"drive_window","bounds":{…}}` to
// stdout after each ok identify/capture/act. The child is untrusted input to
// main: lines are bounded, parsed defensively, and anything that is not
// exactly that shape is ignored without logging its content.
import type { Rect } from '../capture/screenCapture'

/** A line longer than this is dropped whole (the real one is ~90 bytes). */
export const MAX_STDOUT_LINE_BYTES = 4 * 1024
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

/** The companion stdout reader: lines → valid bounds only. */
export function createDriveWindowReader(onBounds: (bounds: Rect) => void): LineSplitter {
  return createLineSplitter((line) => {
    const bounds = parseDriveWindowLine(line)
    if (bounds !== null) onBounds(bounds)
  })
}
