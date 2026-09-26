// SOLUSDEV-311: the local error log — stdout for the dev terminal, plus a
// size-capped JSON-lines file under app.getPath('logs') so a packaged build
// leaves evidence. One rotation (`.1`) bounds disk use at ~2× maxBytes.
// Entries arrive already scrubbed. Never throws: a failing disk must not turn
// one error into a crash loop.
import { appendFileSync, renameSync, statSync } from 'node:fs'
import type { ErrorOrigin, ErrorSurface } from './diagnostics.constants'

export interface ErrorLogEntry {
  at: string
  origin: ErrorOrigin
  surface: ErrorSurface
  fingerprint: string
  name: string
  message: string
  stack?: string
  componentStack?: string
  /** Set on a repeat sighting: how many times this fingerprint has been seen. */
  repeat?: number
}

export interface ErrorLogDeps {
  append: (path: string, text: string) => void
  size: (path: string) => number | null
  rename: (from: string, to: string) => void
  stderr: (line: string) => void
}

export interface ErrorLog {
  write: (entry: ErrorLogEntry) => void
}

export const ERROR_LOG_FILENAME = 'solus-errors.log'
export const ERROR_LOG_MAX_BYTES = 1_000_000

function consoleLines(entry: ErrorLogEntry): string {
  const head = `[solus:error] ${entry.origin} ${entry.surface} ${entry.name}: ${entry.message} (${entry.fingerprint})`
  if (entry.repeat !== undefined) return `${head} ×${entry.repeat}`
  return [head, entry.stack, entry.componentStack].filter(Boolean).join('\n')
}

export function createErrorLog(options: {
  path: string
  maxBytes: number
  deps: ErrorLogDeps
}): ErrorLog {
  const { path, maxBytes, deps } = options
  return {
    write(entry) {
      deps.stderr(consoleLines(entry))
      const line = `${JSON.stringify(entry)}\n`
      try {
        const current = deps.size(path) ?? 0
        if (current > 0 && current + Buffer.byteLength(line) > maxBytes)
          deps.rename(path, `${path}.1`)
        deps.append(path, line)
      } catch (error) {
        deps.stderr(
          `[solus:error] could not write error log: ${error instanceof Error ? error.message : 'unknown'}`
        )
      }
    }
  }
}

export const realErrorLogDeps: ErrorLogDeps = {
  append: (path, text) => appendFileSync(path, text, { encoding: 'utf8', mode: 0o600 }),
  size: (path) => {
    try {
      return statSync(path).size
    } catch {
      return null
    }
  },
  rename: (from, to) => renameSync(from, to),
  stderr: (line) => console.error(line)
}
