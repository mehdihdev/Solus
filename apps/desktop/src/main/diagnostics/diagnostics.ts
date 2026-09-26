// SOLUSDEV-311: the reporter every error path funnels into — renderer reports
// over IPC, main-process exceptions, gone renderers. Scrub → fingerprint →
// dedupe → cap → log (+ Sentry on the first sighting). The Sentry sink attaches
// later (it loads lazily), so errors before it exists are still logged.
import { fingerprintOf } from './fingerprint'
import { scrubReport } from './scrub'
import type { DiagnosticInput, ReportAck } from './diagnostics.constants'
import type { ErrorLog } from './errorLog'

export interface SentrySink {
  capture: (report: DiagnosticInput & { fingerprint: string }) => void
  flush: (timeoutMs: number) => Promise<void>
}

export interface DiagnosticsOptions {
  homeDir: string
  appVersion: string
  log: ErrorLog
  now?: () => Date
  /** Max log entries per session; past it one "cap reached" line, then silence. */
  sessionCap?: number
}

export interface Diagnostics {
  report: (input: DiagnosticInput) => ReportAck
  setSentry: (sink: SentrySink | null) => void
  flush: (timeoutMs: number) => Promise<void>
}

export const DEFAULT_SESSION_CAP = 200

export function createDiagnostics(options: DiagnosticsOptions): Diagnostics {
  const { homeDir, appVersion, log } = options
  const now = options.now ?? (() => new Date())
  const cap = options.sessionCap ?? DEFAULT_SESSION_CAP
  const seen = new Map<string, number>()
  let sentry: SentrySink | null = null
  let written = 0

  const writeCapped = (entry: Parameters<ErrorLog['write']>[0]): void => {
    if (written > cap) return
    written += 1
    log.write(
      written > cap
        ? { ...entry, message: 'session report cap reached; further errors are not logged' }
        : entry
    )
  }

  return {
    report(input) {
      const clean = scrubReport(input, homeDir)
      const fingerprint = fingerprintOf(clean)
      const count = (seen.get(fingerprint) ?? 0) + 1
      seen.set(fingerprint, count)
      const first = count === 1
      const base = {
        at: now().toISOString(),
        origin: clean.origin,
        surface: clean.surface,
        fingerprint,
        name: clean.name,
        message: clean.message
      }
      writeCapped(
        first
          ? { ...base, stack: clean.stack, componentStack: clean.componentStack }
          : { ...base, repeat: count }
      )
      if (first) sentry?.capture({ ...clean, fingerprint })
      return { fingerprint, first, appVersion }
    },
    setSentry(sink) {
      sentry = sink
    },
    flush: async (timeoutMs) => {
      await sentry?.flush(timeoutMs)
    }
  }
}
