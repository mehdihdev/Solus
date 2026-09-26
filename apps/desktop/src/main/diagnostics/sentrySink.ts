// SOLUSDEV-311: Sentry, main process only (renderer reports reach it over our
// own validated IPC, so the renderer CSP never widens). Loaded lazily and only
// when a DSN is configured. Privacy posture (CLAUDE.md §7 — no PII or tokens):
// sendDefaultPii off, breadcrumbs dropped, integrations allowlisted (no
// minidumps — raw memory can hold tokens — no local variables, console/net/
// fetch capture, screenshots, sessions, or the SDK's own uncaught handlers,
// which crashHandlers.ts owns), and beforeSend re-scrubs as defence in depth.
import { scrubText } from './scrub'
import type { DiagnosticInput } from './diagnostics.constants'
import type { SentrySink } from './diagnostics'

/** The slice of @sentry/electron/main this sink uses (a fake in tests). */
export interface SentryModule {
  init: (options: SentryInitOptions) => void
  captureException: (error: Error, hint: CaptureHint) => void
  flush: (timeoutMs: number) => Promise<boolean>
  IPCMode: { Classic: number }
}

interface Integration {
  name: string
}

interface SentryEventLike {
  message?: string
  exception?: { values?: Array<{ value?: string }> }
  [key: string]: unknown
}

interface SentryInitOptions {
  dsn: string
  release: string
  environment: string
  sendDefaultPii: false
  ipcMode: number
  skipOpenTelemetrySetup: true
  integrations: <T extends Integration>(defaults: T[]) => T[]
  beforeBreadcrumb: () => null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the SDK's Event type, narrowed inside
  beforeSend: (event: any) => any
}

interface CaptureHint {
  fingerprint: string[]
  tags: { origin: string; surface: string }
  contexts?: { react: { componentStack: string } }
}

/** Context and grouping only — nothing that captures data from the machine. */
export const KEPT_INTEGRATIONS: ReadonlySet<string> = new Set([
  'ElectronContext',
  'EventFilters',
  'FunctionToString',
  'LinkedErrors',
  'NormalizePaths'
])

export interface SentrySinkOptions {
  dsn: string | undefined
  environment: string
  release: string
  homeDir: string
  load?: () => Promise<SentryModule>
}

const realLoad = async (): Promise<SentryModule> =>
  (await import('@sentry/electron/main')) as unknown as SentryModule

/** Event fields that identify the machine or the person; never sent. */
const DROPPED_EVENT_KEYS = new Set(['user', 'request', 'server_name'])

function scrubEvent(event: SentryEventLike, homeDir: string): SentryEventLike {
  const rest: SentryEventLike = Object.fromEntries(
    Object.entries(event).filter(([key]) => !DROPPED_EVENT_KEYS.has(key))
  )
  const values = rest.exception?.values?.map((v) => ({
    ...v,
    ...(v.value === undefined ? {} : { value: scrubText(v.value, homeDir) })
  }))
  return {
    ...rest,
    ...(rest.message === undefined ? {} : { message: scrubText(rest.message, homeDir) }),
    ...(values === undefined ? {} : { exception: { ...rest.exception, values } })
  }
}

function toError(report: DiagnosticInput): Error {
  const error = new Error(report.message)
  error.name = report.name
  error.stack = report.stack ?? `${report.name}: ${report.message}`
  return error
}

export async function loadSentrySink(options: SentrySinkOptions): Promise<SentrySink | null> {
  const dsn = options.dsn?.trim()
  if (!dsn) return null
  let sentry: SentryModule
  try {
    sentry = await (options.load ?? realLoad)()
  } catch {
    return null
  }
  sentry.init({
    dsn,
    release: options.release,
    environment: options.environment,
    sendDefaultPii: false,
    ipcMode: sentry.IPCMode.Classic,
    skipOpenTelemetrySetup: true,
    integrations: (defaults) => defaults.filter((i) => KEPT_INTEGRATIONS.has(i.name)),
    beforeBreadcrumb: () => null,
    beforeSend: (event: SentryEventLike) => scrubEvent(event, options.homeDir)
  })
  return {
    capture: (report) =>
      sentry.captureException(toError(report), {
        fingerprint: [report.fingerprint],
        tags: { origin: report.origin, surface: report.surface },
        ...(report.componentStack
          ? { contexts: { react: { componentStack: report.componentStack } } }
          : {})
      }),
    flush: async (timeoutMs) => {
      await sentry.flush(timeoutMs)
    }
  }
}
