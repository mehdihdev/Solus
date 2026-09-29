// SOLUSDEV-311: the reporter every error path funnels into — renderer reports
// over IPC, main-process exceptions, gone renderers. Scrub → fingerprint →
// dedupe → cap → log (+ Sentry on the first sighting, only with the user's
// data-collection consent — human decision, security review M3; off until the
// main window says otherwise). The Sentry sink attaches later (it loads
// lazily), so errors before it exists are still logged.
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
  /** Max Sentry events per session, however many errors are new. */
  sentryCap?: number
  /** Max distinct fingerprints remembered; past it every error counts as a repeat. */
  maxFingerprints?: number
}

export interface Diagnostics {
  report: (input: DiagnosticInput) => ReportAck
  setSentry: (sink: SentrySink | null) => void
  /** The signed-in user's data-collection consent; false until told. */
  setConsent: (consent: boolean) => void
  flush: (timeoutMs: number) => Promise<void>
}

export const DEFAULT_SESSION_CAP = 200
export const DEFAULT_SENTRY_CAP = 50
export const DEFAULT_MAX_FINGERPRINTS = 1_000

export function createDiagnostics(options: DiagnosticsOptions): Diagnostics {
  const { homeDir, appVersion, log } = options
  const now = options.now ?? (() => new Date())
  const cap = options.sessionCap ?? DEFAULT_SESSION_CAP
  const sentryCap = options.sentryCap ?? DEFAULT_SENTRY_CAP
  const maxFingerprints = options.maxFingerprints ?? DEFAULT_MAX_FINGERPRINTS
  const seen = new Map<string, number>()
  let sentry: SentrySink | null = null
  let consent = false
  let written = 0
  let sent = 0

  /** How many times this fingerprint has been seen, counting this one. A full
   *  map stops remembering: an unknown fingerprint then reads as a repeat. */
  const sighting = (fingerprint: string): number => {
    const known = seen.get(fingerprint)
    if (known === undefined && seen.size >= maxFingerprints) return 2
    const count = (known ?? 0) + 1
    seen.set(fingerprint, count)
    return count
  }

  const sendToSentry = (report: DiagnosticInput & { fingerprint: string }): void => {
    if (!sentry || !consent || sent >= sentryCap) return
    sent += 1
    sentry.capture(report)
  }

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
      const count = sighting(fingerprint)
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
      if (first) sendToSentry({ ...clean, fingerprint })
      return { fingerprint, first, appVersion }
    },
    setSentry(sink) {
      sentry = sink
    },
    setConsent(value) {
      consent = value
    },
    flush: async (timeoutMs) => {
      await sentry?.flush(timeoutMs)
    }
  }
}
